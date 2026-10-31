"""Unity Gateway migration planner (prototype, read-only).

Inventories legacy model serving endpoints in one workspace, plans their move
to Unity Gateway (v3) model services, scans workspace assets for client code
that still calls legacy endpoints, and checks recent legacy traffic.

Every call is a GET or a SELECT. Nothing is created, changed or deleted.

Run locally:
    python ug_migration_planner.py --profile <cli-profile> --warehouse-id <id> --out ./out

Run in a notebook: %run this file, then call run(...) with the notebook's
WorkspaceClient().

Written by STS as a prototype; not an official Databricks tool.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from databricks.sdk import WorkspaceClient

__version__ = "0.7.0"
DISCLAIMER = ("Prototype from Databricks Shared Technical Services, provided as is. It only reads unless you run apply or "
              "rollback, snapshots, or the dashboard step; review results before acting.")

# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass
class LegacyEndpoint:
    name: str
    endpoint_id: str | None
    kind: str  # system_ppt | external_model | provisioned_throughput | custom_model | agent | unknown
    destinations: list[dict] = field(default_factory=list)
    traffic_routes: list[dict] = field(default_factory=list)
    rate_limits: list[dict] = field(default_factory=list)
    guardrails: dict | None = None
    inference_table: dict | None = None
    fallback_enabled: bool = False
    usage_tracking: bool | None = None
    tags: list[dict] = field(default_factory=list)
    can_query: list[dict] = field(default_factory=list)
    creator: str | None = None
    state: str | None = None


@dataclass
class PlanRow:
    legacy_endpoint: str
    kind: str
    action: str  # use_system_ai | create_model_service | out_of_scope | manual
    target_service: str | None
    provider_service: str | None
    destination_type: str | None
    rate_limits: list[dict]
    routing: dict | None
    inference_table: dict | None
    grants: list[dict]
    tags: list[dict]
    needs_human: list[str]
    requests_window: int = 0
    requesters: int = 0
    last_request: str | None = None
    target_status: str | None = None  # exists | missing | system (for system.ai targets)


@dataclass
class ClientReference:
    asset_type: str  # notebook | file | job_sql | sql_query | dashboard | app
    asset: str
    line: int | None
    pattern: str
    match: str
    legacy_endpoint: str | None
    suggestion: str
    line_text: str | None = None
    fixed_line: str | None = None
    fix_confidence: str | None = None  # auto | review | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get(w: WorkspaceClient, path: str, query: dict | None = None) -> dict:
    return w.api_client.do("GET", path, query=query or {})


def workspace_id_of(w: WorkspaceClient) -> str:
    """Return the workspace (org) ID from the x-databricks-org-id response header.

    WorkspaceClient.get_workspace_id() can return a different ID on some
    workspaces, which silently breaks system-table filters.
    """
    import requests

    resp = requests.get(f"{w.config.host.rstrip('/')}/api/2.0/clusters/spark-versions",
                        headers=w.config.authenticate(), timeout=30)
    org = resp.headers.get("x-databricks-org-id")
    if org:
        return org
    m = re.search(r"adb-(\d+)\.", w.config.host)
    return m.group(1) if m else str(w.get_workspace_id())


ALLOW_SPARK = True  # set False when scanning a workspace other than the one this process runs in


def _active_spark():
    try:
        from pyspark.sql import SparkSession

        return SparkSession.getActiveSession()
    except Exception:
        return None


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _sql(w: WorkspaceClient, warehouse_id: str | None, statement: str, params: dict | None = None) -> list[dict]:
    """Run a read-only query; use the notebook's Spark session when there's no warehouse."""
    spark = _active_spark() if warehouse_id is None and ALLOW_SPARK else None
    if spark is not None:
        return [r.asDict() for r in spark.sql(statement, args=params or {}).collect()]
    if not warehouse_id:
        raise RuntimeError("a SQL warehouse is required here (--warehouse-id, or run in a notebook in this workspace)")
    from databricks.sdk.service.sql import StatementParameterListItem, StatementState

    resp = w.statement_execution.execute_statement(
        warehouse_id=warehouse_id,
        statement=statement,
        parameters=[StatementParameterListItem(name=k, value=str(v)) for k, v in (params or {}).items()],
        wait_timeout="50s",
    )
    while resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(3)
        resp = w.statement_execution.get_statement(resp.statement_id)
    if resp.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"Query failed: {resp.status.error.message if resp.status.error else resp.status.state}")
    cols = [c.name for c in resp.manifest.schema.columns]
    rows = [dict(zip(cols, r)) for r in (resp.result.data_array or [])]
    chunk = resp.result.next_chunk_index
    while chunk:
        part = w.statement_execution.get_statement_result_chunk_n(resp.statement_id, chunk)
        rows += [dict(zip(cols, r)) for r in (part.data_array or [])]
        chunk = part.next_chunk_index
    return rows


# ---------------------------------------------------------------------------
# 1. Inventory
# ---------------------------------------------------------------------------


SECRET_RE = re.compile(r"\{\{\s*secrets/([^/}]+)/([^}]+?)\s*\}\}")
SENSITIVE_KEY_RE = re.compile(r"(key|secret|token|password|credential)", re.I)


def _redact(obj):
    """Copy of a provider config with literal credential values replaced; secret references are kept."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(v, str) and SENSITIVE_KEY_RE.search(k) and not SECRET_RE.fullmatch(v.strip()):
                out[k] = "<redacted plaintext>"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    return obj


def _classify(endpoint: dict) -> tuple[str, list[dict]]:
    config = endpoint.get("config") or endpoint.get("pending_config") or {}
    entities = config.get("served_entities") or config.get("served_models") or []
    destinations, kinds = [], set()
    for e in entities:
        if e.get("external_model"):
            em = e["external_model"]
            provider_cfg = _redact({k: v for k, v in em.items() if k.endswith("_config")})
            destinations.append({
                "served_entity": e.get("name"),
                "type": "external_model",
                "provider": em.get("provider"),
                "model": em.get("name"),
                "task": em.get("task"),
                "provider_config": provider_cfg,
            })
            kinds.add("external_model")
        elif e.get("foundation_model"):
            fm = e["foundation_model"]
            destinations.append({"served_entity": e.get("name"), "type": "system_ppt",
                                 "model": fm.get("name") if isinstance(fm, dict) else fm})
            kinds.add("system_ppt")
        elif e.get("min_provisioned_throughput") is not None or e.get("max_provisioned_throughput") is not None \
                or e.get("provisioned_model_units") is not None:
            destinations.append({"served_entity": e.get("name"), "type": "provisioned_throughput",
                                 "model": e.get("entity_name"), "version": e.get("entity_version")})
            kinds.add("provisioned_throughput")
        else:
            destinations.append({"served_entity": e.get("name"), "type": "custom_model",
                                 "model": e.get("entity_name"), "version": e.get("entity_version")})
            kinds.add("custom_model")
    task = endpoint.get("task") or ""
    if "agent" in task.lower():
        return "agent", destinations
    if not kinds:
        # System pay-per-token endpoints may not expose served entities.
        if (endpoint.get("name") or "").startswith("databricks-"):
            return "system_ppt", [{"type": "system_ppt", "model": endpoint["name"]}]
        return "unknown", destinations
    if len(kinds) == 1:
        return kinds.pop(), destinations
    return "mixed:" + "+".join(sorted(kinds)), destinations


def inventory(w: WorkspaceClient) -> list[LegacyEndpoint]:
    summaries = _get(w, "/api/2.0/serving-endpoints").get("endpoints", [])
    _log(f"Found {len(summaries)} serving endpoints")
    out = []
    for s in summaries:
        name = s["name"]
        try:
            ep = _get(w, f"/api/2.0/serving-endpoints/{name}")
        except Exception as error:  # Some system endpoints can't be read in detail.
            _log(f"  could not read {name}: {error}")
            ep = s
        kind, destinations = _classify(ep)
        gw = ep.get("ai_gateway") or {}
        routes = ((ep.get("config") or {}).get("traffic_config") or {}).get("routes") or []
        can_query = []
        if ep.get("id") and kind not in ("system_ppt",):
            try:
                acl = _get(w, f"/api/2.0/permissions/serving-endpoints/{ep['id']}").get("access_control_list", [])
                for a in acl:
                    levels = {p.get("permission_level") for p in (a.get("all_permissions") or [])}
                    principal = a.get("user_name") or a.get("group_name") or a.get("service_principal_name")
                    if principal and levels & {"CAN_QUERY", "CAN_VIEW", "CAN_MANAGE"}:
                        can_query.append({
                            "principal": a.get("user_name") or a.get("group_name") or a.get("service_principal_name"),
                            "principal_type": "user" if a.get("user_name") else "group" if a.get("group_name") else "service_principal",
                            "levels": sorted(levels),
                        })
            except Exception as error:
                _log(f"  could not read permissions for {name}: {error}")
        out.append(LegacyEndpoint(
            name=name,
            endpoint_id=ep.get("id"),
            kind=kind,
            destinations=destinations,
            traffic_routes=routes,
            rate_limits=gw.get("rate_limits") or [],
            guardrails=gw.get("guardrails"),
            inference_table=gw.get("inference_table_config"),
            fallback_enabled=bool((gw.get("fallback_config") or {}).get("enabled")),
            usage_tracking=(gw.get("usage_tracking_config") or {}).get("enabled"),
            tags=ep.get("tags") or [],
            can_query=can_query,
            creator=ep.get("creator"),
            state=(ep.get("state") or {}).get("ready"),
        ))
    return out


