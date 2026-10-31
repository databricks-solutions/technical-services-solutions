"""Unity Gateway migration apply (prototype, opt-in).

Creates the Unity Gateway objects that ug_migration_planner proposes for
external model and Provisioned Throughput endpoints: model provider services,
model services (routing, fallback, rate limits, inference table) and EXECUTE /
MANAGE grants. Legacy endpoints are not touched, and clients keep calling them
until their code changes, so applying is safe to do ahead of the cutover.

DRY RUN BY DEFAULT: without --execute it only prints what it would create.
Every object it creates is written to a log, and `rollback` deletes exactly
those objects (nothing it found already existing).

    python ug_migration_apply.py --profile P apply --endpoints a,b --target-catalog c --target-schema s
    python ug_migration_apply.py --profile P apply --endpoints a,b ... --execute --uc-secret-map map.json
    python ug_migration_apply.py --profile P rollback --log apply_log.jsonl --execute

Secrets: legacy endpoints reference workspace secrets ({{secrets/scope/key}}).
Model provider services take either a Unity Catalog secret reference
(--uc-secret-map '{"scope/key": "secrets/catalog.schema.name"}', preferred) or
the value itself (--allow-secret-read reads it with the Secrets API at run
time; the value is never printed or logged).

Supported providers in this prototype: OpenAI, Azure OpenAI (API key) and
Anthropic. Others are reported as manual.

Written by STS as a prototype; not an official Databricks tool.
"""

from __future__ import annotations

import argparse
import base64
import copy
import json
import os
import re
import sys
from datetime import datetime, timezone

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound
from databricks.sdk.service import catalog

import ug_migration_planner as planner

SECRET_RE = re.compile(r"^\{\{\s*secrets/([^/}]+)/([^}]+?)\s*\}\}$")

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


def _leaf(fqn: str) -> tuple[str, str]:
    parts = (fqn or "").split(".")
    if len(parts) != 3 or not all(parts):
        raise Manual(f"{fqn!r} isn't a catalog.schema.name; use catalog and schema names without dots")
    c, s, n = parts
    return f"schemas/{c}.{s}", n


