"""Unity Gateway migration apply (prototype, opt-in).

Creates the Unity Gateway objects that ug_migration_planner proposes for
external model and Provisioned Throughput endpoints: model provider services,
model services (routing, fallback, rate limits, inference table) and EXECUTE /
MANAGE grants. Applying doesn't change legacy endpoints, and clients keep
calling them until their code changes, so applying is safe to do ahead of the
cutover. The cut-over operations do change legacy endpoints: pause_legacy sets
the rate limit to 0 and enable_tracking turns usage tracking on (both re-send
the rest of the AI Gateway config; resume_legacy undoes a pause).

DRY RUN BY DEFAULT: without --execute it only prints what it would create.
Every object it creates is written to a log, and `rollback` deletes only the
objects that log says this run created (and that still carry this run's
apply mark). USER_GUIDE.md covers the safety rules.

    python ug_migration_apply.py --profile P apply --endpoints a,b --target-catalog c --target-schema s
    python ug_migration_apply.py --profile P apply --endpoints a,b ... --execute --uc-secret-map map.json \\
        --allowed-secret-schemas c.secrets
    python ug_migration_apply.py --profile P rollback --log apply_log.jsonl --execute

Secrets: legacy endpoints reference workspace secrets ({{secrets/scope/key}}).
Model provider services take either a Unity Catalog secret reference
(--uc-secret-map '{"scope/key": "secrets/catalog.schema.name"}', preferred; the
schema must be in --allowed-secret-schemas) or the value itself
(--allow-secret-read, which also needs --allow-secret-read-enabled; the value is
never printed or logged).

Supported providers in this prototype: OpenAI, Azure OpenAI (API key) and
Anthropic. Others are reported as manual.

Written by STS as a prototype; not an official Databricks tool.
"""

from __future__ import annotations

import argparse
import base64
import copy
import glob
import json
import os
import re
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone

from databricks.sdk import WorkspaceClient
from databricks.sdk.common.types.fieldmask import FieldMask
from databricks.sdk.errors import AlreadyExists, DatabricksError, NotFound
from databricks.sdk.service import catalog

import ug_migration_planner as planner

SECRET_RE = re.compile(r"^\{\{\s*secrets/([^/}]+)/([^}]+?)\s*\}\}$")
UC_SECRET_RE = re.compile(r"^secrets/([^.\s/]+)\.([^.\s/]+)\.([^.\s/]+)$")

NATIVE_API_TYPES = {
    ("openai", "llm/v1/chat"): ["openai/v1/chat/completions"],
    ("openai", "llm/v1/completions"): ["openai/v1/completions"],
    ("openai", "llm/v1/embeddings"): ["openai/v1/embeddings"],
    ("azure_openai", "llm/v1/chat"): ["openai/v1/chat/completions"],
    ("azure_openai", "llm/v1/completions"): ["openai/v1/completions"],
    ("azure_openai", "llm/v1/embeddings"): ["openai/v1/embeddings"],
    ("anthropic", "llm/v1/chat"): ["anthropic/v1/messages"],
}
PROVIDER_TYPES = {
    "openai": "EXTERNAL_MODEL_PROVIDER_TYPE_OPENAI",
    "azure_openai": "EXTERNAL_MODEL_PROVIDER_TYPE_AZURE_OPENAI",
    "anthropic": "EXTERNAL_MODEL_PROVIDER_TYPE_ANTHROPIC",
}


class Manual(Exception):
    """Raised when an endpoint needs a human instead of automation."""


class PolicyError(Exception):
    """Fails the whole run before any change (secret policy, another run holding the target)."""


def _leaf(fqn: str) -> tuple[str, str]:
    parts = (fqn or "").split(".")
    if len(parts) != 3 or not all(parts):
        raise Manual(f"{fqn!r} isn't a catalog.schema.name; use catalog and schema names without dots")
    c, s, n = parts
    return f"schemas/{c}.{s}", n