def system_ai_map(w: WorkspaceClient) -> dict[str, str]:
    """Map legacy databricks-* names to system.ai model service names.

    Uses the PPT destination of each system.ai service (models/system.ai.<model>)
    rather than string rules, then falls back to name matching.
    """
    mapping: dict[str, str] = {}
    try:
        services = list(w.ai_gateway.list_model_services(parent="schemas/system.ai"))
    except Exception as error:
        _log(f"Could not list system.ai model services: {error}")
        return mapping
    _log(f"Found {len(services)} system.ai model services")
    for s in services:
        svc = s.name.removeprefix("model-services/")
        leaf = svc.split(".")[-1]
        candidates = {leaf, leaf.removeprefix("databricks-"), "databricks-" + leaf.removeprefix("databricks-")}
        cfg = s.config
        if cfg is None:
            try:
                cfg = w.ai_gateway.get_model_service(name=s.name).config
            except Exception:
                cfg = None
        for d in (cfg.routing.destinations if cfg and cfg.routing and cfg.routing.destinations else []):
            if d.pay_per_token_config and d.pay_per_token_config.model:
                model_leaf = d.pay_per_token_config.model.removeprefix("models/").split(".")[-1]
                candidates |= {model_leaf, "databricks-" + model_leaf.removeprefix("databricks-")}
        for c in candidates:
            mapping.setdefault(c, svc)
    return mapping


# ---------------------------------------------------------------------------
# 2. Traffic
# ---------------------------------------------------------------------------


def traffic(w: WorkspaceClient, warehouse_id: str | None, workspace_id: str, days: int) -> dict[str, dict]:
    rows = _sql(w, warehouse_id, f"""
        SELECT se.endpoint_name,
               count(*) AS requests,
               count(DISTINCT eu.requester) AS requesters,
               CAST(max(eu.request_time) AS STRING) AS last_request,
               sum(CASE WHEN eu.status_code = 429 THEN 1 ELSE 0 END) AS throttled
        FROM system.serving.endpoint_usage AS eu
        JOIN system.serving.served_entities AS se
          ON eu.served_entity_id = se.served_entity_id
        WHERE eu.workspace_id = :ws
          AND eu.request_time >= current_timestamp() - INTERVAL {int(days)} DAYS
        GROUP BY se.endpoint_name
    """, {"ws": workspace_id})
    return {r["endpoint_name"]: r for r in rows}


def traffic_by_requester(w: WorkspaceClient, warehouse_id: str | None, workspace_id: str, days: int) -> list[dict]:
    return _sql(w, warehouse_id, f"""
        SELECT se.endpoint_name, eu.requester, count(*) AS requests,
               CAST(max(eu.request_time) AS STRING) AS last_request
        FROM system.serving.endpoint_usage AS eu
        JOIN system.serving.served_entities AS se
          ON eu.served_entity_id = se.served_entity_id
        WHERE eu.workspace_id = :ws
          AND eu.request_time >= current_timestamp() - INTERVAL {int(days)} DAYS
        GROUP BY se.endpoint_name, eu.requester
        ORDER BY requests DESC
    """, {"ws": workspace_id})


# ---------------------------------------------------------------------------
# 3. Plan
# ---------------------------------------------------------------------------

WORKSPACE_LOCAL_GROUPS = {"admins", "users"}

V1_KEY_MAP = {
    "endpoint": "RATE_LIMIT_KEY_SERVICE",
    "user": "RATE_LIMIT_KEY_USER",  # becomes USER_DEFAULT when no principal
    "user_group": "RATE_LIMIT_KEY_USER_GROUP",
    "service_principal": "RATE_LIMIT_KEY_SERVICE_PRINCIPAL",
}


RENEWAL_MAP = {"minute": "RATE_LIMIT_RENEWAL_PERIOD_MINUTE", "hour": "RATE_LIMIT_RENEWAL_PERIOD_HOUR"}
BLOCKING_PREFIX = "BLOCKS APPLY: "  # needs_human entries that must stop automation


def _translate_rate_limits(limits: list[dict]) -> tuple[list[dict], list[str]]:
    out, issues = [], []
    for lim in limits:
        key = lim.get("key")
        target_key = V1_KEY_MAP.get(key)
        if key == "user" and not lim.get("principal"):
            target_key = "RATE_LIMIT_KEY_USER_DEFAULT"
        if not target_key:
            issues.append(f"rate limit with unknown key {key!r}")
            continue
        if key != "endpoint" and not lim.get("principal") and key != "user":
            issues.append(f"rate limit for {key} without a principal")
            continue
        period = RENEWAL_MAP.get((lim.get("renewal_period") or "minute").lower())
        if not period:
            issues.append(f"rate limit renewal period {lim.get('renewal_period')!r} has no Unity Gateway equivalent")
            continue
        out.append({k: v for k, v in {
            "key": target_key,
            "renewal_period": period,
            "principal": lim.get("principal"),
            "requests": lim.get("calls"),
            "tokens": lim.get("tokens"),
        }.items() if v is not None})
    return out, issues


def _guardrail_advice(g: dict) -> str:
    """Suggest Unity Gateway service policies for legacy guardrails (not 1:1)."""
    tips = []
    for side in ("input", "output"):
        cfg = g.get(side) if isinstance(g, dict) else None
        cfg = cfg if isinstance(cfg, dict) else {}
        if cfg.get("pii"):
            pii = cfg["pii"]
            behavior = pii.get("behavior", "") if isinstance(pii, dict) else ""
            tips.append(f"{side} PII{' ' + behavior if behavior else ''}: attach the Sensitive Data Detection service policy (Beta; blocks or redacts; set in the Unity Gateway UI)")
        if cfg.get("safety"):
            tips.append(f"{side} safety: built-in unsafe-content guardrail")
        if cfg.get("invalid_keywords") or cfg.get("valid_topics"):
            tips.append(f"{side} keywords/topics: custom service policy function")
    return "; ".join(tips) + ". Policies fail closed: test in log mode first" if tips else \
        "re-create as service policies (not 1:1)"


def _provider_key(dest: dict) -> str:
    """Group external-model destinations that can share one provider service."""
    cfg = json.dumps(dest.get("provider_config") or {}, sort_keys=True)
    return f"{dest.get('provider')}|{cfg}"


def check_targets(w: WorkspaceClient, rows: list[PlanRow]) -> None:
    """Record whether each proposed model service already exists (for example after apply)."""
    from databricks.sdk.errors import NotFound

    for r in rows:
        if not r.target_service:
            continue
        if r.target_service.startswith("system.ai."):
            r.target_status = "system"
            continue
        try:
            w.ai_gateway.get_model_service(name=f"model-services/{r.target_service}")
            r.target_status = "exists"
        except NotFound:
            r.target_status = "missing"
        except Exception:
            r.target_status = None


UC_NAME_MAX = 255


