"""Unity Gateway migration apply (prototype, opt-in).

Creates the Unity Gateway objects that ug_migration_planner proposes for
external model and Provisioned Throughput endpoints: model provider services,
model services (routing, fallback, rate limits, inference table) and EXECUTE /
MANAGE grants. Legacy endpoints are not touched, and clients keep calling them
until their code changes, so applying is safe to do ahead of the cutover.

DRY RUN BY DEFAULT: without --execute it only prints what it would create.
Every object it creates is written to a log, and `rollback` deletes only the
objects that log says this run created (and that still carry this run's
apply mark). See NOTES_apply.md for the safety rules.

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
import uuid
from collections import Counter
from datetime import datetime, timezone

from databricks.sdk import WorkspaceClient
from databricks.sdk.common.types.fieldmask import FieldMask
from databricks.sdk.errors import AlreadyExists, NotFound
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
ROLLBACK_TYPES = ("model_service", "model_provider_service")
OWNED_ACTIONS = ("created", "creating", "exists", "updated")  # actions that put an object in a rollback log
USE_ACTIONS = ("created", "creating", "exists", "updated")  # actions that keep an object in use (protection)
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
    """Fail before any change unless the secret settings are allowed for this job (see NOTES_apply.md)."""
    allowed = {s.strip() for s in allowed_schemas or [] if s and s.strip()}
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
        if f"{m.group(1)}.{m.group(2)}" not in allowed:
            raise PolicyError(f"{ref} is outside the allowed secret schemas {sorted(allowed)}")


class Secrets:
    def __init__(self, w: WorkspaceClient | None, uc_map: dict[str, str] | None, allow_read: bool,
                 dry_run: bool = False, allowed_schemas=(), read_enabled: bool = False):
        self.w, self.uc_map, self.allow_read, self.dry_run = w, uc_map or {}, allow_read, dry_run
        self.allowed_schemas = list(allowed_schemas or [])
        self.read_enabled = read_enabled
        self._checked: set[str] = set()

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
        if not m:
            raise Manual("credential is not a {{secrets/scope/key}} reference")
        key = f"{m.group(1)}/{m.group(2)}"
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


SENSITIVE_KEY_RE = re.compile(r"(^|_)(secret|token|password|passwd|api_?key)(_|$)", re.I)
NOT_SENSITIVE_KEYS = {"secret_reference", "secret_schemas", "allowed_secret_schemas"}


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
        # are primaries; when every served entity carries traffic (a split), no fallback destination is added.
        fallback = [d for d, p in dests if p == 0] if ep.fallback_enabled else []
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


def running_in_logs(log_path: str, target: str, own_apply_id: str | None = None, now: datetime | None = None) -> list[str]:
    """Apply ids that started on this target, have no run_end marker, and started recently (sibling logs)."""
    now = now or datetime.now(timezone.utc)
    conflicts = []
    for path in glob.glob(os.path.join(os.path.dirname(os.path.abspath(log_path)), "*.jsonl")):
        entries, _ = read_log(path)
        for e in entries:
            if e.get("type") == "run" and e.get("action") == "run_start" and e.get("target") == target \
                    and e.get("apply_id") != own_apply_id:
                ended = any(x.get("type") == "run" and x.get("action") == "run_end"
                            and x.get("apply_id") == e.get("apply_id") for x in entries)
                age = (now - datetime.fromisoformat(e["time"])).total_seconds()
                if not ended and age < STALE_RUN_HOURS * 3600:
                    conflicts.append(e.get("apply_id"))
    return conflicts


def apply(w: WorkspaceClient, endpoint_names: list[str] | None, target_catalog: str, target_schema: str,
          execute: bool, secrets: Secrets, log_path: str, grants: bool = True, ack_guardrails: bool = False,
          smoke: bool = False, apply_id: str | None = None) -> list[dict]:
    apply_id = apply_id or str(uuid.uuid4())
    try:
        w.schemas.get(f"{target_catalog}.{target_schema}")
    except NotFound:
        raise SystemExit(f"Target schema {target_catalog}.{target_schema} doesn't exist: create it first")
    secrets.validate_policy()  # before any change

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
        conflicts = running_in_logs(log_path, target, apply_id)
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
    created_here, done, targets, seen, stamp = set(), set(), [], set(), {}
    for e in entries:
        if e.get("rollback_of") or e.get("type") not in ROLLBACK_TYPES:  # audit lines of earlier rollbacks skip
            continue
        key, act = (e["type"], e["name"]), e.get("action")
        if act in ("created", "creating"):
            created_here.add(key)
        if act == "created":
            done.add(key)
        if act in OWNED_ACTIONS:
            if key not in seen:
                seen.add(key)
                targets.append(key)
            if e.get("etag") or e.get("update_time"):
                stamp[key] = e
    grant_entries = [e for e in entries if not e.get("rollback_of") and e.get("type") == "grant"
                     and e.get("action") == "granted" and e.get("added")]
    deleted, still_mine = set(), set()
    for key in reversed(targets):
        typ, name = key
        try:
            if typ == "model_service":
                obj = w.ai_gateway.get_model_service(name=f"model-services/{name}")
            else:
                obj = w.ai_gateway.get_model_provider_service(name=f"model-provider-services/{name}")
            d = obj.as_dict() or {}
            comment = d.get("comment") or ""
            if key in protect:
                emit({"type": typ, "name": name, "action": "kept", "reason": protect[key]})
                continue
            if not is_toolkit(comment):
                emit({"type": typ, "name": name, "action": "kept",
                      "reason": "not created by this tool (comment doesn't match)"})
                continue
            tag, created = owner_tag(comment), key in created_here
            owned = created if tag is None else (tag == apply_id or (not created and tag in released))
            if not owned:
                reason = (f"owned by apply {tag}, which hasn't been rolled back" if tag
                          else "no apply mark and not created by this run")
                emit({"type": typ, "name": name, "action": "kept", "reason": reason})
                continue
            still_mine.add(key)
            if typ == "model_provider_service":
                refs = services_referencing(w, name)
                if refs:
                    emit({"type": typ, "name": name, "action": "kept",
                          "reason": f"still referenced by model service(s): {', '.join(refs)}"})
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
                          "reason": f"changed since apply (update_time {d.get('update_time')}); "
                                    "rerun with force to delete anyway"})
                    continue
            if key not in done and key in created_here:
                emit({"type": typ, "name": name, "action": "note",
                      "reason": "create was interrupted; the object exists and carries this run's mark"})
            if not execute:
                emit({"type": typ, "name": name, "action": "would_delete"})
                continue
            kw = {} if force else {"etag": d.get("etag")}  # conditional delete when not forcing
            if typ == "model_service":
                w.ai_gateway.delete_model_service(name=f"model-services/{name}", **kw)
            else:
                w.ai_gateway.delete_model_provider_service(name=f"model-provider-services/{name}", **kw)
            deleted.add(key)
            emit({"type": typ, "name": name, "action": "deleted"})
        except NotFound:
            emit({"type": typ, "name": name, "action": "already_gone"})
        except Exception as ex:
            emit({"type": typ, "name": name, "action": "error", "reason": str(ex)[:300]})

    # Grants this run added to services that survive the rollback are revoked (only what it added).
    for e in grant_entries:
        key = ("model_service", e["name"])
        if key in deleted or key not in still_mine or key in protect:
            continue
        changes = [catalog.PermissionsChange(principal=a["principal"],
                                             remove=[catalog.Privilege(p) for p in a["privileges"]])
                   for a in e["added"]]
        if not execute:
            emit({"type": "grant", "name": e["name"], "action": "would_revoke", "grants": e["added"]})
            continue
        try:
            w.grants.update(securable_type="model_service", full_name=e["name"], changes=changes)
            emit({"type": "grant", "name": e["name"], "action": "revoked", "grants": e["added"]})
        except NotFound:
            emit({"type": "grant", "name": e["name"], "action": "already_gone"})
        except Exception as ex:
            emit({"type": "grant", "name": e["name"], "action": "error", "reason": str(ex)[:300]})

    if execute and audit_path:
        with open(audit_path, "a") as f:
            f.write(json.dumps({"type": "run", "action": "rollback_complete", "rollback_of": apply_id,
                                "time": _now_iso()}) + "\n")
    return out


def services_referencing(w: WorkspaceClient, provider_fqn: str) -> list[str]:
    """Model services in the provider's schema whose destinations or fallback use it. Raises if it can't check."""
    target = f"model-provider-services/{provider_fqn}"
    prefix = "model-services/" + provider_fqn.rsplit(".", 1)[0] + "."
    refs = []
    for svc in w.ai_gateway.list_model_services():
        d = svc.as_dict() or {}
        name = d.get("name") or ""
        if not name.startswith(prefix):
            continue
        if "config" not in d:  # the listing may omit the config
            d = w.ai_gateway.get_model_service(name=name).as_dict() or {}
        routing = (d.get("config") or {}).get("routing") or {}
        dests = (routing.get("destinations") or []) + ((routing.get("fallback") or {}).get("destinations") or [])
        if any((x.get("external_model_config") or {}).get("model_provider_service") == target for x in dests):
            refs.append(name[len("model-services/"):])
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
                                read_enabled=a.allow_secret_read_enabled),
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