def _safe(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", (name or "dest").lower())[:60]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Ownership mark
# ---------------------------------------------------------------------------

TOOL_MARK = "ug-migration-toolkit"
_OWNER_RE = re.compile(re.escape(TOOL_MARK) + r" apply=([A-Za-z0-9_\-]+)")
ROLLBACK_TYPES = ("model_service", "model_provider_service", "uc_secret")
# created_secret is the uc_secret form of created (the job made a Unity Catalog secret from a workspace secret).
CREATED_ACTIONS = ("created", "creating", "created_secret")
OWNED_ACTIONS = ("created", "creating", "exists", "updated", "created_secret")  # actions that put an object in a rollback log
USE_ACTIONS = ("created", "creating", "exists", "updated", "created_secret")  # actions that keep an object in use (protection)
# Item actions that make a run NEEDS_ATTENTION. Shared by the job (run status) and the store (rolled back).
PROBLEM_ACTIONS = ("error", "manual", "mismatch", "kept", "needs_attention", "smoke_failed", "test_failed", "refused",
                   "missing", "protection_lost", "check_failed")
READY_STATES = ("ACTIVE", "READY", "ONLINE")
STALE_RUN_HOURS = 12


def owner_comment(apply_id: str | None, detail: str = "") -> str:
    """Comment stamped on every object the toolkit creates: TOOL_MARK plus the apply id."""
    prefix = f"{detail}. " if detail else ""
    return f"{prefix}Created by {TOOL_MARK} apply={apply_id or 'none'}, toolkit {planner.__version__} (prototype)"


def is_toolkit(comment: str | None) -> bool:
    return TOOL_MARK in (comment or "")


def owner_tag(comment: str | None) -> str | None:
    m = _OWNER_RE.search(comment or "")
    return m.group(1) if m else None


def _stamp(obj) -> dict:
    d = (obj.as_dict() if obj is not None else None) or {}
    return {k: d[k] for k in ("etag", "update_time") if d.get(k) is not None}


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------


def check_secret_policy(uc_map: dict | None, allowed_schemas, allow_read_requested: bool, read_enabled: bool) -> None:
    """Fail before any change unless the secret settings are allowed for this job.

    Unity Catalog names are case-insensitive, so schema names are compared in lower case (the app does the same)."""
    allowed = {s.strip().lower() for s in allowed_schemas or [] if s and s.strip()}
    for s in allowed:
        if s.count(".") != 1:
            raise PolicyError(f"secret schema {s!r} must be catalog.schema")
    if allow_read_requested and not read_enabled:
        raise PolicyError("reading secret values (allow_secret_read) is requested but not enabled for this job; "
                          "the installer has to enable it (--allow-secret-read-enabled on the CLI)")
    for key, ref in (uc_map or {}).items():
        m = UC_SECRET_RE.match(ref or "")
        if not m:
            raise PolicyError(f"uc secret map entry {key!r} must be secrets/catalog.schema.name")
        if not allowed:
            raise PolicyError("UC secret mapping is disabled: no secret schemas are allowed for this job "
                              "(secret_schemas is empty); set --allowed-secret-schemas or the job's secret_schemas")
        if f"{m.group(1)}.{m.group(2)}".lower() not in allowed:
            raise PolicyError(f"{ref} is outside the allowed secret schemas {sorted(allowed)}")


class Secrets:
    def __init__(self, w: WorkspaceClient | None, uc_map: dict[str, str] | None, allow_read: bool,
                 dry_run: bool = False, allowed_schemas=(), read_enabled: bool = False, create_uc: bool = False):
        self.w, self.uc_map, self.allow_read, self.dry_run = w, uc_map or {}, allow_read, dry_run
        self.allowed_schemas = list(allowed_schemas or [])
        self.read_enabled = read_enabled
        # create_uc: the job creates each mapped Unity Catalog secret from its workspace secret (ensure_uc_secrets).
        self.create_uc = create_uc
        self._checked: set[str] = set()
        self._failed: dict[str, str] = {}  # scope/key -> why its Unity Catalog secret isn't available

    def validate_policy(self) -> None:
        check_secret_policy(self.uc_map, self.allowed_schemas, self.allow_read, self.read_enabled)

    def _check_exists(self, ref: str) -> None:
        """Read-only GET of the Unity Catalog secret before a provider service refers to it."""
        if ref in self._checked or self.w is None:
            return
        m = UC_SECRET_RE.match(ref)
        full = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
        try:
            self.w.secrets_uc.get_secret(full)
        except NotFound:
            raise PolicyError(f"Unity Catalog secret {full} doesn't exist: create it first")
        self._checked.add(ref)

    def resolve(self, value: str | None, plaintext: str | None = None) -> dict:
        """Return a ProviderSecret dict: {'secret_reference': ...} or {'plaintext': ...}."""
        if plaintext:
            # The inventory never holds real plaintext keys (they're redacted on read, and the API may not
            # return them), so copying one would create a provider with a bogus credential.
            raise Manual("the endpoint uses a plaintext API key: store it as a Unity Catalog secret, then "
                         "create the provider service with a secret reference (or use the Terraform output)")
        m = SECRET_RE.match(value or "")
        if not m and not value:
            # The serving API doesn't return plaintext keys, so an endpoint configured with one reads as no key.
            raise Manual("the endpoint has no {{secrets/scope/key}} reference (most likely a plaintext API key, which "
                         "the API doesn't return): store the key as a Unity Catalog secret, then reference it")
        if not m:
            raise Manual("credential is not a {{secrets/scope/key}} reference")
        key = f"{m.group(1)}/{m.group(2)}"
        if key in self._failed:
            raise Manual(self._failed[key])
        if key in self.uc_map:
            ref = self.uc_map[key]
            self._check_exists(ref)
            return {"secret_reference": {"name": ref}}
        if self.allow_read:
            if self.dry_run:
                return {"plaintext": f"<value of {key}, read at --execute>"}
            raw = self.w.secrets.get_secret(m.group(1), m.group(2)).value
            return {"plaintext": base64.b64decode(raw).decode()}
        raise Manual(f"secret {key}: add it to --uc-secret-map (and its schema to --allowed-secret-schemas) "
                     "or pass --allow-secret-read")


def workspace_secret_keys(dest: dict) -> list[str]:
    """The scope/key of every {{secrets/scope/key}} reference in a destination's provider config."""
    found: list[str] = []

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            m = SECRET_RE.match(o)
            if m and f"{m.group(1)}/{m.group(2)}" not in found:
                found.append(f"{m.group(1)}/{m.group(2)}")
    walk(dest.get("provider_config") or {})
    return found


UC_NAME_MAX = 255


def uc_secret_name(scope_key: str) -> str:
    """Default Unity Catalog secret name for a workspace secret: scope_key, lower case, [a-z0-9_] only."""
    leaf = re.sub(r"[^a-z0-9_]+", "_", scope_key.lower().replace("/", "_")).strip("_") or "secret"
    return leaf[:UC_NAME_MAX]


def _scrub(text: str, value: str | None) -> str:
    """An error message with a secret value removed (an API error must never carry it into a row or a log)."""
    text = str(text)
    if value:
        text = text.replace(value, "***")
    return text[:500]


def ensure_uc_secrets(a: "Applier", secrets: Secrets, groups: dict[str, list[dict]], provider_fqn: dict[str, str]) -> None:
    """Create the Unity Catalog secret each mapped workspace secret needs (Secrets.create_uc).

    The job identity reads the workspace secret and writes its value to the Unity Catalog secret named in the map;
    the value is never printed, logged or kept. A secret that already exists is reused (its value can't be compared).
    A dry run only checks that the workspace secret can be read. Failures make the providers that need the key
    manual (Secrets._failed)."""
    used_by: dict[str, list[str]] = {}
    for key, dests in groups.items():
        for d in dests:
            for sk in workspace_secret_keys(d):
                used_by.setdefault(sk, [])
                if provider_fqn[key] not in used_by[sk]:
                    used_by[sk].append(provider_fqn[key])
    for sk in sorted(used_by):
        ref = secrets.uc_map.get(sk)
        m = UC_SECRET_RE.match(ref or "")
        if not m:
            why = f"no Unity Catalog secret name was chosen for workspace secret {sk}"
            secrets._failed[sk] = why
            a.log(type="uc_secret", name=sk, action="manual", reason=why, workspace_secret=sk)
            continue
        full = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
        info = dict(workspace_secret=sk, used_by=sorted(used_by[sk]))
        try:
            existing = a.w.secrets_uc.get_secret(full)
        except NotFound:
            existing = None
        except Exception as e:
            secrets._failed[sk] = f"couldn't check Unity Catalog secret {full}: {_scrub(e, None)}"
            a.log(type="uc_secret", name=full, action="error", reason=secrets._failed[sk], **info)
            continue
        if existing is not None:
            secrets._checked.add(ref)
            owner = owner_tag(getattr(existing, "comment", None))
            a.log(type="uc_secret", name=full, action="exists", owner=owner, **info, **_stamp(existing),
                  note="already exists, so it's reused; its value can't be compared with the workspace secret, so "
                       f"check that it holds the key from {sk}")
            continue
        scope, key = sk.split("/", 1)
        value = None
        try:
            raw = a.w.secrets.get_secret(scope, key).value
            value = base64.b64decode(raw).decode() if raw else ""
        except Exception:
            why = f"the job identity can't read workspace secret {sk}: grant READ on the scope"
            secrets._failed[sk] = why
            a.log(type="uc_secret", name=full, action="manual", reason=why, **info)
            continue
        try:
            if not value:
                why = f"workspace secret {sk} is empty"
                secrets._failed[sk] = why
                a.log(type="uc_secret", name=full, action="manual", reason=why, **info)
                continue
            if not a.execute:
                secrets._checked.add(ref)  # the dry run proceeds as if it existed
                a.log(type="uc_secret", name=full, action="would_create_secret", **info)
                continue
            a.log(type="uc_secret", name=full, action="creating", **info)
            try:
                created = a.w.secrets_uc.create_secret(catalog.Secret(
                    name=m.group(3), catalog_name=m.group(1), schema_name=m.group(2), value=value,
                    comment=owner_comment(a.apply_id, f"From workspace secret {sk}")))
            except AlreadyExists:  # created between the GET and the create
                secrets._checked.add(ref)
                a.log(type="uc_secret", name=full, action="exists", **info,
                      note="created by someone else at the same time; reused, value not compared")
                continue
            secrets._checked.add(ref)
            a.log(type="uc_secret", name=full, action="created_secret", **info, **_stamp(created))
        except Exception as e:
            secrets._failed[sk] = f"couldn't create Unity Catalog secret {full}: {_scrub(e, value)}"
            a.log(type="uc_secret", name=full, action="error", reason=secrets._failed[sk], **info)
        finally:
            value = None


SENSITIVE_KEY_RE = re.compile(r"(^|_)(secret|token|password|passwd|api_?key)(_|$)", re.I)
NOT_SENSITIVE_KEYS = {"secret_reference", "secret_schemas", "allowed_secret_schemas", "workspace_secret"}


def _mask(obj):
    """Copy of a payload with secret values hidden, for printing and logs.

    Hides any 'plaintext' value and any string or number under a key that names a secret, token, password
    or API key (for example api_key, client_secret, access_token). Booleans, lists of rate limits ('tokens')
    and references to Unity Catalog secrets are kept."""
    def walk(o, key=None):
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                if k == "plaintext":
                    out[k] = "***"
                elif (isinstance(k, str) and k not in NOT_SENSITIVE_KEYS and SENSITIVE_KEY_RE.search(k)
                      and isinstance(v, (str, int, float)) and not isinstance(v, bool)):
                    out[k] = "***"
                else:
                    out[k] = walk(v, k)
            return out
        if isinstance(o, list):
            return [walk(v, key) for v in o]
        return o
    return walk(copy.deepcopy(obj))


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def provider_family(dest: dict) -> str:
    provider = (dest.get("provider") or "").lower()
    cfg = (dest.get("provider_config") or {}).get("openai_config") or {}
    if provider == "openai" and (cfg.get("openai_api_type") or "").lower() in ("azure", "azuread"):
        if (cfg.get("openai_api_type") or "").lower() == "azuread":
            raise Manual("Azure OpenAI with Entra ID auth: configure the provider service by hand")
        return "azure_openai"
    if provider in ("openai", "anthropic"):
        return provider
    raise Manual(f"provider {provider!r} isn't automated in this prototype")


def provider_model(dest: dict, family: str) -> str:
    cfg = (dest.get("provider_config") or {}).get("openai_config") or {}
    if family == "azure_openai":
        return cfg.get("openai_deployment_name") or dest.get("model")
    return dest.get("model")


def build_provider(dests: list[dict], secrets: Secrets, apply_id: str | None = None) -> dict:
    """ModelProviderService body for destinations that share one provider and credential."""
    d0 = dests[0]
    family = provider_family(d0)
    pc = d0.get("provider_config") or {}
    if family in ("openai", "azure_openai"):
        cfg = pc.get("openai_config") or {}
        secret = secrets.resolve(cfg.get("openai_api_key"), cfg.get("openai_api_key_plaintext"))
        direct = {"api_key": secret}
        if cfg.get("openai_api_base"):
            direct["base_url"] = cfg["openai_api_base"]
        if family == "openai" and cfg.get("openai_organization"):
            direct["organization"] = cfg["openai_organization"]
        if family == "azure_openai" and not cfg.get("openai_api_base"):
            raise Manual("Azure OpenAI endpoint without openai_api_base")
        provider_cfg = {family: {"direct": direct}}
    else:
        cfg = pc.get("anthropic_config") or {}
        provider_cfg = {"anthropic": {"direct": {"api_key": secrets.resolve(
            cfg.get("anthropic_api_key"), cfg.get("anthropic_api_key_plaintext"))}}}
    targets, seen = [], set()
    for d in dests:
        model = provider_model(d, family)
        api_types = NATIVE_API_TYPES.get((family, d.get("task")))
        if not api_types:
            raise Manual(f"task {d.get('task')!r} for {family} isn't mapped yet")
        if model not in seen:
            seen.add(model)
            targets.append({"model": model, "native_api_types": api_types})
    return {"comment": owner_comment(apply_id),
            "config": {"provider_type": PROVIDER_TYPES[family], "allow_all_targets": False,
                       "targets": targets, **provider_cfg}}


_W: WorkspaceClient | None = None


def check_pt_model(dest: dict) -> None:
    """Fail early with a clear reason when a PT endpoint serves a model that no longer exists."""
    model = dest.get("model")
    if _W is None or not model or model.count(".") != 2:
        return
    try:
        _W.registered_models.get(model)
    except NotFound:
        raise Manual(f"PT endpoint serves {model}, which no longer exists: retire or redeploy the endpoint")
    except Exception:
        pass


MAX_DESTINATIONS = 10  # Unity Gateway limit per model service (primary destinations)
MAX_FALLBACKS = 5  # Unity Gateway limit per model service (fallback destinations)
MAX_RATE_LIMITS = 20  # toolkit safety cap per model service (not a Unity Gateway limit)
MAX_GROUP_RATE_LIMITS = 5  # toolkit safety cap on group-specific limits per model service


def guardrail_items(row: planner.PlanRow) -> list[str]:
    """Planner items about legacy guardrails (blocking or not). They need --ack-guardrails to apply."""
    out = []
    for n in row.needs_human:
        text = n.removeprefix(planner.BLOCKING_PREFIX)
        if text.startswith("guardrails"):  # "guardrails:", "guardrails not carried over: ...", "guardrails acknowledged ..."
            out.append(text)
    return out


CARRIED_GATEWAY_KEYS = ("rate_limits", "guardrails", "inference_table_config", "usage_tracking_config", "fallback_config")


def not_carried_over(ep: planner.LegacyEndpoint, row: planner.PlanRow, grants: bool) -> list[str]:
    """Governance on the legacy endpoint that the new model service doesn't get. Every apply item for the service
    lists these (not_carried_over), so the result says plainly what a person still has to redo or decide."""
    out = []
    if ep.guardrails:
        out.append("guardrails: " + planner.guardrail_consequence(ep.guardrails))
    if ep.rate_limits and not row.rate_limits:
        out.append("rate limits")
    if (ep.inference_table or ep.auto_capture) and not row.inference_table:
        out.append("inference table logging")
    elif row.inference_table:
        out.append("inference table history (the new service logs to a new <prefix>_ug_payload table)")
    if ep.usage_tracking:
        out.append("usage tracking setting (Unity Gateway usage is in system.ai_gateway.usage, not "
                   "system.serving.endpoint_usage)")
    if ep.tags:
        out.append(f"endpoint tags ({len(ep.tags)})")
    if ep.route_optimized:
        out.append("route optimization and its endpoint URL")
    if ep.budget_policy_id:
        out.append("budget policy")
    if ep.usage_policy_id:
        out.append("usage policy")
    if ep.can_query and not (grants and row.grants):
        out.append("endpoint permissions (grants were not copied)" if not grants
                   else "endpoint permissions (none map to Unity Catalog grants)")
    other = [k for k in ep.gateway_settings if k not in CARRIED_GATEWAY_KEYS]
    if other:
        out.append(f"AI Gateway settings {', '.join(sorted(other))}")
    return out


def build_model_service(ep: planner.LegacyEndpoint, row: planner.PlanRow, provider_fqn: dict[str, str],
                        apply_id: str | None = None, ack_guardrails: bool = False) -> dict:
    """ModelService body: destinations, fallback, rate limits and inference table."""
    guards = guardrail_items(row)
    blocking = [n.removeprefix(planner.BLOCKING_PREFIX) for n in row.needs_human
                if n.startswith(planner.BLOCKING_PREFIX)]
    blocking = [b for b in blocking if not b.startswith("guardrails")]
    if guards and not ack_guardrails:
        blocking += guards
    if blocking:
        raise Manual("; ".join(blocking))
    pct = {r.get("served_model_name") or r.get("served_entity_name"): r.get("traffic_percentage")
           for r in ep.traffic_routes}
    entity_names = {d.get("served_entity") for d in ep.destinations}
    if pct and set(pct) - entity_names:
        raise Manual(f"traffic routes name served entities that don't exist: {sorted(set(pct) - entity_names)}")
    used_names: set[str] = set()
    dests = []
    for d in ep.destinations:
        name = _safe(d.get("served_entity") or d.get("model"))
        base, n = name, 2
        while name in used_names:  # 'gpt-5' and 'gpt_5' would both become gpt_5
            name, n = f"{base}_{n}", n + 1
        used_names.add(name)
        if d["type"] == "external_model":
            family = provider_family(d)
            api_types = NATIVE_API_TYPES.get((family, d.get("task")))
            if not api_types:
                raise Manual(f"task {d.get('task')!r} for {family} isn't mapped yet")
            fqn = provider_fqn[planner._provider_key(d)]
            dests.append(({"name": name, "destination_type": "DESTINATION_TYPE_EXTERNAL_FOUNDATION_MODEL",
                           "external_model_config": {
                               "model_provider_service": f"model-provider-services/{fqn}",
                               "target": {"model": provider_model(d, family), "native_api_types": api_types}}},
                          pct.get(d.get("served_entity"))))
        elif d["type"] == "provisioned_throughput":
            check_pt_model(d)
            dests.append(({"name": name, "destination_type": "DESTINATION_TYPE_PROVISIONED_THROUGHPUT_FOUNDATION_MODEL",
                           "provisioned_throughput_config": {"model_serving_endpoint": f"serving-endpoints/{ep.name}"}},
                          pct.get(d.get("served_entity"))))
        else:
            raise Manual(f"destination type {d['type']} isn't automated")
    if not dests:
        raise Manual("no destinations")

    if len(dests) == 1:
        primary, fallback = [dests[0][0]], []
    else:
        if any(p is None for _, p in dests):
            raise Manual("several destinations without traffic percentages")
        if sum(p for _, p in dests) != 100:
            raise Manual(f"traffic percentages add up to {sum(p for _, p in dests)}, not 100")
        primary = [d for d, p in dests if p > 0]
        if not primary:
            raise Manual("every destination has 0% traffic")
        if len(primary) > 1:
            for d, p in dests:
                if p > 0:
                    d["traffic_percentage"] = p
        # Legacy fallback tries the other served entities in listing order. Destinations that carry traffic
        # are primaries and 0% destinations become the fallback. When every served entity carries traffic (a split)
        # there is nothing to fall back to without making a primary also a fallback, which the toolkit doesn't do:
        # the endpoint is left for a person rather than silently losing its fallback.
        fallback = [d for d, p in dests if p == 0] if ep.fallback_enabled else []
        if ep.fallback_enabled and not fallback:
            raise Manual(f"fallback is on and traffic is split across {len(primary)} served entities with no 0% "
                         "entity, so the toolkit can't carry the fallback over. Add a 0% served entity to use as the "
                         "fallback, or create this model service by hand")
        if len(fallback) > MAX_FALLBACKS:
            raise Manual(f"{len(fallback)} fallback destinations; Unity Gateway allows {MAX_FALLBACKS}")
    if len(primary) > MAX_DESTINATIONS:
        raise Manual(f"{len(primary)} primary destinations; Unity Gateway allows {MAX_DESTINATIONS}")
    routing = {"destinations": primary}
    if fallback:
        routing["fallback"] = {"destinations": fallback}
    config = {"routing": routing}
    if row.rate_limits:
        groups = [l for l in row.rate_limits if str(l.get("key", "")).upper().endswith("USER_GROUP")]
        if len(row.rate_limits) > MAX_RATE_LIMITS or len(groups) > MAX_GROUP_RATE_LIMITS:
            raise Manual(f"{len(row.rate_limits)} rate limits ({len(groups)} for groups); toolkit safety caps per "
                         f"model service: {MAX_RATE_LIMITS} ({MAX_GROUP_RATE_LIMITS} for groups). These are toolkit "
                         "safety caps, not Unity Gateway limits; merge some limits first")
        config["rate_limits"] = row.rate_limits
    if row.inference_table:
        config["inference_table"] = {k: v for k, v in row.inference_table.items() if k in ("parent", "table_name_prefix")}
    return {"comment": owner_comment(apply_id, f"Migrated from legacy serving endpoint {ep.name}"),
            "config": config}


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------


def _dest_sig(d: dict) -> tuple:
    ext = d.get("external_model_config") or {}
    pt = d.get("provisioned_throughput_config") or {}
    return (d.get("name"), d.get("destination_type"), ext.get("model_provider_service"),
            (ext.get("target") or {}).get("model"), pt.get("model_serving_endpoint"), d.get("traffic_percentage"))


def _limit_sig(l: dict) -> tuple:
    return (l.get("key"), l.get("renewal_period"), l.get("principal"), l.get("requests"), l.get("tokens"))


def service_differences(have: dict, want: dict) -> list[str]:
    """What differs between a model service config as read back and the planned one."""
    diffs = []
    have_r, want_r = have.get("routing") or {}, want.get("routing") or {}
    for part in ("destinations", "fallback"):
        if part == "fallback":
            g = (have_r.get("fallback") or {}).get("destinations") or []
            w_ = (want_r.get("fallback") or {}).get("destinations") or []
        else:
            g, w_ = have_r.get("destinations") or [], want_r.get("destinations") or []
        if [_dest_sig(d) for d in g] != [_dest_sig(d) for d in w_]:
            diffs.append(f"{part} differ: have {[_dest_sig(d) for d in g]}, want {[_dest_sig(d) for d in w_]}")
    if sorted((_limit_sig(l) for l in have.get("rate_limits") or []), key=repr) != \
            sorted((_limit_sig(l) for l in want.get("rate_limits") or []), key=repr):
        diffs.append("rate limits differ")
    if want.get("inference_table") and not have.get("inference_table"):
        diffs.append("inference table missing")
    return diffs


def provider_differences(have: dict, want: dict) -> list[str]:
    """What differs between an existing provider service config and the planned one."""
    diffs = []
    if have.get("provider_type") != want.get("provider_type"):
        diffs.append(f"provider {have.get('provider_type')} vs {want.get('provider_type')}")
    missing = missing_models(have, want)
    if missing:
        diffs.append(f"missing models {sorted(missing)}")
    fam = next((k for k in ("openai", "azure_openai", "anthropic") if want.get(k)), None)
    if fam:
        want_key = ((want.get(fam) or {}).get("direct") or {}).get("api_key") or {}
        have_key = ((have.get(fam) or {}).get("direct") or {}).get("api_key") or {}
        if want_key.get("secret_reference") and have_key.get("secret_reference") != want_key["secret_reference"]:
            diffs.append("different secret reference")
        want_url = ((want.get(fam) or {}).get("direct") or {}).get("base_url")
        if want_url and ((have.get(fam) or {}).get("direct") or {}).get("base_url") != want_url:
            diffs.append("different base_url")
    return diffs


def missing_models(have: dict, want: dict) -> set:
    if have.get("allow_all_targets"):
        return set()
    have_models = {t.get("model") for t in have.get("targets") or []}
    return {t.get("model") for t in want.get("targets") or []} - have_models


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


class Applier:
    def __init__(self, w: WorkspaceClient, execute: bool, log_path: str, apply_id: str):
        self.w, self.execute, self.log_path, self.apply_id = w, execute, log_path, apply_id
        self.results: list[dict] = []

    def _write(self, entry: dict) -> None:
        if self.execute:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(_mask(entry), default=str) + "\n")

    def log(self, **entry) -> None:
        entry["time"] = _now_iso()
        entry["execute"] = self.execute
        entry["apply_id"] = self.apply_id
        self.results.append(entry)
        self._write(entry)

    # -- providers ---------------------------------------------------------

    def ensure_provider(self, fqn: str, body: dict) -> str:
        name = f"model-provider-services/{fqn}"
        try:
            existing = self.w.ai_gateway.get_model_provider_service(name=name)
        except NotFound:
            existing = None
        if existing is not None:
            return self._reuse_provider(fqn, existing, body)
        if not self.execute:
            self.log(type="model_provider_service", name=fqn, action="would_create", body=body)
            return "would_create"
        parent, leaf = _leaf(fqn)
        self.log(type="model_provider_service", name=fqn, action="creating")
        try:
            created = self.w.ai_gateway.create_model_provider_service(
                model_provider_service=catalog.ModelProviderService.from_dict(body), parent=parent,
                model_provider_service_id=leaf)
        except AlreadyExists:  # another run created it between our GET and POST
            return self._reuse_provider(fqn, self.w.ai_gateway.get_model_provider_service(name=name), body)
        self.log(type="model_provider_service", name=fqn, action="created", **_stamp(created))
        return "created"

    def _reuse_provider(self, fqn: str, existing, body: dict) -> str:
        have = (existing.as_dict() or {}).get("config") or {}
        if not is_toolkit(existing.comment):
            raise Manual(f"{fqn} already exists and wasn't created by this toolkit; reconcile it by hand or rename "
                         "the target")
        diffs = provider_differences(have, body["config"])
        owner = owner_tag(existing.comment)
        if not diffs:
            self.log(type="model_provider_service", name=fqn, action="exists", owner=owner, **_stamp(existing))
            return "exists"
        only_models = len(diffs) == 1 and diffs[0].startswith("missing models")
        if not only_models:
            raise Manual(f"{fqn} already exists with a different configuration ({'; '.join(diffs)}); "
                         "rename the target or reconcile it by hand")
        added = sorted(missing_models(have, body["config"]))
        new_targets = [t for t in body["config"]["targets"] if t["model"] in added]
        if not self.execute:
            self.log(type="model_provider_service", name=fqn, action="would_update", owner=owner, add_models=added)
            return "would_update"
        merged = list(have.get("targets") or []) + new_targets
        updated = self.w.ai_gateway.update_model_provider_service(
            name=f"model-provider-services/{fqn}",
            model_provider_service=catalog.ModelProviderService.from_dict({"config": {"targets": merged}}),
            update_mask=FieldMask(["config.targets"]), etag=existing.etag)
        self.log(type="model_provider_service", name=fqn, action="updated", owner=owner, add_models=added,
                 **(_stamp(updated) or _stamp(existing)))
        return "updated"

    # -- model services ----------------------------------------------------

    def ensure_model_service(self, fqn: str, body: dict, **extra) -> str:
        name = f"model-services/{fqn}"
        try:
            existing = self.w.ai_gateway.get_model_service(name=name)
        except NotFound:
            existing = None
        if existing is not None:
            return self._reuse_service(fqn, existing, body, extra)
        if not self.execute:
            self.log(type="model_service", name=fqn, action="would_create", body=body, **extra)
            return "would_create"
        parent, leaf = _leaf(fqn)
        self.log(type="model_service", name=fqn, action="creating", **extra)
        try:
            created = self.w.ai_gateway.create_model_service(model_service=catalog.ModelService.from_dict(body),
                                                             parent=parent, model_service_id=leaf)
        except AlreadyExists:  # another run created it between our GET and POST
            return self._reuse_service(fqn, self.w.ai_gateway.get_model_service(name=name), body, extra)
        self.log(type="model_service", name=fqn, action="created", **_stamp(created), **extra)
        return "created"

    def _reuse_service(self, fqn: str, existing, body: dict, extra: dict) -> str:
        if not is_toolkit(existing.comment):
            raise Manual(f"{fqn} already exists and wasn't created by this toolkit; it is left alone "
                         "(manage it by hand or rename the target)")
        diffs = service_differences((existing.as_dict() or {}).get("config") or {}, body["config"])
        if diffs:
            raise Manual(f"{fqn} already exists with a different configuration ({'; '.join(diffs)}); "
                         "rename the target or reconcile it by hand")
        self.log(type="model_service", name=fqn, action="exists", owner=owner_tag(existing.comment),
                 **_stamp(existing), **extra)
        return "exists"

    # -- grants ------------------------------------------------------------

    def _privileges(self, fqn: str) -> set:
        perms = self.w.grants.get(securable_type="model_service", full_name=fqn).as_dict() or {}
        return {(a["principal"], p) for a in perms.get("privilege_assignments", []) for p in a.get("privileges", [])}

    def grant(self, fqn: str, grants: list[dict]) -> None:
        """Add the planned privileges that are missing. Only the privileges added here are recorded (for rollback)."""
        if not grants:
            return
        if not self.execute:
            self.log(type="grant", name=fqn, action="would_grant", grants=grants)
            return
        have = self._privileges(fqn)
        prior = [{"principal": g["principal"], "privileges": sorted(p for pr, p in have if pr == g["principal"])}
                 for g in grants]
        added = [{"principal": g["principal"], "privileges": [p for p in g["privileges"] if (g["principal"], p) not in have]}
                 for g in grants]
        added = [a for a in added if a["privileges"]]
        if not added:
            self.log(type="grant", name=fqn, action="already_granted", grants=grants, prior=prior)
            return
        changes = [catalog.PermissionsChange(principal=a["principal"], add=[catalog.Privilege(p) for p in a["privileges"]])
                   for a in added]
        self.w.grants.update(securable_type="model_service", full_name=fqn, changes=changes)
        self.log(type="grant", name=fqn, action="granted", grants=grants, added=added, prior=prior)

    def verify_grants(self, fqn: str, grants: list[dict]) -> list[str]:
        if not grants:
            return []
        have = self._privileges(fqn)
        issues = [f"grant {p} to {g['principal']} missing" for g in grants for p in g["privileges"]
                  if (g["principal"], p) not in have]
        self.log(type="verify", name=fqn, action="ok" if not issues else "mismatch", issues=issues, scope="grants")
        return issues

    # -- checks ------------------------------------------------------------

    def verify_config(self, fqn: str, body: dict, fallback_enabled: bool) -> list[str]:
        """Read the service back and compare it with what was requested (before any grant is added)."""
        got = (self.w.ai_gateway.get_model_service(name=f"model-services/{fqn}").as_dict() or {}).get("config") or {}
        issues = service_differences(got, body["config"])
        want_fb = bool((body["config"]["routing"].get("fallback") or {}).get("destinations"))
        got_fb = bool(((got.get("routing") or {}).get("fallback") or {}).get("destinations"))
        if got_fb != want_fb:
            issues.append(f"fallback is {'set' if got_fb else 'empty'} but the plan expects "
                          f"{'a fallback' if want_fb else 'none'} (legacy fallback_enabled={fallback_enabled})")
        self.log(type="verify", name=fqn, action="ok" if not issues else "mismatch", issues=issues, scope="config")
        return issues

    def smoke(self, fqn: str, body: dict) -> bool:
        """GET the created service and check its state field if the SDK returns one. No inference requests."""
        d = (self.w.ai_gateway.get_model_service(name=f"model-services/{fqn}").as_dict() or {})
        state = next((v for k, v in d.items() if "state" in k.lower() and isinstance(v, str)), None)
        dests = ((d.get("config") or {}).get("routing") or {}).get("destinations") or []
        want = len(body["config"]["routing"]["destinations"])
        ok = len(dests) == want and (state is None or state.upper() in READY_STATES)
        self.log(type="model_service", name=fqn, action="smoke_ok" if ok else "smoke_failed", state=state,
                 destinations=len(dests),
                 note=None if state else "the installed SDK has no state field; checked GET and destination count only")
        return ok