def _uc_name(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", (name or "endpoint").lower())[:UC_NAME_MAX]


def _unique(fqn: str, used: set[str], needs: list[str]) -> str:
    """Avoid two legacy endpoints mapping to the same Unity Catalog name (e.g. 'Proj-A' and 'proj_a')."""
    if fqn not in used:
        used.add(fqn)
        return fqn
    i = 2
    while f"{fqn}_{i}" in used:
        i += 1
    needs.append(f"target name {fqn} was already taken by another endpoint; using {fqn}_{i}")
    used.add(f"{fqn}_{i}")
    return f"{fqn}_{i}"


def _provider_name(dest: dict, secrets: list[str], pkey: str) -> str:
    """Stable provider service name from the provider and its credential, not from inventory order."""
    import hashlib

    prov = _uc_name(dest.get("provider") or "provider")
    basis = secrets[0] if secrets else pkey
    tag = _uc_name(basis.replace("/", "_"))[:40] if secrets else hashlib.sha1(pkey.encode()).hexdigest()[:8]
    return f"{prov}_{tag}"


def plan(endpoints: list[LegacyEndpoint], sys_map: dict[str, str], usage: dict[str, dict],
         target_catalog: str, target_schema: str, traffic_known: bool = True) -> tuple[list[PlanRow], list[dict]]:
    rows: list[PlanRow] = []
    providers: dict[str, dict] = {}
    used_targets: set[str] = set()
    used_providers: set[str] = set()
    for ep in endpoints:
        needs: list[str] = []
        u = usage.get(ep.name, {})
        base = dict(requests_window=int(u.get("requests") or 0), requesters=int(u.get("requesters") or 0),
                    last_request=u.get("last_request"))
        limits, limit_issues = _translate_rate_limits(ep.rate_limits)
        needs += [BLOCKING_PREFIX + i for i in limit_issues]
        if traffic_known and not base["requests_window"] and ep.kind != "system_ppt":
            needs.append("no traffic in the window: confirm with the owner and retire instead of migrating"
                         + (f" (state {ep.state})" if ep.state and ep.state != "READY" else ""))
        if ep.guardrails:
            needs.append("guardrails: " + _guardrail_advice(ep.guardrails))
        grants = []
        for g in ep.can_query:
            if not g.get("principal"):
                continue
            if g["principal_type"] == "group" and g["principal"] in WORKSPACE_LOCAL_GROUPS:
                continue  # workspace admins/users are not Unity Catalog principals
            privs = ["EXECUTE", "MANAGE"] if "CAN_MANAGE" in g["levels"] else ["EXECUTE"] \
                if "CAN_QUERY" in g["levels"] else []
            if privs:
                grants.append({"principal": g["principal"], "principal_type": g["principal_type"], "privileges": privs})
        if any(g["principal"] == "users" and "CAN_QUERY" in g["levels"] for g in ep.can_query):
            needs.append("legacy endpoint is open to all workspace users; choose an account-level group for EXECUTE")
        inference = None
        it = ep.inference_table or {}
        if it and it.get("enabled", True) and not (it.get("catalog_name") and it.get("schema_name")):
            needs.append("inference table without catalog/schema: configure logging on the new service by hand")
        elif it and it.get("enabled", True):
            inference = {
                "parent": f"schemas/{ep.inference_table.get('catalog_name')}.{ep.inference_table.get('schema_name')}",
                # The legacy endpoint already owns <prefix>_payload, so the new service needs its own prefix.
                "table_name_prefix": (ep.inference_table.get("table_name_prefix") or ep.name.replace("-", "_")) + "_ug",
                "note": "new table <prefix>_ug_payload; history stays in the legacy table",
            }

        if ep.kind == "system_ppt":
            target = sys_map.get(ep.name)
            if not target:
                needs.append("no matching system.ai model service found; check model availability")
            if ep.rate_limits or ep.guardrails or ep.inference_table:
                needs.append("legacy endpoint has gateway settings; system.ai services are shared across the "
                             "metastore, so use a wrapper service or group-scoped limits")
            rows.append(PlanRow(ep.name, ep.kind, "use_system_ai", target, None,
                                "PAY_PER_TOKEN_FOUNDATION_MODEL", limits, None, inference,
                                [], ep.tags, needs, **base))
            continue

        if ep.kind in ("custom_model", "unknown") or ep.kind.startswith("mixed"):
            rows.append(PlanRow(ep.name, ep.kind, "out_of_scope" if ep.kind == "custom_model" else "manual",
                                None, None, None, [], None, None, [], ep.tags,
                                ["custom ML model endpoints are not migrated" if ep.kind == "custom_model"
                                 else f"endpoint kind {ep.kind} needs review"], **base))
            continue

        if ep.kind == "agent":
            rows.append(PlanRow(ep.name, ep.kind, "manual", None, None, None, [], None, None, [], ep.tags,
                                ["agent endpoint: redeploy on Databricks Apps or rebuild; "
                                 "AI Search-backed agents break under Enforce"], **base))
            continue

        target = _unique(f"{target_catalog}.{target_schema}.{_uc_name(ep.name)}", used_targets, needs)
        route_pct = {r.get("served_model_name") or r.get("served_entity_name"): r.get("traffic_percentage")
                     for r in ep.traffic_routes}
        destinations, provider_names = [], []
        for d in ep.destinations:
            if d["type"] == "external_model":
                pkey = _provider_key(d)
                if pkey not in providers:
                    secrets = sorted({f"{a}/{b}" for a, b in SECRET_RE.findall(json.dumps(d.get("provider_config")))})
                    pname = _unique(f"{target_catalog}.{target_schema}.{_provider_name(d, secrets, pkey)}",
                                    used_providers, [])
                    providers[pkey] = {"provider_service": pname, "provider": d.get("provider"), "provider_key": pkey,
                                       "secrets": secrets, "models": set(), "legacy_endpoints": set()}
                providers[pkey]["models"].add(d.get("model"))
                providers[pkey]["legacy_endpoints"].add(ep.name)
                provider_names.append(providers[pkey]["provider_service"])
                destinations.append({"destination_type": "DESTINATION_TYPE_EXTERNAL_FOUNDATION_MODEL",
                                     "model_provider_service": providers[pkey]["provider_service"],
                                     "target_model": d.get("model"),
                                     "traffic_percentage": route_pct.get(d.get("served_entity"))})
            elif d["type"] == "provisioned_throughput":
                destinations.append({"destination_type": "DESTINATION_TYPE_PROVISIONED_THROUGHPUT_FOUNDATION_MODEL",
                                     "model_serving_endpoint": f"serving-endpoints/{ep.name}",
                                     "traffic_percentage": route_pct.get(d.get("served_entity"))})
        routing = {"destinations": destinations}
        if ep.fallback_enabled and len(destinations) > 1:
            routing["fallback"] = "enabled: destinations in order"
        rows.append(PlanRow(ep.name, ep.kind, "create_model_service", target,
                            ", ".join(sorted(set(provider_names))) or None,
                            destinations[0]["destination_type"] if destinations else None,
                            limits, routing, inference, grants, ep.tags, needs, **base))

    provider_list = [{**p, "models": sorted(m for m in p["models"] if m),
                      "legacy_endpoints": sorted(p["legacy_endpoints"])} for p in providers.values()]
    return rows, provider_list


# ---------------------------------------------------------------------------
# 4. Client reference scan
# ---------------------------------------------------------------------------

EMBEDDING_RE = re.compile(r"(gte|bge|e5|embedding|embed)", re.I)
# ai_query('name', ...) across lines, allowing SQL comments between "(" and the endpoint argument.
AI_QUERY_RE = re.compile(r"ai_query\s*\((?:\s|--[^\n]*\n|/\*.*?\*/)*(['\"])([A-Za-z0-9_.\-]+)\1", re.I | re.S)
# /serving-endpoints URLs; group 1 marks management APIs (/api/2.x/serving-endpoints), which aren't inference.
SERVING_URL_RE = re.compile(r"(/api/2\.\d)?/serving-endpoints(?:/([A-Za-z0-9_\-]+))?(/[A-Za-z0-9_\-/]+)?")
OPENAI_ROUTE_RE = re.compile(r"/serving-endpoints/(responses|chat/completions|embeddings|completions)\b")
MLFLOW_ENDPOINT_RE = re.compile(r"endpoints:/([A-Za-z0-9_\-]+)")
CHAT_DATABRICKS_START_RE = re.compile(r"ChatDatabricks\s*\(")
CHAT_DATABRICKS_ARG_RE = re.compile(r"\b(endpoint|model)\s*=\s*(['\"])([A-Za-z0-9_.\-]+)\2")
CONFIG_KEY_RE = re.compile(r"(endpoint|model|llm|embed|serving|chat|default|deployment)", re.I)
MAX_STORED_LINE = 1000
SECRET_VALUE_RES = [
    re.compile(r"(?<![A-Za-z0-9_\-])(sk-[A-Za-z0-9_\-]{8,}|dapi[0-9a-f]{16,}(-\d+)?|ghp_[A-Za-z0-9]{20,}"
               r"|xox[abp]-[A-Za-z0-9\-]{10,}|AKIA[0-9A-Z]{16})"),
    re.compile(r"(?i)(\b\w*(?:api[_-]?key|access[_-]?key|private[_-]?key|openai[_-]?key|secret|token|password|passwd|pwd"
               r"|credential|authorization)\w*['\"]?\s*[:=]\s*(?:f?['\"](?:Bearer\s+)?|Bearer\s+))"
               r"(?!\{\{)([^'\"\s{}]{6,})"),
]


def scrub(line: str | None) -> str | None:
    """Hide credential-looking values in a stored code line (keys, tokens, passwords)."""
    if not line:
        return line
    line = SECRET_VALUE_RES[1].sub(lambda m: m.group(1) + "<hidden>", line)
    return SECRET_VALUE_RES[0].sub("<hidden>", line)
MAX_FIX_LINE = 5000


def _balanced_args(text: str, open_paren: int) -> str:
    """Text between a '(' at open_paren and its matching ')' (or the rest of the text)."""
    depth, i = 0, open_paren
    while i < len(text):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren + 1:i]
        i += 1
    return text[open_paren + 1:]


def ipynb_cells(text: str) -> list[str] | None:
    """Source of each cell of a Jupyter notebook, or None if the text isn't one."""
    try:
        nb = json.loads(text)
    except Exception:
        return None
    if not isinstance(nb, dict) or not isinstance(nb.get("cells"), list):
        return None
    out = []
    for c in nb["cells"]:
        src = c.get("source", "") if isinstance(c, dict) else ""
        out.append("".join(src) if isinstance(src, list) else str(src))
    return out