def _safe(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", (name or "dest").lower())[:60]


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------


class Secrets:
    def __init__(self, w: WorkspaceClient, uc_map: dict[str, str] | None, allow_read: bool, dry_run: bool = False):
        self.w, self.uc_map, self.allow_read, self.dry_run = w, uc_map or {}, allow_read, dry_run

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
            return {"secret_reference": {"name": self.uc_map[key]}}
        if self.allow_read:
            if self.dry_run:
                return {"plaintext": f"<value of {key}, read at --execute>"}
            raw = self.w.secrets.get_secret(m.group(1), m.group(2)).value
            return {"plaintext": base64.b64decode(raw).decode()}
        raise Manual(f"secret {key}: add it to --uc-secret-map or pass --allow-secret-read")


def _mask(obj):
    """Copy of a payload with secret values hidden, for printing and logs."""
    obj = copy.deepcopy(obj)

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "plaintext":
                    o[k] = "***"
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(obj)
    return obj


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


def build_provider(dests: list[dict], secrets: Secrets) -> dict:
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
    return {"comment": f"Created by ug-migration-toolkit {planner.__version__} (prototype)",
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


MAX_DESTINATIONS = 10
MAX_FALLBACKS = 5
MAX_RATE_LIMITS = 20  # per model service
MAX_GROUP_RATE_LIMITS = 5  # group-specific limits per model service
TOOL_MARK = "ug-migration-toolkit"


def build_model_service(ep: planner.LegacyEndpoint, row: planner.PlanRow, provider_fqn: dict[str, str]) -> dict:
    """ModelService body: destinations, fallback, rate limits and inference table."""
    blocking = [n.removeprefix(planner.BLOCKING_PREFIX) for n in row.needs_human
                if n.startswith(planner.BLOCKING_PREFIX)]
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
        primary = [d for d, p in dests if p > 0]
        rest = [d for d, p in dests if p == 0]
        if not primary:
            raise Manual("every destination has 0% traffic")
        if sum(p for _, p in dests) != 100:
            raise Manual(f"traffic percentages add up to {sum(p for _, p in dests)}, not 100")
        if len(primary) > 1:
            for d, p in dests:
                if p > 0:
                    d["traffic_percentage"] = p
        # v1 fallback tries the other served entities; v3 lists them as ordered fallbacks.
        fallback = rest if ep.fallback_enabled else []
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
            raise Manual(f"{len(row.rate_limits)} rate limits ({len(groups)} for groups); a model service allows "
                         f"{MAX_RATE_LIMITS} ({MAX_GROUP_RATE_LIMITS} for groups): merge some limits first")
        config["rate_limits"] = row.rate_limits
    if row.inference_table:
        config["inference_table"] = {k: v for k, v in row.inference_table.items() if k in ("parent", "table_name_prefix")}
    return {"comment": f"Migrated from legacy serving endpoint {ep.name} by ug-migration-toolkit {planner.__version__}",
            "config": config}


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def _dest_sig(d: dict) -> tuple:
    ext = d.get("external_model_config") or {}
    pt = d.get("provisioned_throughput_config") or {}
    return (d.get("name"), d.get("destination_type"), ext.get("model_provider_service"),
            (ext.get("target") or {}).get("model"), pt.get("model_serving_endpoint"), d.get("traffic_percentage"))


def _limit_sig(l: dict) -> tuple:
    return (l.get("key"), l.get("renewal_period"), l.get("principal"), l.get("requests"), l.get("tokens"))


def provider_differences(have: dict, want: dict) -> list[str]:
    """What differs between an existing provider service config and the planned one."""
    diffs = []
    if have.get("provider_type") != want.get("provider_type"):
        diffs.append(f"provider {have.get('provider_type')} vs {want.get('provider_type')}")
    have_models = {t.get("model") for t in have.get("targets") or []}
    missing = {t.get("model") for t in want.get("targets") or []} - have_models
    if missing and not have.get("allow_all_targets"):
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


class Applier:
    def __init__(self, w: WorkspaceClient, execute: bool, log_path: str):
        self.w, self.execute, self.log_path = w, execute, log_path
        self.results: list[dict] = []

    def log(self, **entry) -> None:
        entry["time"] = datetime.now(timezone.utc).isoformat()
        entry["execute"] = self.execute
        self.results.append(entry)
        if self.execute:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(_mask(entry)) + "\n")

    def ensure_provider(self, fqn: str, body: dict) -> str:
        try:
            existing = self.w.ai_gateway.get_model_provider_service(name=f"model-provider-services/{fqn}")
        except NotFound:
            existing = None
        if existing is not None:
            diffs = provider_differences((existing.as_dict() or {}).get("config") or {}, body["config"])
            if diffs:
                raise Manual(f"{fqn} already exists with a different configuration ({'; '.join(diffs)}); "
                             "rename the target or reconcile it by hand")
            self.log(type="model_provider_service", name=fqn, action="exists")
            return "exists"
        if not self.execute:
            self.log(type="model_provider_service", name=fqn, action="would_create", body=_mask(body))
            return "would_create"
        parent, leaf = _leaf(fqn)
        self.log(type="model_provider_service", name=fqn, action="creating")
        self.w.ai_gateway.create_model_provider_service(
            model_provider_service=catalog.ModelProviderService.from_dict(body), parent=parent,
            model_provider_service_id=leaf)
        self.log(type="model_provider_service", name=fqn, action="created")
        return "created"

    def ensure_model_service(self, fqn: str, body: dict) -> str:
        try:
            self.w.ai_gateway.get_model_service(name=f"model-services/{fqn}")
            self.log(type="model_service", name=fqn, action="exists")
            return "exists"
        except NotFound:
            pass
        if not self.execute:
            self.log(type="model_service", name=fqn, action="would_create", body=body)
            return "would_create"
        parent, leaf = _leaf(fqn)
        self.log(type="model_service", name=fqn, action="creating")
        self.w.ai_gateway.create_model_service(model_service=catalog.ModelService.from_dict(body),
                                               parent=parent, model_service_id=leaf)
        self.log(type="model_service", name=fqn, action="created")
        return "created"

    def grant(self, fqn: str, grants: list[dict]) -> None:
        changes = [catalog.PermissionsChange(principal=g["principal"],
                                             add=[catalog.Privilege(p) for p in g["privileges"]]) for g in grants]
        if not changes:
            return
        if not self.execute:
            self.log(type="grant", name=fqn, action="would_grant", grants=grants)
            return
        self.w.grants.update(securable_type="model_service", full_name=fqn, changes=changes)
        self.log(type="grant", name=fqn, action="granted", grants=grants)

    def verify(self, fqn: str, body: dict, grants: list[dict]) -> list[str]:
        """Read the service back and compare it with what was requested."""
        issues = []
        got = self.w.ai_gateway.get_model_service(name=f"model-services/{fqn}").as_dict().get("config", {})
        want = body["config"]
        for part in ("destinations", "fallback"):
            g = (got.get("routing", {}).get("fallback") or {}).get("destinations", []) if part == "fallback" \
                else got.get("routing", {}).get("destinations", [])
            w_ = (want["routing"].get("fallback") or {}).get("destinations", []) if part == "fallback" \
                else want["routing"]["destinations"]
            if [_dest_sig(d) for d in g] != [_dest_sig(d) for d in w_]:
                issues.append(f"{part} differ: have {[_dest_sig(d) for d in g]}, want {[_dest_sig(d) for d in w_]}")
        if sorted(_limit_sig(l) for l in got.get("rate_limits") or []) != \
                sorted(_limit_sig(l) for l in want.get("rate_limits") or []):
            issues.append("rate limits differ")
        if want.get("inference_table") and not got.get("inference_table"):
            issues.append("inference table missing")
        if grants:
            perms = self.w.grants.get(securable_type="model_service", full_name=fqn).as_dict()
            have = {(a["principal"], p) for a in perms.get("privilege_assignments", []) for p in a.get("privileges", [])}
            for g in grants:
                for p in g["privileges"]:
                    if (g["principal"], p) not in have:
                        issues.append(f"grant {p} to {g['principal']} missing")
        self.log(type="verify", name=fqn, action="ok" if not issues else "mismatch", issues=issues)
        return issues


def apply(w: WorkspaceClient, endpoint_names: list[str] | None, target_catalog: str, target_schema: str,
          execute: bool, secrets: Secrets, log_path: str, grants: bool = True) -> list[dict]:
    try:
        w.schemas.get(f"{target_catalog}.{target_schema}")
    except NotFound:
        raise SystemExit(f"Target schema {target_catalog}.{target_schema} doesn't exist: create it first")

    global _W
    _W = w
    endpoints = planner.inventory(w)
    rows, all_providers = planner.plan(endpoints, {}, {}, target_catalog, target_schema, traffic_known=False)
    by_name = {e.name: e for e in endpoints}
    selected = [r for r in rows if r.action == "create_model_service"
                and (endpoint_names is None or r.legacy_endpoint in endpoint_names)]
    missing = set(endpoint_names or []) - {r.legacy_endpoint for r in selected}
    a = Applier(w, execute, log_path)
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
    failed_providers = set()
    for key, dests in groups.items():
        fqn = provider_fqn[key]
        try:
            a.ensure_provider(fqn, build_provider(dests, secrets))
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
            body = build_model_service(ep, r, provider_fqn)
            state = a.ensure_model_service(r.target_service, body)
            if grants and r.grants:
                a.grant(r.target_service, r.grants)
            if execute and state in ("created", "exists"):
                a.verify(r.target_service, body, r.grants if grants else [])
        except Manual as m:
            a.log(type="model_service", name=r.target_service, action="manual", reason=str(m))
        except Exception as e:
            a.log(type="model_service", name=r.target_service, action="error", reason=str(e)[:500])
    return a.results


def rollback(w: WorkspaceClient, log_path: str, execute: bool, protect: set | None = None) -> list[dict]:
    """Delete only the objects this tool created, newest first."""
    protect = protect or set()
    entries, bad = [], 0
    for line in open(log_path):
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            bad += 1
    out = [{"type": "log", "name": log_path, "action": "skipped_lines", "count": bad}] if bad else []
    done = {(e.get("type"), e.get("name")) for e in entries if e.get("action") == "created"}
    targets, seen = [], set()
    for e in entries:
        key = (e.get("type"), e.get("name"))
        if e.get("action") in ("created", "creating") and key not in seen and \
                e.get("type") in ("model_service", "model_provider_service"):
            seen.add(key)
            targets.append(e)
    for e in reversed(targets):
        name = e["name"]
        try:
            getter = w.ai_gateway.get_model_service if e["type"] == "model_service" \
                else w.ai_gateway.get_model_provider_service
            prefix = "model-services/" if e["type"] == "model_service" else "model-provider-services/"
            try:
                obj = getter(name=prefix + name)
            except NotFound:
                out.append({"type": e["type"], "name": name, "action": "already_gone"})
                continue
            if (e["type"], name) in protect:
                out.append({"type": e["type"], "name": name, "action": "kept",
                            "reason": "another execute run created or reuses it; roll that run back first"})
                continue
            if TOOL_MARK not in (getattr(obj, "comment", None) or ""):
                out.append({"type": e["type"], "name": name, "action": "kept",
                            "reason": "not created by this tool (comment doesn't match)"})
                continue
            if (e["type"], name) not in done:
                out.append({"type": e["type"], "name": name, "action": "note",
                            "reason": "create was interrupted; the object exists and carries this tool's mark"})
            if not execute:
                out.append({"type": e["type"], "name": name, "action": "would_delete"})
                continue
            if e["type"] == "model_service":
                w.ai_gateway.delete_model_service(name=f"model-services/{name}")
            elif e["type"] == "model_provider_service":
                w.ai_gateway.delete_model_provider_service(name=f"model-provider-services/{name}")
            out.append({"type": e["type"], "name": name, "action": "deleted"})
        except NotFound:
            out.append({"type": e["type"], "name": name, "action": "already_gone"})
        except Exception as ex:
            out.append({"type": e["type"], "name": name, "action": "error", "reason": str(ex)[:300]})
    return out


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


def terraform(w: WorkspaceClient, endpoint_names: list[str] | None, target_catalog: str, target_schema: str,
              uc_map: dict[str, str] | None, out_path: str, grants: bool = True) -> dict:
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
            body = build_provider(dests, secrets)
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
            body = build_model_service(ep, r, provider_fqn)
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
    header = [f'# Generated by ug-migration-toolkit {planner.__version__}. {planner.DISCLAIMER}',
              f'# Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")} from {w.config.host}',
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
    ap.add_argument("--allow-secret-read", action="store_true", help='Read workspace secret values at --execute and copy them into provider services (prefer --uc-secret-map)')
    ap.add_argument("--no-grants", action="store_true", help="Don't copy legacy endpoint permissions as EXECUTE/MANAGE grants")
    ap.add_argument("--execute", action="store_true", help="Actually create objects (default is a dry run)")
    ap.add_argument("--log", default="apply_log.jsonl", help='JSON-lines log of what was created (needed for rollback; default apply_log.jsonl)')
    tp = sub.add_parser("terraform", help="Write Terraform for the plan instead of calling the API")
    tp.add_argument("--endpoints", help='Comma-separated legacy endpoint names')
    tp.add_argument("--all", action="store_true", help='Every external model and PT endpoint in the plan')
    tp.add_argument("--target-catalog", required=True, help='Catalog for the new model services (must exist)')
    tp.add_argument("--target-schema", required=True, help='Schema for the new model services (must exist)')
    tp.add_argument("--uc-secret-map", help='JSON file or string mapping "scope/key" to "secrets/catalog.schema.name"')
    tp.add_argument("--no-grants", action="store_true", help="Don't copy legacy endpoint permissions as EXECUTE/MANAGE grants")
    tp.add_argument("--out", default="ug_migration.tf", help='Terraform file to write (default ug_migration.tf)')
    rb = sub.add_parser("rollback")
    rb.add_argument("--log", default="apply_log.jsonl", help='JSON-lines log of what was created (needed for rollback; default apply_log.jsonl)')
    rb.add_argument("--execute", action="store_true", help='Actually delete (otherwise a dry run)')
    a = p.parse_args(argv)
    w = WorkspaceClient(profile=a.profile) if a.profile else WorkspaceClient()
    uc_map = None
    if getattr(a, "uc_secret_map", None):
        uc_map = json.load(open(a.uc_secret_map)) if os.path.exists(a.uc_secret_map) else json.loads(a.uc_secret_map)
    if a.cmd == "terraform":
        if not a.all and not a.endpoints:
            p.error("pass --endpoints or --all")
        print(json.dumps(terraform(w, None if a.all else [e.strip() for e in a.endpoints.split(",") if e.strip()],
                                   a.target_catalog, a.target_schema, uc_map, a.out, grants=not a.no_grants), indent=1))
        return 0
    if a.cmd == "rollback":
        res = rollback(w, a.log, a.execute)
    else:
        if not a.all and not a.endpoints:
            p.error("pass --endpoints for one wave, or --all")
        res = apply(w, None if a.all else [e.strip() for e in a.endpoints.split(",") if e.strip()],
                    a.target_catalog, a.target_schema, a.execute,
                    Secrets(w, uc_map, a.allow_secret_read, dry_run=not a.execute),
                    a.log, grants=not a.no_grants)
    for r in res:
        print(json.dumps(_mask(r)))
    if a.cmd == "apply" and not a.execute:
        print("DRY RUN: nothing was created. Re-run with --execute to apply.", file=sys.stderr)
    problems = [r for r in res if r.get("action") in ("error", "manual", "mismatch")]
    if problems:
        print(f"{len(problems)} item(s) need attention (error, manual or mismatch).", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