def running_in_logs(log_path: str, target: str, own_apply_id: str | None = None, now: datetime | None = None,
                    is_active=None) -> list[str]:
    """Apply ids that started on this target and have no run_end marker (sibling logs in the same folder).

    is_active(apply_id) -> bool, when given, decides: the app's store says that run is still RUNNING with its job
    run going. A run killed before its run_end marker then stops blocking its target. Without it, a run blocks
    while its log is younger than STALE_RUN_HOURS (CLI use)."""
    now = now or datetime.now(timezone.utc)
    conflicts = []
    for path in glob.glob(os.path.join(os.path.dirname(os.path.abspath(log_path)), "*.jsonl")):
        entries, _ = read_log(path)
        for e in entries:
            if e.get("type") == "run" and e.get("action") == "run_start" and e.get("target") == target \
                    and e.get("apply_id") != own_apply_id:
                ended = any(x.get("type") == "run" and x.get("action") == "run_end"
                            and x.get("apply_id") == e.get("apply_id") for x in entries)
                if ended:
                    continue
                if is_active is not None:
                    if is_active(e.get("apply_id")):
                        conflicts.append(e.get("apply_id"))
                    continue
                age = (now - datetime.fromisoformat(e["time"])).total_seconds()
                if age < STALE_RUN_HOURS * 3600:
                    conflicts.append(e.get("apply_id"))
    return conflicts