class Scanner:
    def __init__(self, endpoint_names: Iterable[str], sys_map: dict[str, str], plan_rows: list[PlanRow]):
        self.names = {n for n in endpoint_names if n}
        self.sys_map = sys_map
        self.targets = {r.legacy_endpoint: r.target_service for r in plan_rows if r.target_service}
        alt = "|".join(sorted((re.escape(n) for n in self.names), key=len, reverse=True))
        # Quoted legacy endpoint names; longest first so similar names don't shadow each other.
        self.name_re = re.compile(r"(['\"])(" + alt + r")\1") if self.names else None
        # Unquoted config values (YAML / HCL / .env) under endpoint-like keys.
        self.config_re = re.compile(r"^(\s*-?\s*([\w.\-]+)\s*[:=]\s*)(" + alt + r")\s*(?:#.*)?$") if self.names else None
        self.refs: list[ClientReference] = []
        self.coverage: dict[str, str] = {}  # surface -> ok | failed: ... | truncated: ... | partial: ...

    def note(self, surface: str, status: str) -> None:
        """Record scan coverage for a surface. Problems are never overwritten by a later ok, and a failure is
        never downgraded to a partial result."""
        current = self.coverage.get(surface)
        if current is None or current == "ok" or (status != "ok" and not current.startswith("failed")):
            self.coverage[surface] = status

    def _target_for(self, name: str | None) -> str | None:
        if not name:
            return None
        return self.targets.get(name) or self.sys_map.get(name)

    def _ai_query_suggestion(self, name: str) -> str:
        target = self._target_for(name)
        if target and target.startswith("system.ai."):
            return (f"ai_query('{target}', ...); note ai_query on Unity Gateway applies usage tracking only "
                    "(no rate limits, fallbacks, inference tables or service policies)")
        if target:
            return (f"ai_query can't call custom model services yet; keep {name} until supported, "
                    "or use a system.ai model")
        if name.startswith("databricks-"):
            return f"{name} has no system.ai model service (likely retired); pick a current system.ai model"
        return "map to a system.ai model service"

    def scan_text(self, asset_type: str, asset: str, text: str) -> None:
        if asset.lower().endswith((".ipynb",)) or (text[:1] == "{" and '"cells"' in text[:4000]):
            cells = ipynb_cells(text)
            if cells is not None:
                for k, cell in enumerate(cells, start=1):
                    self._scan(asset_type, f"{asset} [cell {k}]", cell)
                return
        self._scan(asset_type, asset, text)

    def _scan(self, asset_type: str, asset: str, text: str) -> None:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")

        def line_of(pos: int) -> int:
            return text.count("\n", 0, pos) + 1

        # Calls that can span lines: record (line -> [(pattern, name, token)]).
        spanning: dict[int, list[tuple[str, str, str]]] = {}
        for m in AI_QUERY_RE.finditer(text):
            name = m.group(2)
            if name.startswith("system.ai.") or name.count(".") == 2:
                continue
            spanning.setdefault(line_of(m.start(2)), []).append(("ai_query", name, m.group(1) + name + m.group(1)))
        for m in CHAT_DATABRICKS_START_RE.finditer(text):
            args = _balanced_args(text, m.end() - 1)
            a = CHAT_DATABRICKS_ARG_RE.search(args)
            if a and a.group(3) in self.names:
                pos = m.end() + a.start(3)
                spanning.setdefault(line_of(pos), []).append(
                    ("ChatDatabricks", a.group(3), a.group(2) + a.group(3) + a.group(2)))

        in_endpoint_block = 0  # lines left inside a YAML "serving_endpoint:" mapping
        for i, line in enumerate(lines, start=1):
            self._line = line
            if re.match(r"^\s*-?\s*serving_endpoint\s*:\s*$", line):
                in_endpoint_block = 3
                continue
            if in_endpoint_block:
                in_endpoint_block -= 1
                m = re.match(r"^\s*name\s*:\s*['\"]?([A-Za-z0-9_\-]+)['\"]?\s*$", line)
                if m and m.group(1) in self.names:
                    target = self._target_for(m.group(1))
                    self._add(asset_type, asset, i, "bundle_serving_endpoint_resource", m.group(1), m.group(1),
                              f"app/bundle serving_endpoint resource: replace it, grant the app service principal "
                              f"EXECUTE on {target or '<model service>'} and update the app code to call /ai-gateway/")
                    in_endpoint_block = 0
                    continue
            hits = set()
            for pattern, name, token in spanning.get(i, []):
                if pattern == "ai_query":
                    self._add(asset_type, asset, i, "ai_query", token, name, self._ai_query_suggestion(name))
                else:
                    self._add(asset_type, asset, i, "ChatDatabricks", token, name,
                              "databricks-langchain>=0.19.0: model="
                              f"'{self._target_for(name) or '<model service>'}' (endpoint= is a deprecated alias) "
                              "and use_ai_gateway=True")
                hits.add(name)
            for m in MLFLOW_ENDPOINT_RE.finditer(line):
                name = m.group(1)
                if name not in self.names and not name.startswith("databricks-"):
                    continue
                target = self._target_for(name)
                self._add(asset_type, asset, i, "mlflow_endpoint_uri", m.group(0), name,
                          f"upgrade MLflow to 3.16+ and use databricks:/{target or 'system.ai.<model>'}")
                hits.add(name)
            for m in SERVING_URL_RE.finditer(line):
                name = m.group(2) if m.group(2) in self.names else None
                if m.group(1):
                    self._add(asset_type, asset, i, "serving_endpoints_management_api", m.group(0), name,
                              "management API on legacy serving endpoints (create/update/permissions): move this "
                              "automation to the Unity Gateway APIs or Terraform resources; not an inference call")
                else:
                    target = self._target_for(name)
                    self._add(asset_type, asset, i, "serving_endpoints_url", m.group(0), name,
                              "use <workspace-url>/ai-gateway/mlflow/v1 with model="
                              f"'{target or '<catalog>.<schema>.<service>'}' and an ai-gateway scoped token")
                if name:
                    hits.add(name)
            if self.config_re:
                m = self.config_re.match(line)
                if m and m.group(3) not in hits and CONFIG_KEY_RE.search(m.group(2)):
                    self._add(asset_type, asset, i, "config_value", m.group(3), m.group(3),
                              f"replace with {self._target_for(m.group(3)) or '<model service>'} "
                              "(config value; check what reads it)")
                    hits.add(m.group(3))
            if self.name_re:
                for m in self.name_re.finditer(line):
                    name = m.group(2)
                    if name in hits:
                        continue
                    self._add(asset_type, asset, i, "legacy_endpoint_name", m.group(0), name,
                              f"replace with '{self._target_for(name) or '<model service>'}' "
                              "(and move the client to /ai-gateway/)")
                    hits.add(name)

    def _add(self, asset_type, asset, line, pattern, match, legacy_endpoint, suggestion) -> None:
        if legacy_endpoint and EMBEDDING_RE.search(legacy_endpoint) and asset_type != "vector_search_index":
            suggestion += ("; embedding model: if this feeds an AI Search index, keep it until AI Search "
                           "accepts system.ai embeddings")
        line_text = getattr(self, "_line", None) if line else None
        fixed, confidence = (None, None)
        if line_text is not None and len(line_text) <= MAX_FIX_LINE:
            fixed, confidence = self._fix(pattern, match, legacy_endpoint, line_text)
        stored = scrub(line_text.strip()[:MAX_STORED_LINE]) if line_text else None
        if fixed is not None and scrub(fixed) != fixed:
            # The line holds a credential: don't publish a patch with the value hidden in it.
            fixed, confidence = None, None
            suggestion += "; this line contains a credential: edit it by hand (and move the credential to a secret)"
        self.refs.append(ClientReference(asset_type, asset, line, pattern, match, legacy_endpoint, suggestion,
                                         stored, fixed, confidence))

    @staticmethod
    def _replace_token(line: str, token: str, new: str, after: str | None = None) -> str | None:
        """Replace one exact occurrence of token (after a marker if given); None if not found."""
        start = line.find(after) if after else 0
        idx = line.find(token, max(start, 0))
        if idx < 0:
            idx = line.find(token)
        if idx < 0:
            return None
        return line[:idx] + new + line[idx + len(token):]

    def _fix(self, pattern: str, match: str, name: str | None, line: str) -> tuple[str | None, str | None]:
        """Propose a rewritten line. 'auto' rewrites are mechanical; 'review' need a human check."""
        target = self._target_for(name)
        quoted = lambda t: match[0] + t + match[-1]  # noqa: E731
        if pattern == "ai_query" and target and target.startswith("system.ai."):
            new = self._replace_token(line, match, quoted(target), after="ai_query")
            return (new.strip(), "auto") if new else (None, None)
        if pattern == "mlflow_endpoint_uri" and target:
            new = self._replace_token(line, match, f"databricks:/{target}")
            return (new.strip(), "auto") if new else (None, None)
        if pattern == "config_value" and target and self.config_re:
            m = self.config_re.match(line)
            if m:
                return (line[:m.start(3)] + target + line[m.end(3):]).strip(), "review"
        if pattern == "legacy_endpoint_name" and target:
            new = self._replace_token(line, match, quoted(target))
            return (new.strip(), "review") if new else (None, None)
        if pattern == "ChatDatabricks" and target:
            # databricks-langchain: `model` is the argument; `endpoint` is a deprecated alias.
            kw = re.search(r"\bendpoint(\s*=\s*)" + re.escape(match), line)
            new = (line[:kw.start()] + "model" + kw.group(1) + quoted(target) + line[kw.end():]) if kw \
                else self._replace_token(line, match, quoted(target))
            if new and "use_ai_gateway" not in new and "ChatDatabricks(" in new and new.rstrip().endswith(")"):
                new = new.rstrip()[:-1].rstrip().rstrip(",") + ", use_ai_gateway=True)"
            return (new.strip(), "review") if new else (None, None)
        if pattern == "serving_endpoints_url":
            if OPENAI_ROUTE_RE.search(match):
                return OPENAI_ROUTE_RE.sub(r"/ai-gateway/mlflow/v1/\1", line, count=1).strip(), "review"
            if name and target:
                if match.endswith(f"/{name}/invocations"):
                    new = line.replace(match, "/ai-gateway/mlflow/v1/chat/completions", 1)
                    return new.strip(), "review"  # the request body becomes OpenAI chat format with model=target
                if match == f"/serving-endpoints/{name}":
                    return line.replace(match, "/ai-gateway/mlflow/v1", 1).strip(), "review"
                return None, None
            if match == "/serving-endpoints":
                return line.replace(match, "/ai-gateway/mlflow/v1", 1).strip(), "review"
        return None, None


TOOLKIT_MARKERS = {"ug_migration_planner.py", "ug_migration_toolkit.marker"}


def _walk_workspace(w: WorkspaceClient, roots: list[str], max_objects: int, threads: int = 16) -> list[dict]:
    """List notebooks and files under the roots, one directory level at a time in parallel."""
    from concurrent.futures import ThreadPoolExecutor

    failures: list[str] = []

    def ls(path):
        try:
            return _get(w, "/api/2.0/workspace/list", {"path": path}).get("objects", [])
        except Exception as error:
            if "RESOURCE_DOES_NOT_EXIST" not in str(error) and "doesn't exist" not in str(error):
                failures.append(path)
            return []

    found, level, seen_dirs, skipped = [], list(dict.fromkeys(roots)), set(), []
    with ThreadPoolExecutor(max_workers=threads) as pool:
        while level and len(found) < max_objects:
            next_level = []
            for path, objects in zip(level, pool.map(ls, level)):
                # The toolkit's own install (its files mention legacy endpoint names on purpose): skip it.
                names = {o.get("path", "").rsplit("/", 1)[-1] for o in objects}
                if names & TOOLKIT_MARKERS:
                    skipped.append(path)
                    continue
                for o in objects:
                    t = o.get("object_type")
                    if t in ("DIRECTORY", "REPO") and o["path"] not in seen_dirs:
                        seen_dirs.add(o["path"])
                        next_level.append(o["path"])
                    elif t in ("NOTEBOOK", "FILE"):
                        found.append(o)
            level = next_level
    _walk_workspace.last_failures = failures
    if skipped:
        _log(f"  skipped the toolkit's own folders: {', '.join(skipped[:5])}")
    _walk_workspace.truncated = len(found) >= max_objects
    if _walk_workspace.truncated:
        _log(f"  stopped after {max_objects} workspace objects (raise --max-objects)")
    if failures:
        _log(f"  could not list {len(failures)} folders")
    return found[:max_objects]


def _decode(raw: bytes) -> str | None:
    """Decode text files, including UTF-16 with a BOM; None for binary content."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="ignore")
    if b"\x00" in raw[:4096]:
        return None
    return raw.decode("utf-8", errors="ignore")


def scan_workspace(w: WorkspaceClient, scanner: Scanner, roots: list[str], max_objects: int, threads: int = 16) -> None:
    """Export notebooks and text files in parallel and scan each distinct content once.

    Databricks Apps keep a copy of the source per deployment under
    /Workspace/Users/<sp>/src/<id>/, so identical files are reported once with
    a count of copies.
    """
    import hashlib
    from concurrent.futures import ThreadPoolExecutor

    exts = (".py", ".sql", ".scala", ".r", ".ipynb", ".yml", ".yaml", ".json", ".toml", ".js", ".ts", ".txt",
            ".md", ".sh", ".cfg", ".env")
    objs = [o for o in _walk_workspace(w, roots, max_objects, threads)
            if o["object_type"] == "NOTEBOOK" or o["path"].lower().endswith(exts)]

    if getattr(_walk_workspace, "truncated", False):
        scanner.note("workspace_files", f"truncated at {max_objects} objects")
    if getattr(_walk_workspace, "last_failures", None):
        scanner.note("workspace_files", f"partial: {len(_walk_workspace.last_failures)} folders unreadable")
    export_failures = []

    def export(o):
        fmt = "AUTO" if o["object_type"] == "FILE" else "SOURCE"
        try:
            data = _get(w, "/api/2.0/workspace/export", {"path": o["path"], "format": fmt}).get("content")
            return o, _decode(base64.b64decode(data or ""))
        except Exception:
            export_failures.append(o["path"])
            return o, None

    by_hash: dict[str, list[str]] = {}
    texts: dict[str, tuple[dict, str]] = {}
    with ThreadPoolExecutor(max_workers=threads) as pool:
        for o, text in pool.map(export, objs):
            if text is None:
                continue
            h = hashlib.sha1(text.encode()).hexdigest()
            by_hash.setdefault(h, []).append(o["path"])
            texts.setdefault(h, (o, text))
    for h, (o, text) in texts.items():
        copies = len(by_hash[h]) - 1
        label = o["path"] + (f" (+{copies} identical copies)" if copies else "")
        scanner.scan_text("notebook" if o["object_type"] == "NOTEBOOK" else "file", label, text)
    if export_failures:
        scanner.note("workspace_files", f"partial: {len(export_failures)} files unreadable")
    scanner.note("workspace_files", "ok")
    _log(f"  scanned {len(objs)} notebooks and files ({len(texts)} distinct)")


SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build", ".terraform",
             ".mypy_cache", ".pytest_cache", ".idea", ".vscode", "target", ".databricks"}
LOCAL_EXTS = (".py", ".sql", ".scala", ".r", ".ipynb", ".yml", ".yaml", ".json", ".toml", ".js", ".ts", ".tsx",
              ".jsx", ".java", ".go", ".cs", ".txt", ".sh", ".cfg", ".ini", ".env", ".tf", ".tfvars", ".hcl",
              ".properties", ".conf")


def scan_local(scanner: Scanner, paths: list[str], max_bytes: int = 2_000_000) -> None:
    """Scan local folders (cloned Git repos, bundle projects, Terraform) for legacy references.

    Skips dependency and build folders, binary files and files over max_bytes. Identical files
    are scanned once and reported with a copy count.
    """
    import hashlib

    by_hash: dict[str, list[str]] = {}
    texts: dict[str, tuple[str, str]] = {}
    files = 0
    for root_path in paths:
        root_path = os.path.abspath(os.path.expanduser(root_path))
        for root, dirs, names in os.walk(root_path):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for n in names:
                if not n.lower().endswith(LOCAL_EXTS) and n not in ("Dockerfile", "databricks.yml", ".env"):
                    continue
                path = os.path.join(root, n)
                try:
                    if os.path.getsize(path) > max_bytes:
                        continue
                    raw = open(path, "rb").read()
                except OSError:
                    continue
                text = _decode(raw)
                if text is None:
                    continue
                files += 1
                h = hashlib.sha1(raw).hexdigest()
                rel = os.path.relpath(path, os.path.dirname(root_path))
                by_hash.setdefault(h, []).append(rel)
                texts.setdefault(h, (rel, text))
    for h, (rel, text) in texts.items():
        copies = len(by_hash[h]) - 1
        scanner.scan_text("local_file", rel + (f" (+{copies} identical copies)" if copies else ""), text)
    scanner.note("local_files", "ok" if all(os.path.isdir(os.path.expanduser(p)) for p in paths)
                 else "failed: a --local-path folder doesn't exist")
    _log(f"  scanned {files} local files ({len(texts)} distinct) under {', '.join(paths)}")


def scan_agent_bricks(w: WorkspaceClient, scanner: Scanner) -> None:
    """Knowledge Assistants backed by AI Search indexes and Supervisor Agents that use them.

    Agent Bricks agents on AI Search break when Unity Gateway is enforced; file and volume
    sources keep working.
    """
    vs_kas: dict[str, str] = {}
    n_ka = n_sa = bad_ka = bad_sa = 0
    try:
        for ka in w.knowledge_assistants.list_knowledge_assistants():
            n_ka += 1
            try:
                sources = list(w.knowledge_assistants.list_knowledge_sources(parent=ka.name))
            except Exception:
                bad_ka += 1
                continue
            for src in sources:
                if src.index and src.index.index_name:
                    embed = None
                    try:
                        spec = w.vector_search_indexes.get_index(src.index.index_name).delta_sync_index_spec
                        cols = spec.embedding_source_columns if spec and spec.embedding_source_columns else []
                        embed = next((c.embedding_model_endpoint_name for c in cols if c.embedding_model_endpoint_name), None)
                    except Exception:
                        pass
                    vs_kas[ka.name] = ka.display_name or ka.name
                    scanner._add("knowledge_assistant", f"knowledge assistant {ka.display_name or ka.name}", None,
                                 "ka_vector_search_source", src.index.index_name, embed,
                                 f"source {src.index.index_name} is an AI Search index"
                                 + (f" embedded with {embed}" if embed else "")
                                 + ": breaks under Enforce; use a UC volume / files source or wait for AI Search "
                                   "support on Unity Gateway")
    except Exception as error:
        _log(f"  could not list Knowledge Assistants: {error}")
        scanner.note("knowledge_assistants", f"failed: {str(error)[:120]}")
    scanner.note("knowledge_assistants", f"partial: {bad_ka} unreadable" if bad_ka else "ok")
    try:
        for sa in w.supervisor_agents.list_supervisor_agents():
            n_sa += 1
            try:
                tools = list(w.supervisor_agents.list_tools(parent=sa.name))
            except Exception:
                bad_sa += 1
                continue
            for t in tools:
                ka_ref = t.knowledge_assistant
                ka_name = getattr(ka_ref, "knowledge_assistant_id", None) or getattr(ka_ref, "name", None) if ka_ref else None
                hit = next((v for k, v in vs_kas.items() if ka_name and (ka_name in k or k.endswith(str(ka_name)))), None)
                if hit:
                    scanner._add("supervisor_agent", f"supervisor agent {sa.display_name or sa.name}", None,
                                 "supervisor_uses_vs_ka", hit, None,
                                 f"tool {t.name} uses knowledge assistant {hit}, which is backed by AI Search")
    except Exception as error:
        _log(f"  could not list Supervisor Agents: {error}")
        scanner.note("supervisor_agents", f"failed: {str(error)[:120]}")
    scanner.note("supervisor_agents", f"partial: {bad_sa} unreadable" if bad_sa else "ok")
    _log(f"  scanned {n_ka} knowledge assistants and {n_sa} supervisor agents")


def scan_genie(w: WorkspaceClient, scanner: Scanner, threads: int = 16) -> None:
    """Genie Agent definitions (instructions, example SQL, functions) for legacy references."""
    from concurrent.futures import ThreadPoolExecutor

    try:
        spaces, token = [], None
        while True:
            resp = w.genie.list_spaces(page_token=token) if token else w.genie.list_spaces()
            spaces += resp.spaces or []
            token = resp.next_page_token
            if not token:
                break
    except Exception as error:
        _log(f"  could not list Genie Agents: {error}")
        scanner.note("genie_spaces", f"failed: {str(error)[:120]}")
        return

    def fetch(sp):
        try:
            return sp, w.genie.get_space(sp.space_id, include_serialized_space=True).serialized_space or ""
        except Exception:
            return sp, None

    bad = 0
    with ThreadPoolExecutor(max_workers=threads) as pool:
        for sp, text in pool.map(fetch, spaces):
            if text is None:
                bad += 1
            elif text:
                scanner.scan_text("genie_space", f"genie space {sp.space_id}: {sp.title}", text.replace("\\n", "\n"))
    scanner.note("genie_spaces", f"partial: {bad} unreadable" if bad else "ok")
    _log(f"  scanned {len(spaces)} Genie Agents")


def scan_custom_endpoints(w: WorkspaceClient, scanner: Scanner, endpoints: list[LegacyEndpoint]) -> None:
    """Environment variables of custom model endpoints (custom agents often name their LLM there)."""
    n = bad = 0
    for ep in endpoints:
        if ep.kind not in ("custom_model", "agent"):
            continue
        try:
            cfg = _get(w, f"/api/2.0/serving-endpoints/{ep.name}").get("config") or {}
        except Exception:
            bad += 1
            continue
        for ent in cfg.get("served_entities") or cfg.get("served_models") or []:
            env = ent.get("environment_vars") or {}
            if env:
                n += 1
                text = "\n".join(f"{k} = {v}" for k, v in env.items() if not SECRET_RE.search(str(v)))
                scanner.scan_text("serving_endpoint_env", f"endpoint {ep.name} ({ent.get('name')})", text)
    scanner.note("custom_endpoint_env", f"partial: {bad} endpoints unreadable" if bad else "ok")
    _log(f"  scanned environment variables of {n} custom served entities")


def scan_uc_sql(w: WorkspaceClient, scanner: Scanner, warehouse_id: str | None) -> None:
    """Unity Catalog SQL functions and views whose definitions call legacy endpoints."""
    queries = {
        "uc_function": "SELECT routine_catalog || '.' || routine_schema || '.' || routine_name AS name, "
                       "routine_definition AS body FROM system.information_schema.routines "
                       "WHERE routine_catalog <> 'system' AND (routine_definition ILIKE '%ai_query%' "
                       "OR routine_definition ILIKE '%serving-endpoints%' OR routine_definition ILIKE '%databricks-%')",
        "uc_view": "SELECT table_catalog || '.' || table_schema || '.' || table_name AS name, view_definition AS body "
                   "FROM system.information_schema.views WHERE table_catalog <> 'system' AND "
                   "(view_definition ILIKE '%ai_query%' OR view_definition ILIKE '%databricks-%')",
    }
    for kind, q in queries.items():
        try:
            rows = _sql(w, warehouse_id, q)
        except Exception as error:
            _log(f"  could not read {kind} definitions: {str(error)[:120]}")
            scanner.note(kind + "s", f"failed: {str(error)[:120]}")
            continue
        for r in rows:
            scanner.scan_text(kind, f"{kind.removeprefix('uc_')} {r['name']}", r.get("body") or "")
        scanner.note(kind + "s", "ok")
        _log(f"  scanned {len(rows)} candidate {kind.removeprefix('uc_')}s")


def scan_pipelines(w: WorkspaceClient, scanner: Scanner) -> None:
    """Lakeflow pipeline settings (configuration values often carry endpoint names)."""
    n = bad = 0
    try:
        for p in w.pipelines.list_pipelines():
            try:
                spec = w.pipelines.get(p.pipeline_id).spec
            except Exception:
                bad += 1
                continue
            n += 1
            scanner.scan_text("pipeline", f"pipeline {p.pipeline_id}: {p.name}",
                              json.dumps(spec.as_dict() if spec else {}, indent=1))
    except Exception as error:
        _log(f"  could not list pipelines: {error}")
        scanner.note("pipelines", f"failed: {str(error)[:120]}")
    scanner.note("pipelines", f"partial: {bad} unreadable" if bad else "ok")
    _log(f"  scanned {n} pipelines")


def scan_jobs(w: WorkspaceClient, scanner: Scanner) -> None:
    n = 0
    try:
        for job in w.jobs.list(expand_tasks=True):
            settings = job.settings.as_dict() if job.settings else {}
            n += 1
            scanner.scan_text("job", f"job {job.job_id}: {settings.get('name')}", json.dumps(settings, indent=1))
        scanner.note("jobs", "ok")
    except Exception as error:
        _log(f"  could not list jobs: {error}")
        scanner.note("jobs", f"failed: {str(error)[:120]}")
    _log(f"  scanned {n} jobs")


def scan_sql_queries(w: WorkspaceClient, scanner: Scanner, threads: int = 16) -> None:
    """Scan saved SQL queries. The list API redacts query_text, so each query is read by ID."""
    from concurrent.futures import ThreadPoolExecutor

    ids, token = [], None
    while True:
        try:
            page = _get(w, "/api/2.0/sql/queries", {"page_size": 100, **({"page_token": token} if token else {})})
        except Exception as error:
            _log(f"  could not list SQL queries: {error}")
            scanner.note("sql_queries", f"failed: {str(error)[:120]}")
            return
        ids += [(q.get("id"), q.get("display_name")) for q in page.get("results", [])]
        token = page.get("next_page_token")
        if not token:
            break

    failed = []

    def fetch(item):
        qid, name = item
        try:
            return qid, name, _get(w, f"/api/2.0/sql/queries/{qid}").get("query_text") or ""
        except Exception:
            failed.append(qid)
            return qid, name, ""

    with ThreadPoolExecutor(max_workers=threads) as pool:
        for qid, name, text in pool.map(fetch, ids):
            scanner.scan_text("sql_query", f"query {qid}: {name}", text)
    scanner.note("sql_queries", f"partial: {len(failed)} queries unreadable" if failed else "ok")
    _log(f"  scanned {len(ids)} SQL queries")


def scan_dashboards(w: WorkspaceClient, scanner: Scanner) -> None:
    n = bad = 0
    try:
        for d in w.lakeview.list():
            try:
                full = w.lakeview.get(d.dashboard_id)
            except Exception:
                bad += 1
                continue
            n += 1
            scanner.scan_text("dashboard", f"dashboard {d.dashboard_id}: {d.display_name}", full.serialized_dashboard or "")
    except Exception as error:
        _log(f"  could not list dashboards: {error}")
        scanner.note("dashboards", f"failed: {str(error)[:120]}")
    scanner.note("dashboards", f"partial: {bad} unreadable" if bad else "ok")
    _log(f"  scanned {n} dashboards")


def scan_apps(w: WorkspaceClient, scanner: Scanner) -> None:
    n = 0
    try:
        for app in w.apps.list():
            n += 1
            for r in app.resources or []:
                ep = r.serving_endpoint
                if ep and ep.name:
                    target = scanner._target_for(ep.name)
                    sp = app.service_principal_name or app.service_principal_client_id or "the app service principal"
                    scanner._add("app", f"app {app.name}", None, "app_serving_endpoint_resource", ep.name, ep.name,
                                 f"grant {sp} EXECUTE on {target or '<model service>'}, replace the serving "
                                 "endpoint resource and update the app code to call /ai-gateway/")
    except Exception as error:
        _log(f"  could not list apps: {error}")
        scanner.note("apps", f"failed: {str(error)[:120]}")
    _log(f"  scanned {n} apps")


def scan_vector_search(w: WorkspaceClient, scanner: Scanner) -> None:
    n = bad = 0
    try:
        for ep in w.vector_search_endpoints.list_endpoints():
            for idx in w.vector_search_indexes.list_indexes(endpoint_name=ep.name):
                n += 1
                try:
                    full = w.vector_search_indexes.get_index(idx.name)
                except Exception:
                    bad += 1
                    continue
                spec = full.delta_sync_index_spec
                for col in (spec.embedding_source_columns if spec and spec.embedding_source_columns else []):
                    name = col.embedding_model_endpoint_name
                    if name and not name.startswith("system.ai."):
                        scanner._add("vector_search_index", f"index {idx.name}", None, "embedding_endpoint", name,
                                     name, "re-create the index on a system.ai embedding service once AI "
                                           "Search accepts it (re-embeds the source; expected around mid-November "
                                           "2026 as of October 30, 2026, not confirmed). Until then don't enforce or rate-limit this endpoint to 0. If you "
                                           "must enforce now: switch to self-managed embeddings computed with "
                                           "ai_query('system.ai.<embedding model>', ...) and query with query_vector")
    except Exception as error:
        _log(f"  could not list AI Search indexes: {error}")
        scanner.note("vector_search", f"failed: {str(error)[:120]}")
    scanner.note("vector_search", f"partial: {bad} unreadable" if bad else "ok")
    _log(f"  scanned {n} AI Search indexes")


def annotate_dependencies(rows: list[PlanRow], refs: list[ClientReference]) -> None:
    """Mark endpoints that AI Search indexes or apps depend on, so they aren't enforced early."""
    by_ep: dict[str, list[ClientReference]] = {}
    for r in refs:
        if r.legacy_endpoint and r.asset_type in ("vector_search_index", "app", "knowledge_assistant"):
            by_ep.setdefault(r.legacy_endpoint, []).append(r)
    for row in rows:
        deps = by_ep.get(row.legacy_endpoint, [])
        indexes = [d.asset.removeprefix("index ") for d in deps if d.asset_type in ("vector_search_index", "knowledge_assistant")]
        apps = [d.asset.removeprefix("app ") for d in deps if d.asset_type == "app"]
        if indexes:
            row.needs_human.append(f"embedding model for {len(indexes)} AI Search index(es) "
                                   f"({', '.join(indexes[:3])}): blocks Enforce until re-indexed")
        if apps:
            row.needs_human.append(f"app resource in {', '.join(apps[:3])}: update the app before Enforce")