def apply(w: WorkspaceClient, endpoint_names: list[str] | None, target_catalog: str, target_schema: str,
          execute: bool, secrets: Secrets, log_path: str, grants: bool = True, ack_guardrails: bool = False,
          smoke: bool = False, apply_id: str | None = None, is_active=None) -> list[dict]:
    apply_id = apply_id or str(uuid.uuid4())
    try:
        w.schemas.get(f"{target_catalog}.{target_schema}")
    except NotFound:
        raise SystemExit(f"Target schema {target_catalog}.{target_schema} doesn't exist: create it first")
    secrets.validate_policy()  # before any change
    try:  # the listing is lazy: reading its first page is the call that fails when Unity Gateway is off
        next(iter(w.ai_gateway.list_model_services(parent="schemas/system.ai")), None)
    except Exception as error:
        if planner.unity_gateway_unavailable(error):
            raise PolicyError(f"{planner.UNAVAILABLE_LABEL}. {planner.UNAVAILABLE_ACTION}") from None

    global _W
    _W = w
    endpoints = planner.inventory(w)
    rows, all_providers = planner.plan(endpoints, {}, {}, target_catalog, target_schema, traffic_known=False)
    by_name = {e.name: e for e in endpoints}
    selected = [r for r in rows if r.action == "create_model_service"
                and (endpoint_names is None or r.legacy_endpoint in endpoint_names)]
    missing = set(endpoint_names or []) - {r.legacy_endpoint for r in selected}
    a = Applier(w, execute, log_path, apply_id)
    target = f"{target_catalog}.{target_schema}"
    if execute:
        conflicts = running_in_logs(log_path, target, apply_id, is_active=is_active)
        if conflicts:
            raise PolicyError(f"another execute run is RUNNING for {target} (apply {', '.join(conflicts)}); "
                              "wait for it to finish, or pass its apply_id to check it")
        a._write({"type": "run", "action": "run_start", "target": target, "apply_id": apply_id, "time": _now_iso()})
    try:
        for n in sorted(missing):
            reason = "not found" if n not in by_name else f"{by_name[n].kind}: not a create_model_service endpoint"
            a.log(type="endpoint", name=n, action="skipped", reason=reason)

        # Provider services shared by the selected endpoints.
        groups: dict[str, list[dict]] = {}
        for r in selected:
            for d in by_name[r.legacy_endpoint].destinations:
                if d["type"] == "external_model":
                    groups.setdefault(planner._provider_key(d), []).append(d)
        provider_fqn = {p["provider_key"]: p["provider_service"] for p in all_providers}
        if secrets.create_uc:
            ensure_uc_secrets(a, secrets, groups, provider_fqn)
        failed_providers, bodies = set(), {}
        for key, dests in groups.items():  # reads only; a PolicyError here stops the run before any write
            fqn = provider_fqn[key]
            try:
                bodies[key] = (fqn, build_provider(dests, secrets, apply_id))
            except Manual as m:
                failed_providers.add(key)
                a.log(type="model_provider_service", name=fqn, action="manual", reason=str(m))
            except PolicyError:
                raise
            except Exception as e:
                failed_providers.add(key)
                a.log(type="model_provider_service", name=fqn, action="error", reason=str(e)[:500])
        for key, (fqn, body) in bodies.items():
            try:
                a.ensure_provider(fqn, body)
            except Manual as m:
                failed_providers.add(key)
                a.log(type="model_provider_service", name=fqn, action="manual", reason=str(m))
            except Exception as e:
                failed_providers.add(key)
                a.log(type="model_provider_service", name=fqn, action="error", reason=str(e)[:500])

        for r in selected:
            ep = by_name[r.legacy_endpoint]
            if any(planner._provider_key(d) in failed_providers for d in ep.destinations if d["type"] == "external_model"):
                a.log(type="model_service", name=r.target_service, action="skipped", reason="provider service not available")
                continue
            try:
                body = build_model_service(ep, r, provider_fqn, apply_id, ack_guardrails)
                guard = guardrail_items(r) if ack_guardrails else []
                extra = {"guardrails_not_migrated": guard} if guard else {}
                dropped = not_carried_over(ep, r, grants)
                if dropped:
                    extra["not_carried_over"] = dropped
                state = a.ensure_model_service(r.target_service, body, **extra)
                if not execute:
                    if grants and r.grants:
                        a.grant(r.target_service, r.grants)
                    continue
                if state not in ("created", "exists"):
                    continue
                # Config first; grants only after the service reads back as planned.
                if a.verify_config(r.target_service, body, ep.fallback_enabled):
                    continue
                if grants and r.grants:
                    try:
                        a.grant(r.target_service, r.grants)
                    except Exception as ge:
                        a.log(type="model_service", name=r.target_service, action="needs_attention",
                              reason=f"the service is in place but its grants failed ({str(ge)[:300]}): grant "
                                     "EXECUTE/MANAGE by hand or re-run the same selection")
                        continue
                    a.verify_grants(r.target_service, r.grants)
                if smoke and state == "created":
                    a.smoke(r.target_service, body)
            except Manual as m:
                a.log(type="model_service", name=r.target_service, action="manual", reason=str(m))
            except Exception as e:
                a.log(type="model_service", name=r.target_service, action="error", reason=str(e)[:500])
        return a.results
    finally:
        if execute:
            a._write({"type": "run", "action": "run_end", "target": target, "apply_id": apply_id, "time": _now_iso()})


def run_outcome(results: list[dict]) -> tuple[str, dict]:
    """Status and summary of a finished run (job notebooks store both; the app reads them).

    Summary: how many items had each action, plus kept_other_run (kept objects that another apply run still uses),
    kept_preexisting (kept objects that existed before the apply run) and not_carried_over (model services whose legacy governance isn't all carried over).
    Guardrails that were acknowledged are not a problem: the item records guardrails_not_migrated and the run
    still SUCCEEDED."""
    summary: dict = {}
    for r in results:
        act = r.get("action") or "unknown"
        summary[act] = summary.get(act, 0) + 1
    summary["kept_other_run"] = sum(1 for r in results if r.get("action") == "kept" and r.get("other_run"))
    # Objects that existed before the apply run (reused, no apply mark): rollback rightly keeps them.
    summary["kept_preexisting"] = sum(1 for r in results if r.get("action") == "kept" and r.get("preexisting"))
    # Services whose legacy governance isn't fully carried over (their items list not_carried_over). Not a problem
    # status: the run did what it could, and the result says what a person still has to redo.
    summary["not_carried_over"] = len({r.get("name") for r in results if r.get("not_carried_over")
                                       and r.get("action") in ("created", "exists", "would_create")})
    status = "NEEDS_ATTENTION" if any(summary.get(a) for a in PROBLEM_ACTIONS) else "SUCCEEDED"
    return status, summary


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


def read_log(path: str) -> tuple[list[dict], int]:
    entries, bad = [], 0
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except ValueError:
                bad += 1
    return entries, bad


def protection_from_runs(runs: list[dict], apply_id: str) -> tuple[dict, set]:
    """What a rollback of apply_id must keep, from every other run.

    runs: [{"apply_id": ..., "rolled_back": bool, "entries": [...]}]. Returns (protect, released):
    protect maps (type, name) to a reason for objects that another run which hasn't been rolled back still
    uses (it created, reused or updated them); released holds the apply ids whose rollback is finished."""
    protect, released = {}, set()
    for run in runs:
        rid = run.get("apply_id")
        if not rid or rid == apply_id:
            continue
        if run.get("rolled_back"):
            released.add(rid)
            continue
        for e in run.get("entries") or []:
            if e.get("execute") and e.get("action") in USE_ACTIONS and e.get("type") in ROLLBACK_TYPES:
                protect.setdefault((e["type"], e["name"]), f"used by apply {rid}, which hasn't been rolled back")
    return protect, released


def rollback(w: WorkspaceClient, log_path: str, execute: bool, protect=None, apply_id: str | None = None,
             released=None, force: bool = False, audit_path: str | None = None) -> list[dict]:
    """Delete only what this run's log says it created or reused, and only where the object still carries
    this run's apply mark (or is a reused object whose owning run was rolled back). Newest first.

    Each result is appended to audit_path as it happens (when executing), so a cancelled rollback still
    leaves a record. When audit_path is the source log, a rollback_complete marker is written at the end."""
    entries, bad = read_log(log_path)
    if apply_id is None:
        ids = Counter(e.get("apply_id") for e in entries if e.get("execute") and e.get("apply_id"))
        apply_id = ids.most_common(1)[0][0] if ids else None
    protect = dict.fromkeys(protect, "used by another apply") if isinstance(protect, (set, frozenset)) \
        else dict(protect or {})
    released = set(released or ())
    out: list[dict] = []

    def emit(r: dict) -> None:
        out.append(r)
        if audit_path and execute:
            with open(audit_path, "a") as f:
                f.write(json.dumps(dict(_mask(r), rollback_of=apply_id, time=_now_iso()), default=str) + "\n")

    if bad:
        emit({"type": "log", "name": log_path, "action": "skipped_lines", "count": bad})
    created_here, done, targets, seen, stamp, used_by = set(), set(), [], set(), {}, {}
    for e in entries:
        if e.get("rollback_of") or e.get("type") not in ROLLBACK_TYPES:  # audit lines of earlier rollbacks skip
            continue
        key, act = (e["type"], e["name"]), e.get("action")
        if act in CREATED_ACTIONS:
            created_here.add(key)
        if act in ("created", "created_secret"):
            done.add(key)
        if typ_used := e.get("used_by"):
            used_by[key] = list(typ_used)
        if act in OWNED_ACTIONS:
            if key not in seen:
                seen.add(key)
                targets.append(key)
            if e.get("etag") or e.get("update_time"):
                stamp[key] = e
    grant_entries = [e for e in entries if not e.get("rollback_of") and e.get("type") == "grant"
                     and e.get("action") == "granted" and e.get("added")]
    deleted = set()  # deleted, or would be deleted in a dry run
    for key in reversed(targets):
        typ, name = key
        try:
            if typ == "model_service":
                obj = w.ai_gateway.get_model_service(name=f"model-services/{name}")
            elif typ == "uc_secret":
                obj = w.secrets_uc.get_secret(name)
            else:
                obj = w.ai_gateway.get_model_provider_service(name=f"model-provider-services/{name}")
            d = obj.as_dict() or {}
            d.pop("value", None)
            d.pop("effective_value", None)
            comment = d.get("comment") or ""
            if key in protect:
                emit({"type": typ, "name": name, "action": "kept", "reason": protect[key], "other_run": True})
                continue
            if not is_toolkit(comment):
                emit({"type": typ, "name": name, "action": "kept", "preexisting": True,
                      "reason": "not created by this tool (comment doesn't match)"})
                continue
            tag, created = owner_tag(comment), key in created_here
            owned = created if tag is None else (tag == apply_id or (not created and tag in released))
            if not owned:
                reason = (f"owned by apply {tag}, which hasn't been rolled back" if tag
                          else "no apply mark and not created by this run")
                # No mark and not created here: it existed before this run (reused), so keeping it is expected.
                emit({"type": typ, "name": name, "action": "kept", "reason": reason, "other_run": bool(tag),
                      **({} if tag else {"preexisting": True})})
                continue
            if typ == "model_provider_service":
                try:
                    # A model service this rollback deletes (or, in a dry run, would delete) no longer uses the
                    # provider, so the dry run previews what execute does.
                    refs = [r for r in services_referencing(w, name) if ("model_service", r) not in deleted]
                except ReferenceCheckError as rce:
                    emit({"type": typ, "name": name, "action": "kept",
                          "reason": f"couldn't check every catalog and schema for model services that use it ({rce}); "
                                    "delete it by hand once nothing uses it"})
                    continue
                if refs:
                    # Shared when every service that still uses it belongs to another run that hasn't been rolled back.
                    shared = all(("model_service", r) in protect for r in refs)
                    emit({"type": typ, "name": name, "action": "kept", "other_run": shared,
                          "reason": (f"still used by model service(s) of another apply run: {', '.join(refs)}" if shared
                                     else f"still referenced by model service(s): {', '.join(refs)}")})
                    continue
            if typ == "uc_secret":
                # Providers come before their secrets in reverse log order: keep the secret while a provider that
                # used it is still there (this rollback kept it, or it isn't this run's).
                still = [p for p in used_by.get(key, []) if ("model_provider_service", p) not in deleted]
                if still:
                    emit({"type": typ, "name": name, "action": "kept",
                          "reason": f"still used by provider service(s): {', '.join(still)}"})
                    continue
            st = stamp.get(key)
            if st is None:
                emit({"type": typ, "name": name, "action": "note",
                      "reason": "no etag recorded at creation; changes since apply were not checked"})
            elif not force:
                changed = (d.get("etag") != st.get("etag")) if st.get("etag") else \
                    (d.get("update_time") != st.get("update_time"))
                if changed:
                    emit({"type": typ, "name": name, "action": "kept",
                          "reason": f"changed since apply (update_time {d.get('update_time')}); roll back from "
                                    "the command line with --force (USER_GUIDE.md, Apply from the command line) to delete anyway"})
                    continue
            if key not in done and key in created_here:
                emit({"type": typ, "name": name, "action": "note",
                      "reason": "create was interrupted; the object exists and carries this run's mark"})
            if not execute:
                deleted.add(key)
                emit({"type": typ, "name": name, "action": "would_delete"})
                continue
            kw = {} if force else {"etag": d.get("etag")}  # conditional delete when not forcing
            if typ == "model_service":
                w.ai_gateway.delete_model_service(name=f"model-services/{name}", **kw)
            elif typ == "uc_secret":
                w.secrets_uc.delete_secret(name)
            else:
                w.ai_gateway.delete_model_provider_service(name=f"model-provider-services/{name}", **kw)
            deleted.add(key)
            emit({"type": typ, "name": name, "action": "deleted",
                  **({"note": "checked the model services in every catalog and schema this identity can see"}
                     if typ == "model_provider_service" else {})})
        except NotFound:
            deleted.add(key)  # its grants went with it
            emit({"type": typ, "name": name, "action": "already_gone"})
        except Exception as ex:
            emit({"type": typ, "name": name, "action": "error", "reason": str(ex)[:300]})

    # Grants are never revoked. A deleted service takes its grants with it. A service the rollback keeps (another
    # run uses it, it changed since apply, it existed before, or it couldn't be deleted) keeps every grant, because
    # callers may depend on them now: the privileges this run added are listed so an owner can revoke them by hand.
    for e in grant_entries:
        key = ("model_service", e["name"])
        if key in deleted:
            continue
        emit({"type": "grant", "name": e["name"], "action": "kept", "grants": e["added"],
              "reason": "the service is kept, so the privileges this run added stay; revoke them by hand if they are "
                        "no longer needed"})

    if execute and audit_path:
        with open(audit_path, "a") as f:
            f.write(json.dumps({"type": "run", "action": "rollback_complete", "rollback_of": apply_id,
                                "time": _now_iso()}) + "\n")
    return out