# ---------------------------------------------------------------------------
# 5. Callers: link traffic requesters to code references
# ---------------------------------------------------------------------------


def resolve_requesters(w: WorkspaceClient, requesters: Iterable[str]) -> dict[str, str]:
    """Best-effort display names for service principal application IDs."""
    names = {}
    uuid = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    for r in set(requesters):
        if not r or not uuid.match(r):
            continue
        try:
            sps = list(w.service_principals.list(filter=f'applicationId eq "{r}"'))
            if sps:
                names[r] = sps[0].display_name or r
        except Exception:
            pass
    return names


def link_callers(by_req: list[dict], refs: list[ClientReference], names: dict[str, str]) -> list[dict]:
    """For each requester, list code references that are probably theirs.

    A reference is linked when the asset path contains the requester (user
    email or service principal ID, e.g. an app's source folder) and it names
    the same legacy endpoint, or names none.
    """
    out = []
    for r in by_req:
        who, ep = r.get("requester") or "", r.get("endpoint_name")
        seg = re.compile(r"(^|/)" + re.escape(who) + r"(/|$|\s)") if who else None
        linked = sorted({f"{x.asset}" + (f":{x.line}" if x.line else "") for x in refs
                         if seg and seg.search(x.asset) and x.legacy_endpoint in (ep, None)})
        out.append({"endpoint_name": ep, "requester": who, "requester_name": names.get(who, who),
                    "requests": r.get("requests"), "last_request": r.get("last_request"),
                    "linked_code": linked[:20], "linked_count": len(linked)})
    return out


# ---------------------------------------------------------------------------
# 6. Enforce readiness
# ---------------------------------------------------------------------------


def _gateway_body(ep: LegacyEndpoint) -> dict:
    """The endpoint's current AI Gateway config, as PUT /ai-gateway expects it (for undo)."""
    body = {}
    if ep.usage_tracking is not None:
        body["usage_tracking_config"] = {"enabled": bool(ep.usage_tracking)}
    if ep.rate_limits:
        body["rate_limits"] = ep.rate_limits
    if ep.guardrails:
        body["guardrails"] = ep.guardrails
    if ep.inference_table:
        body["inference_table_config"] = ep.inference_table
    if ep.fallback_enabled:
        body["fallback_config"] = {"enabled": True}
    return body


def readiness(rows: list[PlanRow], refs: list[ClientReference], traffic_ok: bool, days: int,
              endpoints: list[LegacyEndpoint] | None = None, coverage: dict[str, str] | None = None,
              scanned: bool = True) -> dict:
    """Decide whether Enforce Unity Gateway can be turned on, and list what blocks it.

    Blockers break traffic or dependencies when enforced. Warnings are code references that will break
    if they still run. The scan coverage must be complete for READY. Close candidates are external
    model endpoints with no traffic, no dependents and no references in a complete scan; PT endpoints
    are never candidates because their Unity Gateway wrappers route through them.
    """
    blockers, warnings = [], []
    for r in rows:
        if r.requests_window and r.action != "out_of_scope":
            detail = (f"{r.requests_window} requests from {r.requesters} callers in {days} days, last "
                      f"{r.last_request}; move callers to {r.target_service or 'a model service'}")
            if r.kind in ("external_model", "provisioned_throughput"):
                # Enforce leaves existing external model and PT endpoints queryable; they retire with v1.
                warnings.append({"type": "legacy_traffic_kept_after_enforce", "item": r.legacy_endpoint,
                                 "detail": detail + " (keeps working after Enforce; migrate before v1 retires)"})
            else:
                blockers.append({"type": "legacy_traffic", "item": r.legacy_endpoint, "detail": detail})
        if r.kind == "agent":
            blockers.append({"type": "agent", "item": r.legacy_endpoint, "detail": "; ".join(r.needs_human)})
    for x in refs:
        if x.asset_type == "vector_search_index":
            blockers.append({"type": "vector_search", "item": x.asset.removeprefix("index "),
                             "detail": f"embeds with {x.legacy_endpoint}; re-index before enforcing"})
        elif x.asset_type in ("knowledge_assistant", "supervisor_agent"):
            blockers.append({"type": "agent_bricks_vector_search", "item": x.asset, "detail": x.suggestion})
        elif x.asset_type == "app" or x.pattern == "bundle_serving_endpoint_resource":
            blockers.append({"type": "app_resource", "item": x.asset.removeprefix("app "),
                             "detail": f"serving endpoint resource {x.legacy_endpoint}"})
        elif x.pattern == "ai_query" and "can't call custom" in x.suggestion:
            blockers.append({"type": "ai_query_custom", "item": x.asset,
                             "detail": f"ai_query on {x.legacy_endpoint} has no Unity Gateway target yet"})
        else:
            warnings.append({"type": x.pattern, "item": f"{x.asset}" + (f":{x.line}" if x.line else ""),
                             "detail": x.legacy_endpoint or x.match})
    gaps = {k: v for k, v in (coverage or {}).items() if v != "ok"}
    if not traffic_ok:
        # A permissions or data problem, not something Enforce would break: readiness can't be decided yet.
        gaps["traffic"] = "not confirmed: system tables couldn't be read or have no rows for this workspace"
    if not scanned:
        gaps["code_scan"] = "skipped"
    referenced = {x.legacy_endpoint for x in refs if x.legacy_endpoint}
    by_name = {e.name: e for e in endpoints or []}
    candidates = []
    if traffic_ok and not gaps:
        for r in rows:
            ep = by_name.get(r.legacy_endpoint)
            if r.action != "create_model_service" or r.kind != "external_model" or r.requests_window \
                    or r.legacy_endpoint in referenced or ep is None:
                continue
            original = _gateway_body(ep)
            close = dict(original)
            close["rate_limits"] = [l for l in ep.rate_limits if l.get("key") != "endpoint"] + \
                [{"key": "endpoint", "calls": 0, "renewal_period": "minute"}]
            candidates.append({"endpoint": r.legacy_endpoint, "target_ready": r.target_status == "exists",
                               "ai_gateway_body": close, "undo_body": original})
    if blockers:
        status = "BLOCKED"
    elif gaps:
        status = "INCOMPLETE"
    else:
        status = "READY_WITH_WARNINGS" if warnings else "READY"
    return {"status": status, "blockers": blockers, "warnings": warnings, "coverage_gaps": gaps,
            "coverage": coverage or {}, "rate_limit_zero_candidates": candidates}


def readiness_md(ws_url: str, r: dict, days: int) -> str:
    from collections import Counter
    lines = ["# Enforce Unity Gateway readiness", "", f"Workspace: {ws_url}",
             f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} (traffic window {days} days) "
             f"by unity-gateway-migration-toolkit {__version__}", "", f"> {DISCLAIMER}", "",
             f"**Status: {r['status']}**", ""]
    if r["blockers"]:
        lines += ["## Blockers", "", "| Type | Count |", "|---|---|",
                  *[f"| {k} | {v} |" for k, v in Counter(b["type"] for b in r["blockers"]).most_common()], ""]
        lines += [f"- **{b['type']}** {b['item']}: {b['detail']}" for b in r["blockers"][:60]] + [""]
    if r["warnings"]:
        lines += ["## Warnings (code that will break if it still runs)", "",
                  "| Type | Count |", "|---|---|",
                  *[f"| {k} | {v} |" for k, v in Counter(w["type"] for w in r["warnings"]).most_common()], "",
                  "Details in client_references.csv and CODE_FIXES.md.", ""]
    if r.get("coverage_gaps"):
        lines += ["## Incomplete scan", "", "These surfaces weren't fully scanned, so readiness and close "
                  "suggestions can't be trusted until they are:", "", "| Surface | Status |", "|---|---|",
                  *[f"| {k} | {v} |" for k, v in sorted(r["coverage_gaps"].items())], ""]
    if r["rate_limit_zero_candidates"]:
        lines += ["## Can be closed now (external model endpoints with no traffic, no dependents, no references)", "",
                  "Setting the endpoint rate limit to 0 stops calls without deleting anything. The command keeps the "
                  "endpoint's other rate limits and settings; the undo command restores the current config. "
                  "Usage data covers only the traffic window: confirm with the owner first.", "",
                  "| Endpoint | Unity Gateway target exists |", "|---|---|",
                  *[f"| {c['endpoint']} | {'yes' if c['target_ready'] else 'no: run apply first'} |"
                    for c in r["rate_limit_zero_candidates"]], "", "```bash"]
        import shlex
        for c in r["rate_limit_zero_candidates"]:
            path = f"/api/2.0/serving-endpoints/{c['endpoint']}/ai-gateway"
            lines.append(f"# close {c['endpoint']}")
            lines.append(f"databricks api put {shlex.quote(path)} --json {shlex.quote(json.dumps(c['ai_gateway_body']))}")
            lines.append(f"# undo {c['endpoint']}")
            lines.append(f"databricks api put {shlex.quote(path)} --json {shlex.quote(json.dumps(c['undo_body']))}")
        lines += ["```", ""]
    lines += ["## When it's READY", "",
              "Workspace admin: Settings > Advanced > **Enforce Unity Gateway**. Calls to legacy `databricks-*` "
              "pay-per-token endpoints then fail with PERMISSION_DENIED, and new external model and PT endpoints "
              "can only be created through Unity Gateway. Existing external model and PT endpoints stay queryable "
              "until they retire, so migrate their callers too.", ""]
    return "\n".join(lines) + "\n"


def code_fixes_md(refs: list[ClientReference]) -> str:
    """Proposed line changes grouped by asset, as a reviewable pseudo-diff."""
    by_asset: dict[str, list[ClientReference]] = {}
    for r in refs:
        if r.fixed_line and r.fixed_line != r.line_text:
            by_asset.setdefault(r.asset, []).append(r)
    auto = sum(1 for v in by_asset.values() for r in v if r.fix_confidence == "auto")
    review = sum(1 for v in by_asset.values() for r in v if r.fix_confidence == "review")
    lines = ["# Proposed code fixes", "", f"> {DISCLAIMER}", "",
             f"{auto} mechanical (`auto`) and {review} to review (`review`) across {len(by_asset)} assets. "
             "Nothing was changed: apply these in the source (and its Git repo if there is one), then re-run.", ""]
    for asset, items in sorted(by_asset.items()):
        lines += [f"## {asset}", "", "```diff"]
        for r in sorted(items, key=lambda r: r.line or 0):
            lines += [f"@@ line {r.line} ({r.fix_confidence}) @@", f"- {r.line_text}", f"+ {r.fixed_line}"]
        lines += ["```", ""]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 7. Output
# ---------------------------------------------------------------------------


def _write_csv(path: str, rows: list[dict]) -> None:
    if not rows:
        open(path, "w").close()
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=keys)
        wr.writeheader()
        for r in rows:
            wr.writerow({k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in r.items()})