class ReferenceCheckError(Exception):
    """services_referencing couldn't check everywhere a service might use the provider."""


SKIP_CATALOGS = ("system", "__databricks_internal")  # Databricks-managed: their services can't use a customer provider


def _visible_schemas(w: WorkspaceClient):
    for cat in w.catalogs.list():
        if not cat.name or cat.name in SKIP_CATALOGS:
            continue
        for sch in w.schemas.list(catalog_name=cat.name):
            if sch.name and sch.name != "information_schema":
                yield f"{cat.name}.{sch.name}"


def services_referencing(w: WorkspaceClient, provider_fqn: str) -> list[str]:
    """Model services in every catalog and schema this identity can see whose destinations or fallback use the
    provider, not only the provider's own schema. Raises ReferenceCheckError when a catalog, schema or service
    can't be read, so the caller keeps the provider (fail closed). Services in schemas this identity can't see
    aren't checked; the rollback result says so."""
    target = f"model-provider-services/{provider_fqn}"
    refs = []
    try:
        for schema in _visible_schemas(w):
            listing = w.ai_gateway.list_model_services(parent=f"schemas/{schema}",
                                                       view=catalog.ListModelServicesRequestView.FULL)
            for svc in listing:
                d = svc.as_dict() or {}
                name = d.get("name") or ""
                if not name.startswith("model-services/"):
                    continue
                if "config" not in d:  # the listing may omit the config
                    d = w.ai_gateway.get_model_service(name=name).as_dict() or {}
                routing = (d.get("config") or {}).get("routing") or {}
                dests = (routing.get("destinations") or []) + ((routing.get("fallback") or {}).get("destinations") or [])
                if any((x.get("external_model_config") or {}).get("model_provider_service") == target for x in dests):
                    refs.append(name[len("model-services/"):])
    except Exception as e:
        raise ReferenceCheckError(str(e)[:300]) from e
    return refs


def cli_runs(log_path: str) -> list[dict]:
    """Runs described by the logs in the same folder (for CLI protection, the same role as the store has in the app)."""
    runs = []
    for path in sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(log_path)), "*.jsonl"))):
        entries, _ = read_log(path)
        ids = [e.get("apply_id") for e in entries if e.get("apply_id")]
        if not ids:
            continue
        done = any(e.get("type") == "run" and e.get("action") == "rollback_complete" for e in entries)
        runs.append({"apply_id": ids[0], "rolled_back": done, "entries": entries})
    return runs


# ---------------------------------------------------------------------------
# Verify and cut over (runbook cells 12-14 and 30-38; README steps 4-6)
# ---------------------------------------------------------------------------

OPERATIONS = ("apply", "test_call", "pause_legacy", "enable_tracking", "resume_legacy", "guardrail_check")
WRITE_LEGACY_OPERATIONS = ("pause_legacy", "enable_tracking", "resume_legacy")  # one at a time per workspace
API_TYPES = ("mlflow/v1/chat/completions", "openai/v1/responses", "mlflow/v1/embeddings")
DEFAULT_API_TYPE = API_TYPES[0]
# "auto" picks each service's own API type (chat, then responses, then embeddings), so one run can test a mix.
API_TYPE_AUTO = "auto"
TEST_API_TYPES = (API_TYPE_AUTO, *API_TYPES)
DEFAULT_PROMPT = "Reply with: ok"
MAX_PROMPT_CHARS = 200
MAX_TEST_SERVICES = 10  # toolkit cap per test run (each service gets one billable request)
EXCERPT_CHARS = 200
TEST_TIMEOUT_SECONDS = 120
SERVICE_NAME_RE = re.compile(r"[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")
ENDPOINT_NAME_RE = re.compile(r"[A-Za-z0-9_\-]+")
DRY_RUN_TTL_HOURS = 24  # an execute must follow a successful dry run of the same settings started this recently
DRY_RUN_GATED = ("apply", "test_call", "pause_legacy", "enable_tracking", "guardrail_check")  # resume and apply rollback have no dry run
PAUSE_TRAFFIC_HOURS = 24  # pause refuses an endpoint with legacy requests this recent, unless force is set
# AI Gateway settings that PUT /ai-gateway re-sends: the companion script's list plus usage tracking.
# An endpoint with any other setting set is refused, because the PUT would drop it.
GATEWAY_KEYS = ("guardrails", "inference_table_config", "rate_limits", "fallback_config", "usage_tracking_config")
ZERO_LIMIT = {"key": "endpoint", "calls": 0, "renewal_period": "minute"}
EMBEDDING_RE = re.compile(r"embed|\bbge\b|\bgte\b", re.I)
SEARCH_RE = re.compile(r"vector[ _-]?search|ai[ _-]?search", re.I)