def summary_md(ws_url: str, endpoints: list[LegacyEndpoint], rows: list[PlanRow], providers: list[dict],
               refs: list[ClientReference], days: int, traffic_ok: bool, callers: list[dict] | None = None) -> str:
    from collections import Counter
    kinds = Counter(e.kind for e in endpoints)
    actions = Counter(r.action for r in rows)
    active = [r for r in rows if r.requests_window > 0]
    by_pattern = Counter(r.pattern for r in refs)
    lines = [
        "# Unity Gateway migration plan (prototype, read-only)",
        "",
        f"Workspace: {ws_url}",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} by unity-gateway-migration-toolkit {__version__}",
        "",
        f"> {DISCLAIMER}",
        "",
        "## Endpoints",
        "",
        "| Kind | Count |", "|---|---|",
        *[f"| {k} | {v} |" for k, v in kinds.most_common()],
        "",
        "| Plan action | Count |", "|---|---|",
        *[f"| {k} | {v} |" for k, v in actions.most_common()],
        "",
        (f"{len(active)} endpoint{'' if len(active) == 1 else 's'} had traffic in the last {days} days." if traffic_ok
         else "Traffic not available (system.serving tables need account admin access or a warehouse)."),
        "",
    ]
    if active:
        lines += ["| Endpoint | Kind | Requests | Requesters | Last request | Target |", "|---|---|---|---|---|---|"]
        for r in sorted(active, key=lambda r: -r.requests_window)[:25]:
            lines.append(f"| {r.legacy_endpoint} | {r.kind} | {r.requests_window} | {r.requesters} | "
                         f"{r.last_request} | {r.target_service or '-'} |")
        lines.append("")
    if callers:
        lines += ["## Who calls legacy endpoints", "", "| Endpoint | Caller | Requests | Last request | Code found |",
                  "|---|---|---|---|---|"]
        for c in sorted(callers, key=lambda c: -int(c["requests"] or 0))[:30]:
            code = "; ".join(c["linked_code"][:2]) + (f" (+{c['linked_count'] - 2})" if c["linked_count"] > 2 else "")
            lines.append(f"| {c['endpoint_name']} | {c['requester_name']} | {c['requests']} | {c['last_request']} | "
                         f"{code or 'not found: check jobs, external apps or local code'} |")
        lines.append("")
    if providers:
        lines += ["## Provider services to create", "", "| Provider service | Provider | Models | Legacy endpoints | Secrets |",
                  "|---|---|---|---|---|"]
        for p in providers:
            lines.append(f"| {p['provider_service']} | {p['provider']} | {', '.join(p['models'])} | "
                         f"{len(p['legacy_endpoints'])} | {', '.join(p['secrets']) or '-'} |")
        lines.append("")
    human = [r for r in rows if r.needs_human]
    if human:
        lines += ["## Needs a human", ""]
        for r in human[:50]:
            lines.append(f"- **{r.legacy_endpoint}** ({r.kind}): " + "; ".join(r.needs_human))
        lines.append("")
    lines += ["## Client references", "", "| Pattern | Count |", "|---|---|",
              *[f"| {k} | {v} |" for k, v in by_pattern.most_common()], ""]
    for r in refs[:40]:
        loc = f"{r.asset}" + (f":{r.line}" if r.line else "")
        lines.append(f"- `{r.match[:80]}` in {loc} ({r.asset_type}): {r.suggestion}")
    if len(refs) > 40:
        lines.append(f"- ... {len(refs) - 40} more in client_references.csv")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def run(w: WorkspaceClient, out_dir: str, warehouse_id: str | None = None, days: int = 30,
        target_catalog: str = "ai_gateway", target_schema: str = "migrated",
        scan_roots: list[str] | None = None, max_objects: int = 20000, skip_scan: bool = False,
        workspace_id: str | None = None, threads: int = 16, local_paths: list[str] | None = None,
        allow_spark: bool = True) -> dict:
    global ALLOW_SPARK
    previous, ALLOW_SPARK = ALLOW_SPARK, allow_spark
    try:
        return _run(w, out_dir, warehouse_id, days, target_catalog, target_schema, scan_roots, max_objects,
                    skip_scan, workspace_id, threads, local_paths)
    finally:
        ALLOW_SPARK = previous


def _run(w, out_dir, warehouse_id, days, target_catalog, target_schema, scan_roots, max_objects, skip_scan,
         workspace_id, threads, local_paths) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    ws_url = w.config.host
    workspace_id = workspace_id or workspace_id_of(w)
    _log(f"Workspace {ws_url} ({workspace_id})")

    _log("1. Inventory")
    endpoints = inventory(w)
    sys_map = system_ai_map(w)

    _log("2. Traffic")
    usage, by_req, traffic_ok, traffic_status = {}, [], True, "ok"
    try:
        usage = traffic(w, warehouse_id, workspace_id, days)
        by_req = traffic_by_requester(w, warehouse_id, workspace_id, days)
        known = _sql(w, warehouse_id, "SELECT count(*) AS n FROM system.serving.served_entities "
                                      "WHERE workspace_id = :ws", {"ws": workspace_id})
        if endpoints and not int((known[0] or {}).get("n") or 0):
            traffic_ok = False
            traffic_status = (f"system.serving.served_entities has no rows for workspace {workspace_id} although "
                              f"{len(endpoints)} endpoints exist: wrong workspace ID or no access to the system tables")
        _log(f"  {len(usage)} endpoints with traffic in {days} days")
    except Exception as error:
        traffic_ok = False
        traffic_status = f"failed: {str(error)[:200]}"
    if not traffic_ok:
        _log(f"  traffic not confirmed: {traffic_status}")

    _log("3. Plan")
    rows, providers = plan(endpoints, sys_map, usage, target_catalog, target_schema, traffic_ok)
    check_targets(w, rows)

    refs: list[ClientReference] = []
    coverage: dict[str, str] = {}
    if not skip_scan:
        _log("4. Client reference scan")
        scanner = Scanner((e.name for e in endpoints), sys_map, rows)
        scan_workspace(w, scanner, scan_roots or ["/Users", "/Shared", "/Repos"], max_objects, threads)
        scan_jobs(w, scanner)
        scan_sql_queries(w, scanner, threads)
        scan_dashboards(w, scanner)
        scan_apps(w, scanner)
        scan_vector_search(w, scanner)
        scan_agent_bricks(w, scanner)
        scan_genie(w, scanner, threads)
        scan_custom_endpoints(w, scanner, endpoints)
        scan_uc_sql(w, scanner, warehouse_id)
        scan_pipelines(w, scanner)
        if local_paths:
            scan_local(scanner, local_paths)
        refs = scanner.refs
        coverage = scanner.coverage
        annotate_dependencies(rows, refs)

    _write_csv(os.path.join(out_dir, "legacy_endpoints.csv"), [asdict(e) for e in endpoints])
    _write_csv(os.path.join(out_dir, "migration_plan.csv"), [asdict(r) for r in rows])
    _write_csv(os.path.join(out_dir, "provider_services.csv"),
               [{k: v for k, v in p.items() if k != "provider_key"} for p in providers])
    _write_csv(os.path.join(out_dir, "client_references.csv"), [asdict(r) for r in refs])
    callers = link_callers(by_req, refs, resolve_requesters(w, (r.get("requester") for r in by_req)))
    _write_csv(os.path.join(out_dir, "callers.csv"), callers)
    with open(os.path.join(out_dir, "system_ai_map.json"), "w") as f:
        json.dump(sys_map, f, indent=1, sort_keys=True)
    ready = readiness(rows, refs, traffic_ok, days, endpoints, coverage, scanned=not skip_scan)
    ready["traffic_status"] = traffic_status
    ready["workspace_id"] = workspace_id
    with open(os.path.join(out_dir, "READINESS.md"), "w") as f:
        f.write(readiness_md(ws_url, ready, days))
    with open(os.path.join(out_dir, "readiness.json"), "w") as f:
        json.dump(ready, f, indent=1)
    with open(os.path.join(out_dir, "CODE_FIXES.md"), "w") as f:
        f.write(code_fixes_md(refs))
    with open(os.path.join(out_dir, "SUMMARY.md"), "w") as f:
        f.write(summary_md(ws_url, endpoints, rows, providers, refs, days, traffic_ok, callers))
    _log(f"Done. Results in {out_dir}")
    return {"version": __version__, "endpoints": len(endpoints), "plan_rows": len(rows), "providers": len(providers),
            "client_references": len(refs), "traffic_ok": traffic_ok, "readiness": ready["status"]}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--profile", help="Databricks CLI profile")
    p.add_argument("--warehouse-id", help="SQL warehouse for system table queries")
    p.add_argument("--out", default="./ug_migration_out", help='Output folder (default ./ug_migration_out)')
    p.add_argument("--days", type=int, default=30, help='Traffic window in days (default 30)')
    p.add_argument("--target-catalog", default="ai_gateway", help='Catalog the plan targets for new model services (default ai_gateway)')
    p.add_argument("--target-schema", default="migrated", help='Schema the plan targets for new model services (default migrated)')
    p.add_argument("--scan-root", action="append", help="Workspace path to scan (repeatable)")
    p.add_argument("--max-objects", type=int, default=20000, help='Stop listing workspace files after this many (default 20000)')
    p.add_argument("--workspace-id", help="Override the detected workspace ID")
    p.add_argument("--threads", type=int, default=16, help='Parallel API calls for the code scan (default 16)')
    p.add_argument("--local-path", action="append", help="Also scan this local folder, e.g. a cloned repo (repeatable)")
    p.add_argument("--skip-scan", action="store_true", help='Skip the code scan (inventory, traffic and plan only)')
    a = p.parse_args(argv)
    w = WorkspaceClient(profile=a.profile) if a.profile else WorkspaceClient()
    result = run(w, a.out, a.warehouse_id, a.days, a.target_catalog, a.target_schema,
                 a.scan_root, a.max_objects, a.skip_scan, a.workspace_id, a.threads, a.local_path)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