def _parse_time(ts) -> datetime | None:
    """A UTC time from epoch seconds or an ISO string (no zone means UTC); None if it can't be read."""
    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
        return datetime.fromtimestamp(ts, timezone.utc)
    try:
        t = datetime.fromisoformat(str(ts).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def dry_run_expired(started_at, now: datetime | None = None) -> bool:
    """True when a dry run started more than DRY_RUN_TTL_HOURS ago (or its start time can't be read)."""
    t = _parse_time(started_at)
    if t is None:
        return True
    return ((now or datetime.now(timezone.utc)) - t).total_seconds() > DRY_RUN_TTL_HOURS * 3600


def dry_run_gate_error(dry: dict | None, operation: str, fingerprint: str | None, scan_run_id: str = "",
                       requested_by: str = "", now: datetime | None = None, used_by: str | None = None) -> str | None:
    """Why an execute can't run: it must follow a successful, recent dry run of the same operation and settings.

    dry is the dry run's row in ug_migration_applies (mode, operation, status, fingerprint, scan_run_id,
    requested_by, started_at as epoch seconds or a UTC string). The job checks this itself, so starting the job directly can't skip the dry run.
    requested_by must match when the dry run recorded one; it is a consistency check, not an access control.
    used_by is the apply_id of an execute that already followed this dry run: each dry run is good for one execute."""
    if dry is None:
        return "execute needs dry_run_id: the apply_id of a successful dry run of the same settings"
    if dry.get("mode") != "dry_run" or (dry.get("operation") or "apply") != operation:
        return f"dry_run_id must be a dry run of {operation}"
    if dry.get("status") != "SUCCEEDED":
        return "that dry run didn't succeed; run a dry run with these settings again"
    if not dry.get("fingerprint") or dry.get("fingerprint") != fingerprint:
        return "the endpoints or options changed since that dry run; run a dry run with these settings"
    if operation == "apply" and (dry.get("scan_run_id") or "") != (scan_run_id or ""):
        return "that dry run used a different scan; run a dry run with this scan"
    if (dry.get("requested_by") or "") and (dry.get("requested_by") or "") != (requested_by or ""):
        return "that dry run was started by someone else; run your own dry run first"
    if dry_run_expired(dry.get("started_at"), now):
        return f"that dry run is more than {DRY_RUN_TTL_HOURS} hours old; run a dry run again"
    if used_by:
        return f"that dry run was already used by execute {used_by}; run a new dry run"
    return None


UNATTRIBUTED_TRAFFIC = "(unmatched served entity)"  # ug_migration_store.UNATTRIBUTED


def pause_traffic_refusal(name: str, recent_requests: dict | None, force: bool = False) -> str | None:
    """Why pause must not run for an endpoint that still has callers (server-side gate; the app asks first).

    recent_requests maps endpoint name to legacy requests (v1 and v2) in the last PAUSE_TRAFFIC_HOURS. None means
    traffic couldn't be checked, which refuses too (fail closed). force pauses anyway: the caller has confirmed that
    the remaining callers will get errors. System tables lag by up to a few hours, so no traffic is not proof."""
    if force:
        return None
    if recent_requests is None:
        return (f"couldn't check the last {PAUSE_TRAFFIC_HOURS} hours of traffic; pause with force set to confirm "
                "that any remaining callers will get errors")
    n = int(recent_requests.get(name) or 0)
    if n > 0:
        return (f"{n} legacy request(s) in the last {PAUSE_TRAFFIC_HOURS} hours: those callers would get errors. Move "
                "them first, or pause with force set to confirm")
    unmatched = int(recent_requests.get(UNATTRIBUTED_TRAFFIC) or 0)
    if unmatched > 0:
        # Fail closed: these requests could be this endpoint's.
        return (f"{unmatched} legacy request(s) in the last {PAUSE_TRAFFIC_HOURS} hours couldn't be matched to an "
                "endpoint (their served entity isn't in system.serving.served_entities), so they may be this "
                "endpoint's callers. Check them, or pause with force set to confirm")
    return None


def resolve_api_type(value) -> str:
    v = (value or "").strip() or DEFAULT_API_TYPE
    if v not in TEST_API_TYPES:
        raise ValueError(f"api_type must be one of {', '.join(TEST_API_TYPES)}, not {v!r}")
    return v


def pick_api_type(requested: str, supported: list[str]) -> str | None:
    """The API type to test a service on: the requested one, or with "auto" the first of API_TYPES it supports."""
    if requested != API_TYPE_AUTO:
        return requested if requested in supported else None
    return next((t for t in API_TYPES if t in supported), None)


def resolve_prompt(value) -> str:
    v = (value or "").strip() or DEFAULT_PROMPT
    if len(v) > MAX_PROMPT_CHARS:
        raise ValueError(f"prompt is {len(v)} characters; the limit is {MAX_PROMPT_CHARS}")
    if any(ord(c) < 32 or ord(c) == 127 for c in v):
        raise ValueError("prompt can't contain control characters (line breaks or tabs)")
    return v


def _split_unique(value) -> list[str]:
    out = []
    for s in (value or "").split(","):
        s = s.strip()
        if s and s not in out:
            out.append(s)
    return out


def parse_endpoints(value) -> list[str]:
    names = _split_unique(value)
    bad = [n for n in names if not ENDPOINT_NAME_RE.fullmatch(n)]
    if bad:
        raise ValueError(f"bad endpoint name(s) {bad}")
    return names


def parse_services(value) -> list[str]:
    names = _split_unique(value)
    if not names:
        raise ValueError("choose at least one Model Service in services (catalog.schema.name)")
    bad = [n for n in names if not SERVICE_NAME_RE.fullmatch(n)]
    if bad:
        raise ValueError(f"services must be three-part catalog.schema.name names, not {bad}")
    if len(names) > MAX_TEST_SERVICES:
        raise ValueError(f"at most {MAX_TEST_SERVICES} services per test run, got {len(names)}")
    return names


def _api_refusal(e: Exception) -> bool:
    """True for an error the API returned on purpose (a 4xx-style refusal), not a server or network failure."""
    from databricks.sdk.errors import DeadlineExceeded, InternalError, TemporarilyUnavailable
    return isinstance(e, DatabricksError) and not isinstance(
        e, (InternalError, TemporarilyUnavailable, DeadlineExceeded))


# -- Model Service test calls (runbook cells 11-14) -------------------------

def build_test_request(api_type: str, service: str, prompt: str) -> dict:
    """The request body for one test call (the same small prompt for every API type)."""
    if api_type == "mlflow/v1/chat/completions":
        return {"model": service, "messages": [{"role": "user", "content": prompt}]}
    return {"model": service, "input": prompt}  # openai/v1/responses and mlflow/v1/embeddings


def reply_excerpt(api_type: str, body) -> str | None:
    """A short excerpt of the model's reply (or the embedding size); None when the body has no reply to show."""
    try:
        if api_type == "mlflow/v1/chat/completions":
            text = body["choices"][0]["message"].get("content")
        elif api_type == "openai/v1/responses":
            text = body.get("output_text") or next(
                (part["text"] for item in body.get("output") or [] for part in item.get("content") or []
                 if part.get("text")), None)
        else:
            text = f"embedding with {len(body['data'][0]['embedding'])} dimensions"
    except (KeyError, IndexError, TypeError, AttributeError):
        return None
    return str(text)[:EXCERPT_CHARS] if text else None


def run_test_calls(w: WorkspaceClient, services: list[str], api_type: str, prompt: str, execute: bool,
                   log_path: str, apply_id: str | None = None, post=None) -> list[dict]:
    """Send one small request to each Model Service on api_type (runbook cell 12).

    Dry run: validates each service (read-only GET) and logs what it would send; no request is sent. Execute:
    sends one billable request per service and records the HTTP status, request id, latency and a reply excerpt.
    The request uses the workspace's own auth headers, which are never recorded."""
    a = Applier(w, execute, log_path, apply_id)
    if post is None:
        import requests
        post = requests.post
    url_base = w.config.host.rstrip("/")
    requested = api_type
    for svc in services:
        try:
            ms = w.ai_gateway.get_model_service(name=f"model-services/{svc}")
        except NotFound:
            a.log(type="model_service", name=svc, action="missing",
                  reason="not created yet, or not visible to this identity: apply it first, or check the name")
            continue
        except Exception as e:
            a.log(type="model_service", name=svc, action="test_failed", reason=f"could not read: {str(e)[:300]}")
            continue
        supported = list(ms.supported_api_types or [])
        api_type = pick_api_type(requested, supported)
        if api_type is None:
            a.log(type="model_service", name=svc, action="refused", api_type=requested,
                  reason=(f"does not support {requested}" if requested != API_TYPE_AUTO
                          else f"supports none of the API types the toolkit can test ({', '.join(API_TYPES)})"),
                  supported_api_types=supported)
            continue
        path_for = f"/ai-gateway/{api_type}"
        if not execute:
            a.log(type="model_service", name=svc, action="would_test", api_type=api_type, path=path_for)
            continue
        started = time.monotonic()
        try:
            resp = post(url_base + path_for,
                        headers={**w.config.authenticate(), "Content-Type": "application/json"},
                        json=build_test_request(api_type, svc, prompt), timeout=TEST_TIMEOUT_SECONDS)
        except Exception as e:
            a.log(type="model_service", name=svc, action="test_failed", api_type=api_type, path=path_for,
                  reason=f"no response: {str(e)[:300]}")
            continue
        latency_ms = round((time.monotonic() - started) * 1000)
        headers = getattr(resp, "headers", None) or {}
        request_id = headers.get("x-request-id") or headers.get("x-databricks-request-id")
        base = dict(type="model_service", name=svc, api_type=api_type, path=path_for,
                    http_status=resp.status_code, request_id=request_id, latency_ms=latency_ms)
        if resp.status_code >= 400:
            a.log(action="test_failed", reason=f"HTTP {resp.status_code}: {str(resp.text)[:EXCERPT_CHARS]}", **base)
            continue
        try:
            body = resp.json()
        except ValueError:
            body = None
        extra = {} if request_id else {"note": "no request id header; look the call up by time instead"}
        a.log(action="test_ok", reply_excerpt=reply_excerpt(api_type, body) if body is not None else None,
              **base, **extra)
    return a.results


# -- Guardrail check: does the new service still block what the legacy endpoint's guardrails block? ----------

MAX_GUARDRAIL_PAIRS = 10
# Harmless probes. The PII one carries a fake address from the documentation range of example.com.
FAKE_EMAIL = "jane.doe@example.com"
GUARDRAIL_PROBES = {
    "control": "Reply with the word ok.",
    "pii": f"Reply with the word ok. My contact email is {FAKE_EMAIL}.",
}
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def parse_guardrail_pairs(value) -> list[tuple[str, str]]:
    """"legacy=catalog.schema.service" entries (comma-separated), sorted and de-duplicated."""
    pairs = set()
    for part in str(value or "").split(","):
        part = part.strip()
        if not part:
            continue
        legacy, _, service = part.partition("=")
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", legacy) or not re.fullmatch(r"[A-Za-z0-9_\-]+(\.[A-Za-z0-9_\-]+){2}", service):
            raise ValueError(f"guardrail pairs look like legacy_endpoint=catalog.schema.service, not {part!r}")
        pairs.add((legacy, service))
    if not pairs:
        raise ValueError("guardrail_check needs at least one legacy_endpoint=catalog.schema.service pair")
    if len(pairs) > MAX_GUARDRAIL_PAIRS:
        raise ValueError(f"at most {MAX_GUARDRAIL_PAIRS} pairs per guardrail check, got {len(pairs)}")
    return sorted(pairs)


def _masked_excerpt(text) -> str | None:
    """A short excerpt with any email address (the probe's or another) masked."""
    if text is None:
        return None
    return _EMAIL_RE.sub("[email]", str(text))[:EXCERPT_CHARS]


def _guardrail_blocked(status: int, text: str) -> bool:
    """A refusal by an AI Gateway guardrail: a 4xx whose body names a guardrail."""
    return 400 <= status < 500 and "guardrail" in (text or "").lower()


def _probe_call(post, url: str, headers: dict, body: dict) -> dict:
    try:
        resp = post(url, headers=headers, json=body, timeout=TEST_TIMEOUT_SECONDS)
    except Exception as e:
        return {"status": None, "blocked": False, "excerpt": _masked_excerpt(f"no response: {str(e)[:150]}")}
    text = str(getattr(resp, "text", "") or "")
    excerpt = text
    if resp.status_code < 400:
        try:
            excerpt = resp.json()["choices"][0]["message"].get("content") or ""
        except Exception:
            pass
    return {"status": resp.status_code, "blocked": _guardrail_blocked(resp.status_code, text),
            "excerpt": _masked_excerpt(excerpt)}


def run_guardrail_checks(w: WorkspaceClient, pairs: list[tuple[str, str]], execute: bool, log_path: str,
                         apply_id: str | None = None, post=None) -> list[dict]:
    """For each (legacy endpoint, new service) pair, send the same harmless probes to both and compare.

    Dry run: reads both (GETs only) and says which probes it would send. Execute: per probe, one request to the
    legacy endpoint and one to the service (billable, tiny), recording status, whether a guardrail blocked it, and a
    masked excerpt (never the full reply). Verdict per pair: protection_lost (the legacy endpoint blocks the PII probe,
    the service doesn't), still_protected (both block it), not_applicable (the legacy endpoint has no PII guardrail or
    didn't block the probe). Other guardrail kinds (safety, keywords, topics) are listed, not probed."""
    a = Applier(w, execute, log_path, apply_id)
    if post is None:
        import requests
        post = requests.post
    host = w.config.host.rstrip("/")
    for legacy, service in pairs:
        base = dict(type="guardrail_check", name=service, legacy_endpoint=legacy, service=service)
        try:
            ep = _read_endpoint(w, legacy)
        except NotFound:
            a.log(action="missing", reason=f"legacy endpoint {legacy} not found", **base)
            continue
        except Exception as e:
            a.log(action="check_failed", reason=f"could not read {legacy}: {str(e)[:300]}", **base)
            continue
        gw = ep.get("ai_gateway") or {}
        guardrails = gw.get("guardrails") or {}
        settings = planner.guardrail_settings(guardrails)
        if _zero_endpoint_limit(gw):
            a.log(action="refused", reason=f"{legacy} is paused (rate limit 0), so it can't be compared: resume it "
                                           "first", guardrails=settings, **base)
            continue
        try:
            ms = w.ai_gateway.get_model_service(name=f"model-services/{service}")
        except NotFound:
            a.log(action="missing", reason="the service isn't created yet, or isn't visible to this identity",
                  guardrails=settings, **base)
            continue
        except Exception as e:
            a.log(action="check_failed", reason=f"could not read the service: {str(e)[:300]}", **base)
            continue
        if DEFAULT_API_TYPE not in list(ms.supported_api_types or []):
            a.log(action="refused", reason=f"the service doesn't support {DEFAULT_API_TYPE}", guardrails=settings,
                  **base)
            continue
        pii_guarded = any(s.startswith("input PII") for s in settings)
        probes = ["control"] + (["pii"] if pii_guarded else [])
        if not settings:
            a.log(action="not_applicable", reason=f"{legacy} has no AI Gateway guardrails", guardrails=[], **base)
            continue
        unprobed = [s for s in settings if not s.startswith("input PII")]
        note = (f"Not probed: {', '.join(unprobed)} (check those by hand)" if unprobed else None)
        if not execute:
            a.log(action="would_check", probes=probes, guardrails=settings, requests=2 * len(probes),
                  **({"note": note} if note else {}), **base)
            continue
        headers = {**w.config.authenticate(), "Content-Type": "application/json"}
        results = []
        for probe in probes:
            msg = {"messages": [{"role": "user", "content": GUARDRAIL_PROBES[probe]}], "max_tokens": 10}
            leg = _probe_call(post, f"{host}/serving-endpoints/{legacy}/invocations", headers, msg)
            svc = _probe_call(post, f"{host}/ai-gateway/{DEFAULT_API_TYPE}", headers, {**msg, "model": service})
            results.append({"probe": probe, "legacy_status": leg["status"], "legacy_blocked": leg["blocked"],
                            "legacy_excerpt": leg["excerpt"], "service_status": svc["status"],
                            "service_blocked": svc["blocked"], "service_excerpt": svc["excerpt"]})
        control = results[0]
        pii = next((r for r in results if r["probe"] == "pii"), None)
        if control["legacy_status"] != 200 or control["service_status"] != 200:
            action, why = "check_failed", ("the control request (no PII) didn't succeed on both, so the comparison "
                                           "isn't reliable")
        elif pii is None:
            action, why = "not_applicable", "no input PII guardrail to probe"
        elif pii["legacy_blocked"] and not pii["service_blocked"]:
            action, why = "protection_lost", (f"{legacy} blocks a request with PII; {service} lets it through to the "
                                              "model")
        elif pii["legacy_blocked"] and pii["service_blocked"]:
            action, why = "still_protected", f"both block a request with PII"
        else:
            action, why = "not_applicable", f"{legacy} didn't block the PII probe either"
        a.log(action=action, reason=why, probes=results, guardrails=settings, **({"note": note} if note else {}),
              **base)
    return a.results


# -- Legacy v1 endpoints: rate-limit pause, resume and usage tracking (README steps 5-6; companion script) -----

def is_custom_kind(kind: str) -> bool:
    return kind in ("custom_model", "agent", "unknown") or "custom_model" in kind


def endpoint_kind(ep: dict) -> str:
    return planner._classify(ep)[0]


def gateway_settings(gw: dict | None) -> dict:
    """The AI Gateway settings a PUT re-sends: the GATEWAY_KEYS that are set (deep copy)."""
    gw = gw or {}
    return {k: copy.deepcopy(gw[k]) for k in GATEWAY_KEYS if gw.get(k) not in (None, [], {}, "")}


def unknown_gateway_keys(gw: dict | None) -> list[str]:
    """Set AI Gateway settings that this tool doesn't re-send (a PUT would drop them)."""
    return sorted(k for k, v in (gw or {}).items() if k not in GATEWAY_KEYS and v not in (None, False, [], {}, ""))


def _settings_view(settings: dict) -> dict:
    view = {}
    for k in GATEWAY_KEYS:
        v = settings.get(k)
        if v in (None, [], {}, "") or (isinstance(v, dict) and set(v) <= {"enabled"} and not v.get("enabled")):
            continue  # an off or empty setting reads the same as an absent one
        view[k] = sorted(json.dumps(x, sort_keys=True) for x in v) if k == "rate_limits" else v
    return view


def same_settings(a: dict, b: dict) -> bool:
    return _settings_view(a) == _settings_view(b)


def _zero_endpoint_limit(gw: dict | None) -> bool:
    return any(l.get("key") == "endpoint" and l.get("calls") == 0 and not l.get("principal")
               for l in (gw or {}).get("rate_limits") or [])


def pause_refusal(ep: dict, kind: str) -> str | None:
    """Why an endpoint must not be rate-limited to 0 (custom models, AI Search and embedding endpoints)."""
    if is_custom_kind(kind):
        return f"{kind} endpoint: custom models and agents are out of scope for the Unity Gateway migration"
    text = [ep.get("name") or "", ep.get("task") or ""]
    for t in ep.get("tags") or []:
        text.append(f"{t.get('key') or ''} {t.get('value') or ''}")
    for ent in (ep.get("config") or {}).get("served_entities") or []:
        ext = ent.get("external_model") or {}
        text += [ent.get("entity_name") or "", ext.get("task") or "", ext.get("name") or ""]
        fm = ent.get("foundation_model")
        if isinstance(fm, dict):
            text.append(fm.get("name") or "")
    if any(SEARCH_RE.search(t) for t in text):
        return "AI Search or Vector Search endpoint: the runbook says not to rate-limit these"
    if any(EMBEDDING_RE.search(t) for t in text):
        return "embedding endpoint: the runbook says not to rate-limit embedding endpoints"
    return None


# The API refuses an empty AI Gateway body ("AI Gateway configuration must be provided"), so "no settings" is sent
# as usage tracking off, which reads the same (same_settings) and turns nothing on.
NO_GATEWAY_SETTINGS = {"usage_tracking_config": {"enabled": False}}


def _put_gateway(w: WorkspaceClient, name: str, body: dict) -> None:
    # PUT replaces the whole AI Gateway config: the caller sends every setting it wants kept.
    w.api_client.do("PUT", f"/api/2.0/serving-endpoints/{name}/ai-gateway",
                    body=body if gateway_settings(body) else copy.deepcopy(NO_GATEWAY_SETTINGS))


def _read_endpoint(w: WorkspaceClient, name: str) -> dict:
    return planner._get(w, f"/api/2.0/serving-endpoints/{name}")


def _refusal_or_error(e: Exception, what: str) -> tuple[str, str]:
    if _api_refusal(e):
        return "refused", f"the API refused the change: {str(e)[:300]}"
    return "error", f"could not {what}: {str(e)[:300]}"


def pause_legacy(w: WorkspaceClient, names: list[str], execute: bool, log_path: str,
                 apply_id: str | None = None, recent_requests: dict | None = None, force: bool = False) -> list[dict]:
    """Set each legacy endpoint's endpoint-wide rate limit to 0 calls a minute (README step 5).

    Every other AI Gateway setting is re-sent unchanged. The previous and written configs go in the durable log
    before the write (action pausing), so resume_legacy can restore the previous config exactly even when the read-back
    fails or the run is killed. An endpoint that can't be read first is refused (fail closed). Custom model and
    embedding endpoints are refused, and so is any endpoint the API refuses (for example databricks-* system
    endpoints). An endpoint with recent legacy traffic is refused unless force is set (pause_traffic_refusal)."""
    a = Applier(w, execute, log_path, apply_id)
    typ = "serving_endpoint"
    for name in names:
        refusal = pause_traffic_refusal(name, recent_requests, force)
        if refusal:
            a.log(type=typ, name=name, action="refused", reason=refusal,
                  recent_requests=None if recent_requests is None else int(recent_requests.get(name) or 0))
            continue
        try:
            ep = _read_endpoint(w, name)
        except NotFound:
            a.log(type=typ, name=name, action="refused", reason="endpoint not found")
            continue
        except Exception as e:
            a.log(type=typ, name=name, action="error", reason=f"could not read the endpoint: {str(e)[:300]}")
            continue
        kind = endpoint_kind(ep)
        reason = pause_refusal(ep, kind)
        if reason:
            a.log(type=typ, name=name, action="refused", kind=kind, reason=reason)
            continue
        gw = ep.get("ai_gateway") or {}
        unknown = unknown_gateway_keys(gw)
        if unknown:
            a.log(type=typ, name=name, action="refused", kind=kind,
                  reason=f"ai_gateway has settings this tool doesn't re-send ({', '.join(unknown)}); pause it by hand")
            continue
        previous = gateway_settings(gw)
        if _zero_endpoint_limit(gw):
            a.log(type=typ, name=name, action="already_paused", kind=kind, previous_ai_gateway=previous)
            continue
        paused = dict(previous)
        paused["rate_limits"] = [l for l in gw.get("rate_limits") or []
                                 if l.get("key") != "endpoint"] + [dict(ZERO_LIMIT)]
        facts = dict(kind=kind, previous_ai_gateway=previous, paused_ai_gateway=paused)
        if not execute:
            a.log(type=typ, name=name, action="would_pause", **facts)
            continue
        # In the durable log before the write, so a resume can restore this endpoint even if the run is killed
        # mid-write. Not a result row: the result row (paused, mismatch, refused or error) follows the write.
        a._write({"type": typ, "name": name, "action": "pausing", "time": _now_iso(), "execute": True,
                  "apply_id": a.apply_id, **facts})
        try:
            _put_gateway(w, name, paused)
        except Exception as e:
            action, why = _refusal_or_error(e, "pause the endpoint")
            # A failed or timed-out PUT may still have been applied; resume checks the endpoint before restoring.
            a.log(type=typ, name=name, action=action, reason=why, write_attempted=True, **facts)
            continue
        try:
            after = _read_endpoint(w, name).get("ai_gateway") or {}
            ok = _zero_endpoint_limit(after) and same_settings(gateway_settings(after), paused)
            why = None if ok else "the endpoint reads back with different settings than were written"
        except Exception as e:
            ok, why = False, f"could not read back: {str(e)[:300]}; resume this run to restore the previous settings"
        a.log(type=typ, name=name, action="paused" if ok else "mismatch", write_attempted=True, **facts,
              **({"reason": why} if why else {}))
    return a.results


RESUMABLE_PAUSE_ACTIONS = ("paused", "pausing", "mismatch")  # the pause wrote (or may have written) the endpoint


def _resumable(e: dict) -> bool:
    return (e.get("type") == "serving_endpoint" and bool(e.get("previous_ai_gateway") is not None)
            and (e.get("action") in RESUMABLE_PAUSE_ACTIONS or bool(e.get("write_attempted"))))


def resume_source_error(src: dict | None) -> str | None:
    """Why a run can't be resumed (only an executed pause_legacy run can)."""
    if not src:
        return "that run doesn't exist"
    if src.get("operation") != "pause_legacy" or src.get("mode") != "execute":
        return "resume needs the apply_id of an executed pause run"
    return None


def resume_legacy(w: WorkspaceClient, paused_entries: list[dict], names: list[str] | None, execute: bool,
                  log_path: str, apply_id: str | None, pause_apply_id: str, force: bool = False) -> list[dict]:
    """Restore the previous AI Gateway config of the endpoints that a pause run paused (rollback of a pause).

    paused_entries are that run's log entries. An endpoint whose settings changed after the pause is kept (not
    restored) unless force is set, because restoring would overwrite the change. An endpoint with settings this
    tool doesn't re-send is always kept."""
    a = Applier(w, execute, log_path, apply_id)
    typ = "serving_endpoint"
    by_name: dict[str, dict] = {}
    for e in paused_entries:
        if _resumable(e):  # paused, or written without a confirmed read-back (pausing, mismatch, a failed PUT)
            by_name.setdefault(e.get("name"), e)
    for name in (names or list(by_name)):
        if name not in by_name:
            a.log(type=typ, name=name, action="skipped", reason="not paused by this run")
            continue
        e = by_name[name]
        previous = e.get("previous_ai_gateway") or {}
        paused_body = e.get("paused_ai_gateway") or {}
        try:
            ep = _read_endpoint(w, name)
        except NotFound:
            a.log(type=typ, name=name, action="already_gone")
            continue
        except Exception as ex:
            a.log(type=typ, name=name, action="error", reason=f"could not read the endpoint: {str(ex)[:300]}")
            continue
        gw = ep.get("ai_gateway") or {}
        current = gateway_settings(gw)
        facts = dict(previous_ai_gateway=previous, paused_ai_gateway=paused_body, current_ai_gateway=current,
                     pause_apply_id=pause_apply_id)
        if same_settings(current, previous):
            a.log(type=typ, name=name, action="already_resumed", **facts)
            continue
        unknown = unknown_gateway_keys(gw)
        if unknown:
            a.log(type=typ, name=name, action="kept", **facts,
                  reason=f"ai_gateway has settings this tool doesn't re-send ({', '.join(unknown)}); restore it by hand")
            continue
        if not same_settings(current, paused_body) and not force:
            a.log(type=typ, name=name, action="kept", **facts,
                  reason="the AI Gateway settings changed after the pause; resume with force to restore the previous "
                         "settings anyway")
            continue
        if not execute:
            a.log(type=typ, name=name, action="would_resume", **facts)
            continue
        try:
            _put_gateway(w, name, previous)
        except Exception as ex:
            action, why = _refusal_or_error(ex, "restore the previous settings")
            a.log(type=typ, name=name, action="error" if action == "error" else "kept", reason=why, **facts)
            continue
        try:
            ok = same_settings(gateway_settings(_read_endpoint(w, name).get("ai_gateway") or {}), previous)
        except Exception:
            ok = False
        a.log(type=typ, name=name, action="resumed" if ok else "mismatch", **facts)
    return a.results


def enable_tracking(w: WorkspaceClient, names: list[str], execute: bool, log_path: str,
                    apply_id: str | None = None) -> list[dict]:
    """Turn on usage tracking for legacy endpoints (companion script; runbook step 1).

    An empty names list means every non-custom endpoint in the workspace (databricks-* system endpoints are
    skipped, since Databricks sets their tracking). Endpoints that already track usage are skipped. Existing
    settings are re-sent unchanged; the previous config goes in the log."""
    a = Applier(w, execute, log_path, apply_id)
    typ = "serving_endpoint"
    explicit = bool(names)
    targets = names if explicit else [s["name"] for s in
                                      planner._get(w, "/api/2.0/serving-endpoints").get("endpoints", [])]
    for name in targets:
        try:
            ep = _read_endpoint(w, name)
        except NotFound:
            a.log(type=typ, name=name, action="refused", reason="endpoint not found")
            continue
        except Exception as e:
            a.log(type=typ, name=name, action="error", reason=f"could not read the endpoint: {str(e)[:300]}")
            continue
        kind = endpoint_kind(ep)
        if is_custom_kind(kind):
            a.log(type=typ, name=name, action="refused" if explicit else "skipped", kind=kind,
                  reason=f"{kind} endpoint: custom models and agents are out of scope")
            continue
        if not explicit and kind == "system_ppt":
            a.log(type=typ, name=name, action="skipped", kind=kind,
                  reason="databricks-* system endpoint: Databricks sets its usage tracking")
            continue
        gw = ep.get("ai_gateway") or {}
        if (gw.get("usage_tracking_config") or {}).get("enabled") is True:
            a.log(type=typ, name=name, action="already_enabled", kind=kind)
            continue
        unknown = unknown_gateway_keys(gw)
        if unknown:
            a.log(type=typ, name=name, action="refused", kind=kind,
                  reason=f"ai_gateway has settings this tool doesn't re-send ({', '.join(unknown)}); enable it by hand")
            continue
        previous = gateway_settings(gw)
        body = dict(previous, usage_tracking_config={"enabled": True})
        facts = dict(kind=kind, previous_ai_gateway=previous, requested_ai_gateway=body)
        if not execute:
            a.log(type=typ, name=name, action="would_enable_tracking", **facts)
            continue
        try:
            _put_gateway(w, name, body)
        except Exception as e:
            action, why = _refusal_or_error(e, "enable usage tracking")
            a.log(type=typ, name=name, action=action, reason=why, **facts)
            continue
        try:
            ok = same_settings(gateway_settings(_read_endpoint(w, name).get("ai_gateway") or {}), body)
            why = None if ok else "the endpoint reads back with different settings than were written"
        except Exception as e:
            ok, why = False, f"could not read back: {str(e)[:300]}"
        a.log(type=typ, name=name, action="tracking_enabled" if ok else "mismatch", **facts,
              **({"reason": why} if why else {}))
    return a.results


# ---------------------------------------------------------------------------
# Terraform export
# ---------------------------------------------------------------------------


class RawHCL(str):
    """An HCL expression to emit unquoted (for example var.openai_key)."""


def _hcl_string(v: str) -> str:
    """HCL string literal: JSON-like escapes, \\UXXXXXXXX for non-BMP characters, template markers doubled."""
    out = ['"']
    for ch in v:
        o = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif o < 0x20 or o == 0x7f:
            out.append(f"\\u{o:04x}")
        elif o > 0xFFFF:
            out.append(f"\\U{o:08x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out).replace("${", "$${").replace("%{", "%%{")


def _hcl_key(k: str) -> str:
    return k if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_\-]*", k) else _hcl_string(k)


def to_hcl(value, indent: int = 0) -> str:
    pad, inner = "  " * indent, "  " * (indent + 1)
    if isinstance(value, RawHCL):
        return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return _hcl_string(value)
    if isinstance(value, list):
        if not value:
            return "[]"
        return "[\n" + ",\n".join(inner + to_hcl(v, indent + 1) for v in value) + "\n" + pad + "]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        # Match `terraform fmt`: align "=" within runs of single-line attributes only.
        rendered = [(_hcl_key(k), to_hcl(v, indent + 1)) for k, v in value.items()]
        lines, run = [], []

        def flush():
            width = max((len(k) for k, _ in run), default=0)
            lines.extend(f"{inner}{k.ljust(width)} = {r}" for k, r in run)
            run.clear()
        for k, r in rendered:
            if "\n" in r:
                flush()
                lines.append(f"{inner}{k} = {r}")
            else:
                run.append((k, r))
        flush()
        return "{\n" + "\n".join(lines) + "\n" + pad + "}"
    raise TypeError(f"can't render {type(value)}")


class TerraformSecrets(Secrets):
    """Secrets for Terraform: UC secret references, or sensitive input variables (never values)."""

    def __init__(self, uc_map: dict[str, str] | None):
        super().__init__(None, uc_map, False)
        self.variables: dict[str, str] = {}

    def resolve(self, value, plaintext=None) -> dict:
        m = SECRET_RE.match(value or "")
        key = f"{m.group(1)}/{m.group(2)}" if m else None
        if key and key in self.uc_map:
            return {"secret_reference": {"name": self.uc_map[key]}}
        import hashlib

        if key:
            desc = f"Value of workspace secret {key}"
            var = _safe("secret_" + key.replace("/", "_"))
            if var in self.variables and self.variables[var] != desc:
                var = f"{var}_{hashlib.sha1(key.encode()).hexdigest()[:6]}"
        else:  # a literal key on the legacy endpoint: one variable per credential
            n = sum(1 for v in self.variables if v.startswith("provider_api_key")) + 1
            var, desc = f"provider_api_key_{n}", f"API key {n} (the legacy endpoint used a literal key)"
        self.variables[var] = desc
        return {"plaintext": RawHCL(f"var.{var}")}


TF_DRAFT_HEADER = [
    "# DRAFT: the resource type names databricks_ai_gateway_model_provider_service and",
    "# databricks_ai_gateway_model_service could not be checked against the Terraform provider docs when this",
    "# file was generated. Run `terraform validate` against your databricks provider version before use.",
    "# databricks_grants is AUTHORITATIVE: it replaces every other grant on each model service, so do not",
    "# manage those services' grants anywhere else.",
]


def terraform(w: WorkspaceClient, endpoint_names: list[str] | None, target_catalog: str, target_schema: str,
              uc_map: dict[str, str] | None, out_path: str, grants: bool = True,
              ack_guardrails: bool = False) -> dict:
    """Write Terraform for the selected endpoints instead of calling the API."""
    global _W
    _W = w
    endpoints = planner.inventory(w)
    rows, providers = planner.plan(endpoints, {}, {}, target_catalog, target_schema, traffic_known=False)
    by_name = {e.name: e for e in endpoints}
    selected = [r for r in rows if r.action == "create_model_service"
                and (endpoint_names is None or r.legacy_endpoint in endpoint_names)]
    provider_fqn = {p["provider_key"]: p["provider_service"] for p in providers}
    secrets = TerraformSecrets(uc_map)
    groups: dict[str, list[dict]] = {}
    for r in selected:
        for d in by_name[r.legacy_endpoint].destinations:
            if d["type"] == "external_model":
                groups.setdefault(planner._provider_key(d), []).append(d)

    blocks, skipped, provider_res = [], [], {}
    for key, dests in groups.items():
        fqn = provider_fqn[key]
        try:
            parent, leaf = _leaf(fqn)
            body = build_provider(dests, secrets, "terraform")
        except Manual as m:
            skipped.append({"name": fqn, "reason": str(m)})
            continue
        res = f"provider_{_safe(leaf)}"
        provider_res[key] = res
        blocks.append(f'resource "databricks_ai_gateway_model_provider_service" "{res}" {{\n'
                      f'  parent                    = {to_hcl(parent)}\n'
                      f'  model_provider_service_id = {to_hcl(leaf)}\n'
                      f'  comment                   = {to_hcl(body["comment"])}\n'
                      f'  config = {to_hcl(body["config"], 1)}\n}}\n')
    for r in selected:
        ep = by_name[r.legacy_endpoint]
        keys = [planner._provider_key(d) for d in ep.destinations if d["type"] == "external_model"]
        if any(k not in provider_res for k in keys):
            skipped.append({"name": r.target_service, "reason": "provider service not generated"})
            continue
        try:
            body = build_model_service(ep, r, provider_fqn, "terraform", ack_guardrails)
            parent, leaf = _leaf(r.target_service)
        except Manual as m:
            skipped.append({"name": r.target_service, "reason": str(m)})
            continue
        res = f"service_{_safe(leaf)}"
        deps = sorted({f"databricks_ai_gateway_model_provider_service.{provider_res[k]}" for k in keys})
        blocks.append(f'# Migrated from legacy serving endpoint {ep.name}\n'
                      f'resource "databricks_ai_gateway_model_service" "{res}" {{\n'
                      f'  parent           = {to_hcl(parent)}\n'
                      f'  model_service_id = {to_hcl(leaf)}\n'
                      f'  comment          = {to_hcl(body["comment"])}\n'
                      f'  config = {to_hcl(body["config"], 1)}\n'
                      + (f'  depends_on = [{", ".join(deps)}]\n' if deps else "") + "}\n")
        if grants and r.grants:
            # A grant block's body renders like an object without the braces.
            grant_blocks = "".join("  grant " + to_hcl({"principal": g["principal"], "privileges": g["privileges"]}, 1)
                                   + "\n" for g in r.grants)
            blocks.append(f'# Authoritative: replaces any other grants on this service\n'
                          f'resource "databricks_grants" "{res}" {{\n'
                          f'  model_service = databricks_ai_gateway_model_service.{res}.name\n{grant_blocks}}}\n')
    header = [f'# Generated by unity-gateway-migration-toolkit {planner.__version__}. {planner.DISCLAIMER}',
              f'# Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")} from {w.config.host}',
              *TF_DRAFT_HEADER,
              '', 'terraform {', '  required_providers {',
              '    databricks = {', '      source  = "databricks/databricks"', '      version = ">= 1.124.0"',
              '    }', '  }', '}', '']
    for var, desc in sorted(secrets.variables.items()):
        header += [f'variable "{var}" {{', f'  description = {to_hcl(desc)}', '  type        = string',
                   '  sensitive   = true', '}', '']
    with open(out_path, "w") as f:
        f.write("\n".join(header) + "\n" + "\n".join(blocks))
    return {"file": out_path, "provider_services": len(provider_res),
            "model_services": sum(1 for b in blocks if "databricks_ai_gateway_model_service\"" in b),
            "variables": sorted(secrets.variables), "skipped": skipped}


def _split(value: str | None) -> list[str]:
    return [s.strip() for s in (value or "").split(",") if s.strip()]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--profile", help='Databricks CLI profile (default: the CLI default)')
    sub = p.add_subparsers(dest="cmd", required=True)
    ap = sub.add_parser("apply")
    ap.add_argument("--endpoints", help="Comma-separated legacy endpoint names (one wave)")
    ap.add_argument("--all", action="store_true", help="Every external model / PT endpoint in the workspace")
    ap.add_argument("--target-catalog", required=True, help='Catalog for the new model services (must exist)')
    ap.add_argument("--target-schema", required=True, help='Schema for the new model services (must exist)')
    ap.add_argument("--uc-secret-map", help="JSON file or string mapping 'scope/key' to 'secrets/c.s.name'")
    ap.add_argument("--allowed-secret-schemas", help="Comma-separated catalog.schema names that UC secrets may live in "
                                                     "(required with --uc-secret-map)")
    ap.add_argument("--allow-secret-read", action="store_true", help='Read workspace secret values at --execute and copy them into provider services (prefer --uc-secret-map)')
    ap.add_argument("--create-uc-secrets", action="store_true",
                    help="Create each Unity Catalog secret named in --uc-secret-map from its workspace secret (read with "
                         "your identity; the value is never printed). Rollback deletes the ones it created")
    ap.add_argument("--allow-secret-read-enabled", action="store_true",
                    help="Enables --allow-secret-read for this run (the CLI equivalent of the installer's setting)")
    ap.add_argument("--no-grants", action="store_true", help="Don't copy legacy endpoint permissions as EXECUTE/MANAGE grants")
    ap.add_argument("--ack-guardrails", action="store_true",
                    help="Apply even though legacy guardrails aren't migrated; the item records guardrails_not_migrated")
    ap.add_argument("--smoke", action="store_true", help="After --execute, GET each created model service and check its state (no inference calls)")
    ap.add_argument("--execute", action="store_true", help="Actually create objects (default is a dry run)")
    ap.add_argument("--log", default="apply_log.jsonl", help='JSON-lines log of what was created (needed for rollback; default apply_log.jsonl)')
    tp = sub.add_parser("terraform", help="Write Terraform for the plan instead of calling the API")
    tp.add_argument("--endpoints", help='Comma-separated legacy endpoint names')
    tp.add_argument("--all", action="store_true", help='Every external model and PT endpoint in the plan')
    tp.add_argument("--target-catalog", required=True, help='Catalog for the new model services (must exist)')
    tp.add_argument("--target-schema", required=True, help='Schema for the new model services (must exist)')
    tp.add_argument("--uc-secret-map", help='JSON file or string mapping "scope/key" to "secrets/catalog.schema.name"')
    tp.add_argument("--allowed-secret-schemas", help="Comma-separated catalog.schema names allowed for UC secrets")
    tp.add_argument("--no-grants", action="store_true", help="Don't copy legacy endpoint permissions as EXECUTE/MANAGE grants")
    tp.add_argument("--ack-guardrails", action="store_true", help="Render endpoints whose legacy guardrails aren't migrated")
    tp.add_argument("--out", default="ug_migration.tf", help='Terraform file to write (default ug_migration.tf)')
    rb = sub.add_parser("rollback")
    rb.add_argument("--log", default="apply_log.jsonl", help='JSON-lines log of what was created (needed for rollback; default apply_log.jsonl)')
    rb.add_argument("--execute", action="store_true", help='Actually delete (otherwise a dry run)')
    rb.add_argument("--force", action="store_true", help="Delete objects changed since apply (otherwise they are kept)")
    a = p.parse_args(argv)
    uc_map = None
    if getattr(a, "uc_secret_map", None):
        uc_map = json.load(open(a.uc_secret_map)) if os.path.exists(a.uc_secret_map) else json.loads(a.uc_secret_map)
    try:
        if a.cmd == "terraform":
            if not a.all and not a.endpoints:
                p.error("pass --endpoints or --all")
            if uc_map:
                check_secret_policy(uc_map, _split(a.allowed_secret_schemas), False, False)
            w = WorkspaceClient(profile=a.profile) if a.profile else WorkspaceClient()
            print(json.dumps(terraform(w, None if a.all else _split(a.endpoints), a.target_catalog, a.target_schema,
                                       uc_map, a.out, grants=not a.no_grants, ack_guardrails=a.ack_guardrails),
                             indent=1))
            return 0
        w = WorkspaceClient(profile=a.profile) if a.profile else WorkspaceClient()
        if a.cmd == "rollback":
            entries, _ = read_log(a.log)
            if any(e.get("type") == "run" and e.get("action") == "rollback_complete" for e in entries):
                raise PolicyError(f"{a.log} already has a finished rollback")
            own = next((e.get("apply_id") for e in entries if e.get("execute") and e.get("apply_id")), None)
            protect, released = protection_from_runs(cli_runs(a.log), own)
            res = rollback(w, a.log, a.execute, protect=protect, apply_id=own, released=released,
                           force=a.force, audit_path=a.log)
        else:
            if not a.all and not a.endpoints:
                p.error("pass --endpoints for one wave, or --all")
            res = apply(w, None if a.all else _split(a.endpoints), a.target_catalog, a.target_schema, a.execute,
                        Secrets(w, uc_map, a.allow_secret_read, dry_run=not a.execute,
                                allowed_schemas=_split(a.allowed_secret_schemas),
                                read_enabled=a.allow_secret_read_enabled, create_uc=a.create_uc_secrets),
                        a.log, grants=not a.no_grants, ack_guardrails=a.ack_guardrails, smoke=a.smoke)
    except PolicyError as e:
        print(f"Refused: {e}", file=sys.stderr)
        return 2
    for r in res:
        print(json.dumps(_mask(r)))
    if a.cmd == "apply" and not a.execute:
        print("DRY RUN: nothing was created. Re-run with --execute to apply.", file=sys.stderr)
    problems = [r for r in res if r.get("action") in ("error", "manual", "mismatch", "needs_attention", "smoke_failed", "kept")]
    if problems:
        print(f"{len(problems)} item(s) need attention (error, manual, mismatch, needs_attention, smoke_failed or kept).",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
