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
import bisect
import csv
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urlsplit

from databricks.sdk import WorkspaceClient

__version__ = "0.10.3"
DISCLAIMER = ("Prototype from Databricks Shared Technical Services, provided as is. It only reads unless you run apply or "
              "rollback, or snapshots; review results before acting.")


def validate_deadline(value: str) -> str:
    """The retirement date must be an ISO date (YYYY-MM-DD)."""
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise ValueError(f"deadline must be an ISO date such as 2027-03-30, not {value!r}") from None
    return value


# One retirement date for every legacy endpoint (v1 and v2: pay-per-token, embeddings, PT, external). Custom model
# and feature serving endpoints are not affected. Set UGMIG_DEADLINE or pass --deadline to change it.
LEGACY_DEADLINE = validate_deadline(os.environ.get("UGMIG_DEADLINE", "2027-03-30"))
DEADLINE_AS_OF = "confirmed as of 2026-11-01"
V1_SOURCE = "Model Serving (v1)"
V2_SOURCE = "AI Gateway v2 (workspace-bound)"


def deadline_text() -> str:
    """The retirement date in words, for people: 'March 30, 2027'."""
    d = datetime.strptime(LEGACY_DEADLINE, "%Y-%m-%d")
    return f"{d:%B} {d.day}, {d.year}"


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass
class LegacyEndpoint:
    name: str
    endpoint_id: str | None
    kind: str  # system_ppt | external_model | provisioned_throughput | custom_model | agent | unknown | v2_workspace_endpoint
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
    auto_capture: dict | None = None  # deprecated config.auto_capture_config (legacy inference tables)
    route_optimized: bool = False
    endpoint_url: str | None = None  # invocation URL of a route-optimized endpoint
    budget_policy_id: str | None = None  # explicitly set, not the workspace default
    usage_policy_id: str | None = None
    gateway_settings: list[str] = field(default_factory=list)  # ai_gateway blocks that are set, e.g. rate_limits
    source: str = V1_SOURCE  # where the endpoint lives: serving endpoint (v1) or workspace-bound AI Gateway v2


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
    provider_status: str | None = None  # automated | manual_supported | no_ug_provider | unknown_provider
    v2_requests: int = 0  # part of requests_window that came from AI Gateway v2 (retires with all legacy endpoints)
    api_types: list[str] = field(default_factory=list)  # v2 routes seen in the window, e.g. mlflow/v1/chat/completions
    tokens_window: int = 0  # input + output tokens in the window (v1 and v2); shown, not used for decisions
    v2_tokens: int = 0  # part of tokens_window from AI Gateway v2 (total_tokens)
    v2_failed: int = 0  # v2 requests with no status, or status 0 or 501 (see V2_CALLER_SQL)
    v2_status_501: int = 0  # v2 requests answered with HTTP 501: v2 is off for this workspace
    target_api_types: list[str] = field(default_factory=list)  # supported_api_types of the target model service


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
    fix_confidence: str | None = None  # review | None (every proposed line change needs a human check)
    also_in: list[str] = field(default_factory=list)  # other identical copies (same content, other paths)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get(w: WorkspaceClient, path: str, query: dict | None = None) -> dict:
    return w.api_client.do("GET", path, query=query or {})


ENFORCE_SETTING = "enforce_ai_gateway_v3_only"


def enforce_status(w: WorkspaceClient) -> str:
    """The workspace's Enforce Unity Gateway setting: on, off, or unknown with the reason (read-only).

    Read from GET /api/2.1/settings/enforce_ai_gateway_v3_only (the CLI's workspace-settings-v2
    get-public-workspace-setting); verified Nov 3, 2026. The effective value includes the account default."""
    try:
        d = _get(w, f"/api/2.1/settings/{ENFORCE_SETTING}")
    except Exception as error:
        return f"unknown: {str(error)[:120]}"
    val = (d.get("effective_boolean_val") or d.get("boolean_val") or {}).get("value")
    return "unknown: the setting has no value" if val is None else ("on" if val else "off")


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


# -- Central mode (optional): scan another workspace of the account from the hub's scan job --------------------

WORKSPACE_ID_RE = re.compile(r"[0-9]{1,20}")
WORKSPACE_URL_RE = re.compile(r"https://[A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9]/?")


def parse_workspace_ids(value) -> list[str]:
    """Workspace IDs from a comma-separated list (the central-mode allowlist). Raises ValueError on anything else."""
    ids = []
    for part in str(value or "").split(","):
        p = part.strip()
        if not p:
            continue
        if not WORKSPACE_ID_RE.fullmatch(p):
            raise ValueError(f"workspace IDs are numbers, not {p!r}")
        if p not in ids:
            ids.append(p)
    return ids


def remote_workspace_client(target_id: str, allowlist: list[str], url: str, client_id: str, client_secret: str,
                            factory=None) -> WorkspaceClient:
    """A client for another workspace, signed in as the central-mode service principal (OAuth M2M).

    The target must be on the allowlist and the URL must come from the account's workspace table (never from
    the caller). The secret is passed straight to the client and never logged. The client must answer as the
    target workspace, so a wrong URL can't scan another workspace by mistake."""
    target_id = str(target_id or "").strip()
    if target_id not in allowlist:
        raise PermissionError(f"workspace {target_id} isn't in the central-mode allowlist")
    if not WORKSPACE_URL_RE.fullmatch(url or ""):
        raise ValueError(f"workspace {target_id} has no usable URL in system.access.workspaces_latest")
    if not client_id or not client_secret:
        raise ValueError("central mode needs the service principal's client ID (Run jobs as service principal) "
                         "and its OAuth secret (Central mode: service principal OAuth secret)")
    client = (factory or WorkspaceClient)(host=url.rstrip("/"), client_id=client_id, client_secret=client_secret,
                                          auth_type="oauth-m2m")
    got = workspace_id_of(client)
    if str(got) != target_id:
        raise ValueError(f"{url} answers as workspace {got}, not {target_id}")
    return client


SECRET_REF_RE = re.compile(r"[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+")


def central_target(spark, hub_client: WorkspaceClient, target_id: str, allowlist_raw: str, client_id: str,
                   secret_ref: str, secret_get, factory=None) -> tuple[WorkspaceClient, str, bool]:
    """The client a job acts through, the other workspace's ID ("" for the hub), and whether it's another workspace.

    Blank or the hub's own ID: the hub client (the hub's ID is only looked up when a target is named). Another workspace (central mode): everything is checked before it
    is contacted, in this order: allowlist, secret reference format, URL from system.access.workspaces_latest (never
    from the caller), the secret (read here, never logged), then remote_workspace_client, which signs in and
    checks the URL answers as that workspace. secret_get(scope, key) is dbutils.secrets.get in the notebooks."""
    target_id = str(target_id or "").strip()
    if not target_id or target_id == str(workspace_id_of(hub_client)):
        return hub_client, "", False
    allowlist = parse_workspace_ids(allowlist_raw)
    if target_id not in allowlist:
        raise PermissionError(f"workspace {target_id} isn't in this install's central-mode allowlist")
    ref = str(secret_ref or "").strip()
    if not SECRET_REF_RE.fullmatch(ref):
        raise ValueError("central_secret must be scope/key")
    rows = spark.sql("SELECT workspace_url FROM system.access.workspaces_latest WHERE workspace_id = :id",
                     args={"id": target_id}).collect()
    url = (rows[0]["workspace_url"] if rows else "") or ""
    url = url if url.startswith("http") else (f"https://{url}" if url else "")
    scope, key = ref.split("/", 1)
    client = remote_workspace_client(target_id, allowlist, url, str(client_id or "").strip(), secret_get(scope, key),
                                     factory=factory)
    return client, target_id, True


ALLOW_SPARK = True  # set False when scanning a workspace other than the one this process runs in
REMOTE_SCAN = False  # central mode: the scanned workspace isn't the one this process (and its Spark) runs in
SQL_POLL_SECONDS = 1800  # give up waiting on a system table query after this (the warehouse keeps running it)


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
    deadline = time.time() + SQL_POLL_SECONDS
    while resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
        if time.time() > deadline:
            raise RuntimeError(f"query still running after {SQL_POLL_SECONDS // 60} minutes; stopped waiting for it")
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
SENSITIVE_KEY_RE = re.compile(r"(key|secret|token|password|credential|pass|pwd)", re.I)


def _fingerprint(value: str) -> str:
    """Short, stable tag for a plaintext value: tells two different keys apart without showing either."""
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()[:8]


def _redact(obj):
    """Copy of a provider config with literal credential values replaced; secret references are kept.

    Each replacement carries a short fingerprint so two endpoints with different plaintext keys stay in
    different provider groups (the fingerprint is not the value, but it is stable for the same value).
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(v, str) and SENSITIVE_KEY_RE.search(k) and not SECRET_RE.fullmatch(v.strip()):
                out[k] = f"<redacted plaintext {_fingerprint(v)}>"
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
        elif e.get("min_provisioned_throughput") is not None or e.get("max_provisioned_throughput") is not None \
                or e.get("provisioned_model_units") is not None:
            # Checked before foundation_model: a PT entity that also names a foundation model is still PT.
            destinations.append({"served_entity": e.get("name"), "type": "provisioned_throughput",
                                 "model": e.get("entity_name"), "version": e.get("entity_version"),
                                 "workload_type": e.get("workload_type"),
                                 "scale_to_zero": e.get("scale_to_zero_enabled")})
            kinds.add("provisioned_throughput")
        elif e.get("foundation_model"):
            fm = e["foundation_model"]
            destinations.append({"served_entity": e.get("name"), "type": "system_ppt",
                                 "model": fm.get("name") if isinstance(fm, dict) else fm})
            kinds.add("system_ppt")
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
        # Legacy inference tables (deprecated) live in config.auto_capture_config, not in ai_gateway.
        auto = (ep.get("config") or {}).get("auto_capture_config")
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
            auto_capture=auto if isinstance(auto, dict) and auto.get("enabled") else None,
            route_optimized=bool(ep.get("route_optimized")),
            endpoint_url=ep.get("endpoint_url"),
            # Only the explicit values: the detail response also shows the workspace default as effective_*.
            budget_policy_id=ep.get("budget_policy_id"),
            usage_policy_id=ep.get("usage_policy_id"),
            gateway_settings=sorted(k for k, v in gw.items() if v),
        ))
    return out


def v2_workspace_endpoints(usage: dict[str, dict], known: Iterable[str],
                           dormant: Iterable[str] = ()) -> list[LegacyEndpoint]:
    """Workspace-bound AI Gateway v2 endpoints: names with v2 traffic that aren't serving endpoints.

    Measured: they have no serving-endpoint object, so the serving list doesn't show them. Their only trace is
    system.ai_gateway.usage, so they are inventoried from the traffic: the ones with v2 requests in the window,
    plus dormant ones (v2 requests only before the window, see v2_endpoint_history), so code that still names a
    dormant v2 endpoint is found by the scan.
    """
    known = set(known)
    names = {name for name in usage if int(usage[name].get("v2_requests") or 0)} | set(dormant)
    return [LegacyEndpoint(name=name, endpoint_id=None, kind="v2_workspace_endpoint", source=V2_SOURCE,
                           destinations=[{"served_entity": None, "type": "v2_workspace", "model": name}])
            for name in sorted(names) if name and name not in known]


# How far back to look for v2 endpoint names with no traffic in the window (system table retention permitting).
V2_HISTORY_DAYS = 365


def v2_endpoint_history(w: WorkspaceClient, warehouse_id: str | None, workspace_id: str,
                        days: int = V2_HISTORY_DAYS) -> list[str]:
    """Every endpoint name with AI Gateway v2 requests in the last `days` days (names only, no counts)."""
    rows = _sql(w, warehouse_id, f"""
        SELECT DISTINCT endpoint_name FROM system.ai_gateway.usage
        WHERE workspace_id = :ws AND service_type IS NULL AND endpoint_name IS NOT NULL
          AND event_time >= current_timestamp() - INTERVAL {int(days)} DAYS
    """, {"ws": workspace_id})
    return sorted({r["endpoint_name"] for r in rows if r.get("endpoint_name")})


# Coverage value of system_ai_map when the listing says Unity Gateway isn't on here (readiness makes it a blocker).
UNAVAILABLE = "unavailable"
UNAVAILABLE_CODES = ("FEATURE_DISABLED", "NOT_IMPLEMENTED")


def unity_gateway_unavailable(error: Exception) -> bool:
    """True when a failed system.ai listing means Unity Gateway isn't enabled for this workspace or account.

    Rules: the API error code (FEATURE_DISABLED, NOT_IMPLEMENTED), the SDK classes for HTTP 501 (NotImplemented) and
    403 (PermissionDenied), or "not enabled" / "disabled" in the message. Any other error is a coverage gap.
    """
    from databricks.sdk import errors as sdk_errors

    code = str(getattr(error, "error_code", "") or "").upper()
    if code in UNAVAILABLE_CODES or isinstance(error, (sdk_errors.NotImplemented, sdk_errors.PermissionDenied)):
        return True
    text = str(error).lower()
    return "not enabled" in text or "disabled" in text


def system_ai_map(w: WorkspaceClient, coverage: dict[str, str] | None = None,
                  api_types: dict[str, list[str]] | None = None) -> dict[str, str]:
    """Map legacy databricks-* names to system.ai model service names.

    Uses the PPT destination of each system.ai service (models/system.ai.<model>)
    rather than string rules, then falls back to name matching. A failed listing is
    recorded in coverage, so readiness can't say READY on a map it never read. When the failure means Unity
    Gateway isn't available (unity_gateway_unavailable), coverage says so and readiness reports a blocker.
    When api_types is given, it is filled with each service's supported_api_types (services whose
    types can't be read are left out).
    """
    mapping: dict[str, str] = {}
    try:
        services = list(w.ai_gateway.list_model_services(parent="schemas/system.ai"))
    except Exception as error:
        _log(f"Could not list system.ai model services: {error}")
        if coverage is not None:
            if unity_gateway_unavailable(error):
                coverage["system_ai_map"] = f"{UNAVAILABLE}: {str(error)[:120]}"
            else:
                coverage["system_ai_map"] = f"failed: {str(error)[:120]}"
        return mapping
    if coverage is not None:
        coverage["system_ai_map"] = "ok"
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
        if api_types is not None:
            types = s.supported_api_types
            if types is None:
                try:
                    types = w.ai_gateway.get_model_service(name=s.name).supported_api_types
                except Exception:
                    types = None
            if types is not None:
                api_types[svc] = sorted(types)
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


# AI Gateway v2 requests on legacy endpoints are logged only in system.ai_gateway.usage (rows without a
# service_type), not in system.serving.endpoint_usage. Measured 2026-10-31: an endpoint with 2.2M v2 requests in
# 7 days had no endpoint_usage rows, so both tables are read and summed.
# failed counts the rows with no status code, or status 0 or 501 (other 4xx and 5xx can be caller, permission, rate-limit or provider errors, not a gateway that is off). status_501 counts HTTP 501: v2 is off
# for the workspace (Enforce retires v2 with 501), so those calls already fail. Both are kept apart from requests.
# One row per (endpoint, requester, user agent, URL, API type). Everything v2 is derived from it in Python: totals,
# requesters, routes (api_type) and caller classes (user agent and URL tell the caller apart).
V2_CALLER_SQL = """
        SELECT endpoint_name, requester, user_agent, url, api_type, count(*) AS requests,
               sum(CASE WHEN status_code IS NULL OR status_code IN (0, 501) THEN 1 ELSE 0 END) AS failed,
               sum(CASE WHEN status_code = 501 THEN 1 ELSE 0 END) AS status_501,
               coalesce(sum(total_tokens), 0) AS tokens,
               CAST(max(event_time) AS STRING) AS last_request
        FROM system.ai_gateway.usage
        WHERE workspace_id = :ws AND service_type IS NULL AND endpoint_name IS NOT NULL
          AND event_time >= current_timestamp() - INTERVAL {days} DAYS
        GROUP BY endpoint_name, requester, user_agent, url, api_type
"""

# Caller classes. Another module copies these rules (keep the two in step). Coding agents are matched first,
# because their user agents also carry the SDK name.
CALLER_CLASSES = ("platform", "no_client_info", "coding_agent", "sdk", "llm_sdk", "http", "service_principal", "user",
                  "unknown")
CODING_AGENT_MARKERS = ("claude-code", "opencode", "codex", "cursor", "copilot", "gemini-cli", "aider")
SDK_MARKERS = ("databricks-sdk", "mlflow")
LLM_SDK_MARKERS = ("openai", "litellm", "anthropic", "langchain")
HTTP_MARKERS = ("python-requests", "curl", "axios", "go-http", "java")
# Requesters that are Databricks system identities. Only names seen in practice belong here; none was seen in the
# test workspace's v1 rows, so the list is short and conservative.
SYSTEM_REQUESTERS = {"system", "databricks", "databricks-system"}
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def caller_class(user_agent: str | None, url: str | None, requester: str | None, api: str = "v1") -> str:
    """Who sent the requests: one of CALLER_CLASSES.

    api="v2" marks rows from system.ai_gateway.usage. There, a row with no user agent and no URL is "no_client_info":
    measured 2026-11-01, those rows were requester_type USER with an email, bursty (2.2M requests from 21 users in 49
    hours), so most likely ai_query or batch inference from notebooks and jobs, which the customer owns. They may
    also be a Databricks feature running as the user (Genie, Agent Bricks). Either way they block readiness: only
    known Databricks system identities are "platform". v1 rows (system.serving.endpoint_usage) have neither user
    agent nor URL, so they are classed by requester: a UUID is a service principal, an email is a user.
    """
    ua = (user_agent or "").lower()
    if (requester or "").strip().lower() in SYSTEM_REQUESTERS:
        return "platform"
    if api == "v2" and not ua and not url:
        return "no_client_info"
    if ua:
        for cls, markers in (("coding_agent", CODING_AGENT_MARKERS), ("sdk", SDK_MARKERS),
                             ("llm_sdk", LLM_SDK_MARKERS), ("http", HTTP_MARKERS)):
            if any(mk in ua for mk in markers):
                return cls
        return "unknown"
    who = (requester or "").strip()
    if who.lower() in SYSTEM_REQUESTERS:
        return "platform"
    if UUID_RE.match(who.lower()):
        return "service_principal"
    if "@" in who:
        return "user"
    return "unknown"


def _v2_rows(w: WorkspaceClient, warehouse_id: str | None, workspace_id: str, days: int) -> list[dict]:
    return _sql(w, warehouse_id, V2_CALLER_SQL.format(days=int(days)), {"ws": workspace_id})


def _v2_summary(rows: list[dict]) -> list[dict]:
    """Per endpoint: total v2 requests, failed and HTTP 501 requests, tokens, distinct requesters, last request and the
    routes (api types) seen."""
    per: dict[str, dict] = {}
    for r in rows:
        cur = per.setdefault(r["endpoint_name"], {"endpoint_name": r["endpoint_name"], "requests": 0, "failed": 0,
                                                  "status_501": 0, "tokens": 0, "requesters": set(),
                                                  "last_request": None, "api_types": set()})
        cur["requests"] += int(r.get("requests") or 0)
        cur["failed"] += int(r.get("failed") or 0)
        cur["status_501"] += int(r.get("status_501") or 0)
        cur["tokens"] += int(r.get("tokens") or 0)
        if r.get("requester"):
            cur["requesters"].add(r["requester"])
        if r.get("api_type"):
            cur["api_types"].add(r["api_type"])
        cur["last_request"] = max(filter(None, [cur["last_request"], r.get("last_request")]), default=None)
    return [dict(c, requesters=len(c["requesters"]), api_types=sorted(c["api_types"])) for c in per.values()]


def _merge_traffic(v1: list[dict], v2: list[dict]) -> dict[str, dict]:
    """Sum v1 (endpoint_usage) and v2 (ai_gateway.usage) rows per endpoint. tokens is v1 plus v2; v2_tokens,
    v2_failed and v2_status_501 are the v2 part. Requesters can overlap, so the requester count is the larger of
    the two (a lower bound)."""
    out: dict[str, dict] = {}
    for r in v1:
        out[r["endpoint_name"]] = dict(r, tokens=int(r.get("tokens") or 0), v2_requests=0, v2_tokens=0, v2_failed=0,
                                       v2_status_501=0)
    for r in v2:
        cur = out.setdefault(r["endpoint_name"], {"endpoint_name": r["endpoint_name"], "requests": 0,
                                                  "requesters": 0, "last_request": None, "throttled": 0,
                                                  "tokens": 0, "v2_requests": 0, "v2_tokens": 0, "v2_failed": 0,
                                                  "v2_status_501": 0, "api_types": []})
        n = int(r.get("requests") or 0)
        cur["requests"] = int(cur.get("requests") or 0) + n
        cur["v2_requests"] = int(cur.get("v2_requests") or 0) + n
        cur["v2_failed"] = int(cur.get("v2_failed") or 0) + int(r.get("failed") or 0)
        cur["v2_status_501"] = int(cur.get("v2_status_501") or 0) + int(r.get("status_501") or 0)
        cur["v2_tokens"] = int(cur.get("v2_tokens") or 0) + int(r.get("tokens") or 0)
        cur["tokens"] = int(cur.get("tokens") or 0) + int(r.get("tokens") or 0)
        cur["requesters"] = max(int(cur.get("requesters") or 0), int(r.get("requesters") or 0))
        cur["last_request"] = max(filter(None, [cur.get("last_request"), r.get("last_request")]), default=None)
        cur["api_types"] = sorted(set(cur.get("api_types") or []) | set(r.get("api_types") or []))
    return out


def traffic(w: WorkspaceClient, warehouse_id: str | None, workspace_id: str, days: int) -> dict[str, dict]:
    v1 = _sql(w, warehouse_id, f"""
        SELECT se.endpoint_name,
               count(*) AS requests,
               count(DISTINCT eu.requester) AS requesters,
               CAST(max(eu.request_time) AS STRING) AS last_request,
               sum(CASE WHEN eu.status_code = 429 THEN 1 ELSE 0 END) AS throttled,
               coalesce(sum(coalesce(eu.input_token_count, 0) + coalesce(eu.output_token_count, 0)), 0) AS tokens
        FROM system.serving.endpoint_usage AS eu
        JOIN system.serving.served_entities AS se
          ON eu.served_entity_id = se.served_entity_id
        WHERE eu.workspace_id = :ws
          AND eu.request_time >= current_timestamp() - INTERVAL {int(days)} DAYS
        GROUP BY se.endpoint_name
    """, {"ws": workspace_id})
    v2 = _v2_summary(_v2_rows(w, warehouse_id, workspace_id, days))
    return _merge_traffic(v1, v2)


def unattributed_v1(w: WorkspaceClient, warehouse_id: str | None, workspace_id: str, days: int) -> int:
    """v1 requests in the window whose served entity has no system.serving.served_entities row. traffic() joins on
    served_entities, so these would otherwise read as no traffic for whichever endpoint they belong to."""
    rows = _sql(w, warehouse_id, f"""
        SELECT count(*) AS n
        FROM system.serving.endpoint_usage AS eu
        LEFT JOIN system.serving.served_entities AS se
          ON eu.served_entity_id = se.served_entity_id
        WHERE eu.workspace_id = :ws
          AND eu.request_time >= current_timestamp() - INTERVAL {int(days)} DAYS
          AND se.served_entity_id IS NULL
    """, {"ws": workspace_id})
    return int((rows[0] if rows else {}).get("n") or 0)


def traffic_by_requester(w: WorkspaceClient, warehouse_id: str | None, workspace_id: str, days: int) -> list[dict]:
    v1 = _sql(w, warehouse_id, f"""
        SELECT se.endpoint_name, eu.requester, count(*) AS requests,
               coalesce(sum(coalesce(eu.input_token_count, 0) + coalesce(eu.output_token_count, 0)), 0) AS tokens,
               CAST(max(eu.request_time) AS STRING) AS last_request
        FROM system.serving.endpoint_usage AS eu
        JOIN system.serving.served_entities AS se
          ON eu.served_entity_id = se.served_entity_id
        WHERE eu.workspace_id = :ws
          AND eu.request_time >= current_timestamp() - INTERVAL {int(days)} DAYS
        GROUP BY se.endpoint_name, eu.requester
    """, {"ws": workspace_id})
    merged: dict[tuple, dict] = {}

    def add(r: dict, api: str, user_agent: str | None, cls: str) -> None:
        k = (r["endpoint_name"], r["requester"], api, user_agent, cls)
        cur = merged.setdefault(k, {"endpoint_name": k[0], "requester": k[1], "api": api, "user_agent": user_agent,
                                    "caller_class": cls, "requests": 0, "tokens": 0, "last_request": None})
        cur["requests"] += int(r.get("requests") or 0)
        cur["tokens"] += int(r.get("tokens") or 0)
        cur["last_request"] = max(filter(None, [cur["last_request"], r.get("last_request")]), default=None)

    for r in v1:
        add(r, "v1", None, caller_class(None, None, r.get("requester"), "v1"))
    for r in _v2_rows(w, warehouse_id, workspace_id, days):
        ua = r.get("user_agent")
        add(r, "v2", ua, caller_class(ua, r.get("url"), r.get("requester"), "v2"))
    return sorted(merged.values(), key=lambda r: -r["requests"])


# ---------------------------------------------------------------------------
# 3. Plan
# ---------------------------------------------------------------------------

def retarget_name(name: str | None, catalog: str, schema: str) -> str | None:
    """A planned service name under another catalog.schema. system.ai services (and empty names) are unchanged."""
    if not name or name.startswith("system.ai.") or name.count(".") != 2:
        return name
    return f"{catalog}.{schema}.{name.split('.', 2)[2]}"


def retarget_plan(rows: list, catalog: str, schema: str) -> list:
    """The plan rows with their model and provider service names moved to catalog.schema (the apply-time target).

    Rows are PlanRow objects or the dicts stored with a scan; copies are returned, the input is unchanged. Only
    target_service and provider_service change (system.ai targets stay). The apply job doesn't need this: it plans
    again from the live endpoints with the target it's given; this is for showing that plan before it runs."""
    out = []
    for r in rows:
        if isinstance(r, dict):
            d = dict(r)
            for k in ("target_service", "provider_service"):
                d[k] = retarget_name(d.get(k), catalog, schema)
        else:
            d = replace(r, target_service=retarget_name(r.target_service, catalog, schema),
                        provider_service=retarget_name(r.provider_service, catalog, schema))
        out.append(d)
    return out


WORKSPACE_LOCAL_GROUPS = {"admins", "users"}

V1_KEY_MAP = {
    "endpoint": "RATE_LIMIT_KEY_SERVICE",
    "user": "RATE_LIMIT_KEY_USER",  # becomes USER_DEFAULT when no principal
    "user_group": "RATE_LIMIT_KEY_USER_GROUP",
    "service_principal": "RATE_LIMIT_KEY_SERVICE_PRINCIPAL",
}


RENEWAL_MAP = {"minute": "RATE_LIMIT_RENEWAL_PERIOD_MINUTE", "hour": "RATE_LIMIT_RENEWAL_PERIOD_HOUR"}
BLOCKING_PREFIX = "BLOCKS APPLY: "  # needs_human entries that must stop automation
NO_TRAFFIC_NEED = "no requests in the window (zero is not proof of no use): confirm with the owner before migrating or retiring it"
PLAINTEXT_KEY_NEED = ("API key is stored in plaintext in the endpoint config (value not shown): move it to a secret "
                      "scope or Unity Catalog secret before migrating.")
NO_SYSTEM_AI_NEED = "no system.ai model for this endpoint: pick a replacement model"
V2_NEED = ("workspace-bound AI Gateway v2 endpoint (not a serving endpoint, so it is absent from the serving list): "
           "callers keep their /ai-gateway/ route and change the model name to the system.ai model")
API_TYPE_NEED = ("callers use {missing}, which {target} doesn't support (supported_api_types): this needs a manual "
                 "decision. Keep the route and pick a model that supports it; never move a Responses client to Chat "
                 "Completions")
PLATFORM_ACTION = ("Databricks-managed callers (for example Genie, Agent Bricks, AI Search). You can't change these; "
                   "confirm with your account team how they move")


def _n(count: int, word: str) -> str:
    """'1 caller', '3 callers', '0 callers'."""
    return f"{count} {word if count == 1 else word + 's'}"


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


GUARDRAIL_ACK_HINT = ("set the service policies, then re-plan with --ack-guardrails (ack_guardrails=True) "
                      "to accept that the new service has no legacy guardrails")
# Providers Unity Gateway supports that this toolkit's apply step doesn't automate yet, and providers it doesn't support.
MANUAL_SUPPORTED_PROVIDERS = {"amazon-bedrock", "google-cloud-vertex-ai", "custom", "azure-ai-foundry", "foundry"}
NO_UG_PROVIDERS = {"cohere", "ai21labs", "palm", "databricks-model-serving", "mistral"}


def guardrail_settings(g: dict) -> list[str]:
    """The legacy guardrails that are on, as short labels: "input PII → BLOCK", "output safety", "input keywords"."""
    out = []
    for side in ("input", "output"):
        cfg = g.get(side) if isinstance(g, dict) else None
        cfg = cfg if isinstance(cfg, dict) else {}
        pii = cfg.get("pii")
        if pii:
            behavior = (pii.get("behavior") or "").upper() if isinstance(pii, dict) else ""
            if behavior != "NONE":
                out.append(f"{side} PII → {behavior or 'on'}")
        if cfg.get("safety"):
            out.append(f"{side} safety")
        if cfg.get("invalid_keywords"):
            out.append(f"{side} keywords")
        if cfg.get("valid_topics"):
            out.append(f"{side} topics")
    return out


def guardrail_consequence(g: dict) -> str:
    """What callers lose when they move from the legacy endpoint to the new service, in plain words."""
    does, reach = [], set()
    for side in ("input", "output"):
        cfg = g.get(side) if isinstance(g, dict) else None
        cfg = cfg if isinstance(cfg, dict) else {}
        what = "requests" if side == "input" else "responses"
        pii = cfg.get("pii")
        behavior = (pii.get("behavior") or "").upper() if isinstance(pii, dict) else ("BLOCK" if pii else "")
        if behavior == "MASK":
            does.append(f"masks PII in {what}")
            reach.add(side)
        elif behavior and behavior != "NONE":
            does.append(f"blocks {what} that contain PII")
            reach.add(side)
        if cfg.get("safety"):
            does.append(f"blocks unsafe {what}")
            reach.add(side)
        if cfg.get("invalid_keywords"):
            does.append(f"blocks {what} with listed keywords")
            reach.add(side)
        if cfg.get("valid_topics"):
            does.append(f"allows only listed topics in {what}")
            reach.add(side)
    if not does:
        return "This endpoint has AI Gateway guardrails that the new service won't have. Re-create the protection " \
               "on the service or in your callers before moving them."
    listed = does[0] if len(does) == 1 else ", ".join(does[:-1]) + " and " + does[-1]
    lands = " and ".join(p for p in (("those requests will reach the model" if "input" in reach else ""),
                                     ("those responses will reach your callers" if "output" in reach else "")) if p)
    return (f"This endpoint {listed} today ({'; '.join(guardrail_settings(g))}). The new service won't: {lands}. "
            "Re-create the protection on the service or in your callers before moving them.")


def _guardrail_advice(g: dict) -> str:
    """Suggest Unity Gateway service policies for legacy guardrails (not 1:1).

    Service policies are Beta and need the workspace preview opt-in.
    """
    tips = []
    for side in ("input", "output"):
        cfg = g.get(side) if isinstance(g, dict) else None
        cfg = cfg if isinstance(cfg, dict) else {}
        if cfg.get("pii"):
            pii = cfg["pii"]
            behavior = (pii.get("behavior") or "").upper() if isinstance(pii, dict) else ""
            action = "redact" if behavior == "MASK" else "block"
            tips.append(f"{side} PII {behavior or 'unset'}: system.ai.detect_sensitive_data, {action}")
        if cfg.get("safety"):
            tips.append(f"{side} safety: system.ai.block_unsafe_content")
        if cfg.get("invalid_keywords") or cfg.get("valid_topics"):
            tips.append(f"{side} keywords/topics: custom service policy function")
    return "; ".join(tips) + ". Service policies are Beta (workspace preview opt-in) and fail closed: test in " \
        "log mode first" if tips else "re-create as service policies (not 1:1)"


def provider_status(dest: dict) -> str:
    """What the toolkit can do with an external model provider.

    automated: apply creates the provider service. manual_supported: Unity Gateway has the provider but apply
    doesn't automate it yet. no_ug_provider: Unity Gateway has no provider for it. unknown_provider: a name
    this list doesn't know (check it by hand).
    """
    provider = (dest.get("provider") or "").lower()
    if provider == "openai":
        cfg = (dest.get("provider_config") or {}).get("openai_config") or {}
        return "manual_supported" if (cfg.get("openai_api_type") or "").lower() == "azuread" else "automated"
    if provider == "anthropic":
        return "automated"
    if provider in MANUAL_SUPPORTED_PROVIDERS:
        return "manual_supported"
    if provider in NO_UG_PROVIDERS:
        return "no_ug_provider"
    return "unknown_provider"


PPT_BACKED_NEED = ("forwards to the pay-per-token endpoint {model} through the databricks-model-serving provider, so it "
                   "stops working when Enforce is on: move its callers to {target}{service}")
PPT_BACKED_SERVICE = (", or to the model service apply creates (a pay-per-token destination on the same model, keeping "
                      "the rate limits and inference table)")


def ppt_shape(dest: dict) -> str | None:
    """The databricks-* endpoint an external-model destination forwards to through the databricks-model-serving
    provider, else None. Such a destination needs no provider service."""
    model = str(dest.get("model") or "")
    if dest.get("type") == "external_model" and dest.get("provider") == "databricks-model-serving" \
            and model.startswith("databricks-"):
        return model
    return None


def ppt_uc_model(dest: dict, uc_models: Iterable[str] | None) -> str | None:
    """The system.ai UC model a model service can route to for this destination (pay-per-token destination), or
    None. The UC model carries the endpoint's name (system.ai.databricks-claude-haiku-4-5), and it must be in
    uc_models (system_ai_uc_models): a model nobody confirmed exists is never automated."""
    model = ppt_shape(dest)
    uc = f"system.ai.{model}" if model else None
    return uc if uc and uc in set(uc_models or ()) else None


def system_ai_uc_models(w: WorkspaceClient, coverage: dict[str, str] | None = None) -> set[str]:
    """The UC models in system.ai (system.ai.<name>), which pay-per-token destinations route to.

    Measured Nov 5, 2026: system.ai model services don't show their own destinations, so the UC model list is
    what confirms a pay-per-token destination exists. A failed listing returns an empty set (nothing is
    automated) and is recorded in coverage."""
    try:
        found = {f"system.ai.{m.name}" for m in w.registered_models.list(catalog_name="system", schema_name="ai")
                 if m.name}
    except Exception as error:
        _log(f"Could not list the system.ai models: {error}")
        if coverage is not None:
            coverage["system_ai_models"] = f"failed: {str(error)[:120]}"
        return set()
    if coverage is not None:
        coverage["system_ai_models"] = "ok"
    return found


def needs_provider_service(dest: dict) -> bool:
    """External-model destinations that need a provider service (not the ones on a databricks-* endpoint)."""
    return dest.get("type") == "external_model" and not ppt_shape(dest)


def ppt_backed_models(ep: "LegacyEndpoint") -> list[str]:
    """databricks-* pay-per-token endpoints an external model endpoint calls through the databricks-model-serving
    provider. Enforce stops those endpoints, so the external model endpoint breaks with them."""
    return sorted({str(d.get("model")) for d in ep.destinations
                   if d.get("type") == "external_model" and d.get("provider") == "databricks-model-serving"
                   and str(d.get("model") or "").startswith("databricks-")})


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


def _route_check(target: str | None, observed: list[str], supported: list[str] | None, needs: list[str]) -> bool:
    """Compare the API types callers use (from v2 traffic) with what the target supports.

    Adds a note to needs. Returns True when a manual decision is needed (the target can't serve a route callers use).
    """
    if not target or not observed:
        return False
    if supported is None:
        needs.append(f"could not read the supported API types of {target}: check {', '.join(observed)} by hand "
                     "before moving callers")
        return False
    missing = [t for t in observed if t not in supported]
    if missing:
        needs.append(API_TYPE_NEED.format(missing=", ".join(missing), target=target))
        return True
    return False


def plan(endpoints: list[LegacyEndpoint], sys_map: dict[str, str], usage: dict[str, dict],
         target_catalog: str, target_schema: str, traffic_known: bool = True,
         ack_guardrails: bool = False, target_api_types: dict[str, list[str]] | None = None,
         uc_models: Iterable[str] | None = None) -> tuple[list[PlanRow], list[dict]]:
    rows: list[PlanRow] = []
    providers: dict[str, dict] = {}
    used_targets: set[str] = set()
    used_providers: set[str] = set()
    for ep in endpoints:
        needs: list[str] = []
        u = usage.get(ep.name, {})
        base = dict(requests_window=int(u.get("requests") or 0), requesters=int(u.get("requesters") or 0),
                    last_request=u.get("last_request"), v2_requests=int(u.get("v2_requests") or 0),
                    api_types=sorted(u.get("api_types") or []), tokens_window=int(u.get("tokens") or 0),
                    v2_tokens=int(u.get("v2_tokens") or 0), v2_failed=int(u.get("v2_failed") or 0),
                    v2_status_501=int(u.get("v2_status_501") or 0))
        limits, limit_issues = _translate_rate_limits(ep.rate_limits)
        needs += [BLOCKING_PREFIX + i for i in limit_issues]
        if traffic_known and not base["requests_window"] and ep.kind != "system_ppt":
            # annotate_dependencies() replaces this with the retire advice only when no code references the endpoint.
            needs.append(NO_TRAFFIC_NEED + (f" (state {ep.state})" if ep.state and ep.state != "READY" else ""))
        if any("<redacted plaintext" in json.dumps(d.get("provider_config") or {}) for d in ep.destinations):
            needs.append(PLAINTEXT_KEY_NEED)
        if ep.usage_tracking:
            needs.append("usage tracking is on: dashboards on system.serving.endpoint_usage should move to "
                         "system.ai_gateway.usage")
        if ep.route_optimized:
            needs.append(f"route-optimized endpoint: callers use {ep.endpoint_url or 'its own URL'}, which goes away "
                         "with the legacy endpoint; move callers to the Unity Gateway URL")
        for label, value in (("budget policy", ep.budget_policy_id), ("usage policy", ep.usage_policy_id)):
            if value:
                needs.append(f"{label} {value} doesn't carry over: attach it to the new service by hand if still needed")
        grants = []
        for g in ep.can_query:
            if not g.get("principal"):
                continue
            if g["principal_type"] == "group" and g["principal"] in WORKSPACE_LOCAL_GROUPS:
                continue  # workspace admins/users are not Unity Gateway principals
            privs = ["EXECUTE", "MANAGE"] if "CAN_MANAGE" in g["levels"] else ["EXECUTE"] \
                if "CAN_QUERY" in g["levels"] else []
            if privs:
                grants.append({"principal": g["principal"], "principal_type": g["principal_type"], "privileges": privs})
        if any(g["principal"] == "users" and "CAN_QUERY" in g["levels"] for g in ep.can_query):
            needs.append("legacy endpoint is open to all workspace users; choose an account-level group for EXECUTE")
        inference = None
        # Deprecated auto-capture tables are mapped like AI Gateway inference tables.
        it = ep.inference_table or ep.auto_capture or {}
        source = "AI Gateway inference table" if ep.inference_table \
            else "legacy auto-capture table (deprecated config.auto_capture_config)"
        if it and it.get("enabled", True) and not (it.get("catalog_name") and it.get("schema_name")):
            needs.append(f"{source} without catalog/schema: configure logging on the new service by hand")
        elif it and it.get("enabled", True):
            inference = {
                "parent": f"schemas/{it.get('catalog_name')}.{it.get('schema_name')}",
                # The legacy endpoint already owns <prefix>_payload, so the new service needs its own prefix.
                "table_name_prefix": (it.get("table_name_prefix") or ep.name.replace("-", "_")) + "_ug",
                "note": "new table <prefix>_ug_payload; history stays in the legacy table",
            }
            if not ep.inference_table:
                needs.append("logging comes from the deprecated auto-capture setting: the new service logs to a new "
                             "table; history stays in the legacy table")

        if ep.kind == "v2_workspace_endpoint":
            target = sys_map.get(ep.name)
            supported = (target_api_types or {}).get(target) if target else None
            needs.append(V2_NEED)
            if not target:
                needs.append(NO_SYSTEM_AI_NEED)
            manual = _route_check(target, base["api_types"], supported, needs)
            rows.append(PlanRow(ep.name, ep.kind, "manual" if (manual or not target) else "use_system_ai", target, None,
                                "PAY_PER_TOKEN_FOUNDATION_MODEL" if target else None, [], None, None, [], ep.tags,
                                needs, target_api_types=list(supported or []), **base))
            continue

        if ep.kind == "system_ppt":
            target = sys_map.get(ep.name)
            supported = (target_api_types or {}).get(target) if target else None
            if not target:
                needs.append(NO_SYSTEM_AI_NEED)
            # Callers on the /ai-gateway/ route (v2) need the same API-type check as v2-only endpoints.
            manual = _route_check(target, base["api_types"], supported, needs)
            dropped = [label for label, on in (("rate limits", ep.rate_limits), ("guardrails", ep.guardrails),
                                               ("inference table", it)) if on]
            if dropped:
                needs.append(f"legacy endpoint has gateway settings that a system.ai service can't carry "
                             f"({', '.join(dropped)}); system.ai services are shared across the metastore, so use a "
                             "wrapper service or group-scoped limits")
            rows.append(PlanRow(ep.name, ep.kind, "manual" if (manual or not target) else "use_system_ai", target, None,
                                "PAY_PER_TOKEN_FOUNDATION_MODEL", limits, None, inference,
                                [], ep.tags, needs, target_api_types=list(supported or []), **base))
            continue

        if ep.kind in ("custom_model", "unknown") or ep.kind.startswith("mixed"):
            rows.append(PlanRow(ep.name, ep.kind, "out_of_scope" if ep.kind == "custom_model" else "manual",
                                None, None, None, [], None, None, [], ep.tags,
                                ["custom ML model endpoints are not migrated" if ep.kind == "custom_model"
                                 else f"endpoint kind {ep.kind} needs review"], **base))
            continue

        if ep.kind == "agent":
            # Agent endpoints aren't retired: only the LLM calls inside them move, so their callers need no change.
            rows.append(PlanRow(ep.name, ep.kind, "out_of_scope", None, None, None, [], None, None, [], ep.tags,
                                [AGENT_NEED], **base))
            continue

        target = _unique(f"{target_catalog}.{target_schema}.{_uc_name(ep.name)}", used_targets, needs)
        route_pct = {r.get("served_model_name") or r.get("served_entity_name"): r.get("traffic_percentage")
                     for r in ep.traffic_routes}
        destinations, provider_names, statuses = [], [], []
        for model in ppt_backed_models(ep):
            confirmed = f"system.ai.{model}" in set(uc_models or ())
            needs.append(PPT_BACKED_NEED.format(model=model, target=sys_map.get(model) or "a system.ai model",
                                                service=PPT_BACKED_SERVICE if confirmed else ""))
        for d in ep.destinations:
            if ppt_shape(d):
                # Same model, no provider service: a pay-per-token destination keeps the endpoint's rate limits
                # and inference table on a model service. Only when the system.ai UC model is confirmed.
                uc_model = ppt_uc_model(d, uc_models)
                statuses.append("automated" if uc_model else "unconfirmed_model")
                destinations.append({"destination_type": "DESTINATION_TYPE_PAY_PER_TOKEN_FOUNDATION_MODEL",
                                     "served_entity": d.get("served_entity"),
                                     "pay_per_token_model": uc_model,  # None until the UC model is confirmed
                                     "traffic_percentage": route_pct.get(d.get("served_entity"))})
            elif d["type"] == "external_model":
                pkey = _provider_key(d)
                if pkey not in providers:
                    secrets = sorted({f"{a}/{b}" for a, b in SECRET_RE.findall(json.dumps(d.get("provider_config")))})
                    pname = _unique(f"{target_catalog}.{target_schema}.{_provider_name(d, secrets, pkey)}",
                                    used_providers, [])
                    providers[pkey] = {"provider_service": pname, "provider": d.get("provider"), "provider_key": pkey,
                                       "provider_status": provider_status(d), "secrets": secrets, "models": set(),
                                       "legacy_endpoints": set()}
                providers[pkey]["models"].add(d.get("model"))
                providers[pkey]["legacy_endpoints"].add(ep.name)
                provider_names.append(providers[pkey]["provider_service"])
                statuses.append(providers[pkey]["provider_status"])
                destinations.append({"destination_type": "DESTINATION_TYPE_EXTERNAL_FOUNDATION_MODEL",
                                     "model_provider_service": providers[pkey]["provider_service"],
                                     "target_model": d.get("model"),
                                     "traffic_percentage": route_pct.get(d.get("served_entity"))})
            elif d["type"] == "provisioned_throughput":
                destinations.append({"destination_type": "DESTINATION_TYPE_PROVISIONED_THROUGHPUT_FOUNDATION_MODEL",
                                     "model_serving_endpoint": f"serving-endpoints/{ep.name}",
                                     "traffic_percentage": route_pct.get(d.get("served_entity"))})
                if d.get("workload_type") or d.get("scale_to_zero") is not None:
                    needs.append(f"PT settings (workload {d.get('workload_type') or 'default'}, scale to zero "
                                 f"{'on' if d.get('scale_to_zero') else 'off'}) stay on the legacy PT endpoint, "
                                 "which the Unity Gateway wrapper routes to")
        if ep.guardrails:
            advice = _guardrail_advice(ep.guardrails)
            consequence = guardrail_consequence(ep.guardrails)
            if ack_guardrails:
                needs.append(f"guardrails acknowledged, not carried over: {consequence} Suggested: {advice}")
            else:
                needs.append(f"{BLOCKING_PREFIX}guardrails not carried over: {consequence} Suggested: {advice}; "
                             f"{GUARDRAIL_ACK_HINT}")
        # Apply sends 0%-traffic destinations to the fallback, in listing order, and nothing else.
        zero = [d.get("served_entity") for d in ep.destinations if route_pct.get(d.get("served_entity")) == 0]
        routing = {"destinations": destinations}
        if ep.fallback_enabled and len(destinations) > 1:
            if zero:
                routing["fallback"] = "0%-traffic destinations, in listing order: " + ", ".join(zero)
            else:
                needs.append("legacy fallback is enabled but no destination is at 0% traffic: apply creates no fallback")
        bad = [s for s in statuses if s != "automated"]
        status = bad[0] if bad else ("automated" if statuses else None)
        action = "manual" if bad else "create_model_service"
        if bad:
            needs.append({"manual_supported": "Unity Gateway supports this provider but apply doesn't automate it: "
                                              "create the provider and model services by hand",
                          "no_ug_provider": "Unity Gateway has no provider for this model: keep the endpoint or "
                                            "move the callers to a supported model",
                          "unconfirmed_model": "the system.ai model this endpoint forwards to wasn't found (or the "
                                               "system.ai model list couldn't be read): move the callers to its "
                                               "system.ai service, or create the model service by hand with a "
                                               "pay-per-token destination",
                          }.get(status, "provider name not recognised: check it by hand"))
        rows.append(PlanRow(ep.name, ep.kind, action, target,
                            ", ".join(sorted(set(provider_names))) or None,
                            destinations[0]["destination_type"] if destinations else None,
                            limits, routing, inference, grants, ep.tags, needs, provider_status=status, **base))

    provider_list = [{**p, "models": sorted(m for m in p["models"] if m),
                      "legacy_endpoints": sorted(p["legacy_endpoints"])} for p in providers.values()]
    return rows, provider_list


# ---------------------------------------------------------------------------
# 4. Client reference scan
# ---------------------------------------------------------------------------

EMBEDDING_RE = re.compile(r"(gte|bge|e5|embedding|embed)", re.I)
# ai_query('name', ...) across lines, allowing SQL comments between "(" and the endpoint argument.
AI_QUERY_CALL_RE = re.compile(r"\bai_query\s*\(", re.I)
AI_QUERY_RE = re.compile(r"ai_query\s*\((?:\s|--[^\n]*\n|/\*.*?\*/)*(['\"])([A-Za-z0-9_.\-]+)\1", re.I | re.S)
# /serving-endpoints URLs; group 1 marks management APIs (/api/2.x/serving-endpoints), which aren't inference.
SERVING_URL_RE = re.compile(r"(/api/2\.\d)?/serving-endpoints(?:/([A-Za-z0-9_\-]+))?(/[A-Za-z0-9_\-/]+)?")
OPENAI_ROUTE_RE = re.compile(r"/serving-endpoints/(responses|chat/completions|embeddings|completions)\b")
MLFLOW_ENDPOINT_RE = re.compile(r"endpoints:/([A-Za-z0-9_\-]+)")
CHAT_DATABRICKS_START_RE = re.compile(r"ChatDatabricks\s*\(")
CHAT_DATABRICKS_ARG_RE = re.compile(r"\b(endpoint|model)\s*=\s*(['\"])([A-Za-z0-9_.\-]+)\2")
CONFIG_KEY_RE = re.compile(r"(endpoint|model|llm|embed|serving|chat|default|deployment)", re.I)
# Route-optimized endpoints have their own host (<id>.serving.databricks.com); the name isn't in the URL.
ROUTE_URL_RE = re.compile(r"https?://[A-Za-z0-9.\-]+\.serving\.(?:azure)?databricks\.(?:com|net)(?:/[^\s'\"<>)]*)?")
# "/serving-endpoints/" followed by a variable, f-string brace, format placeholder or concatenation.
DYNAMIC_URL_RE = re.compile(r"/serving-endpoints/(?:[{$%'\"]|\s*\+)")
DYNAMIC_URL_SUGGESTION = ("manual: the endpoint name is built at run time, so no URL can be rewritten here; "
                          "point this call at /ai-gateway/mlflow/v1 with the model service name")
# Client calls whose endpoint name comes from a variable, parameter or f-string, so no legacy name is on the line.
# Each client is bound to /serving-endpoints, so swapping only the name for a model service gives a 404.
OPENAI_CLIENT_RE = re.compile(r"\bget_open_ai_client\s*\(")
DEPLOY_CLIENT_RE = re.compile(r"\bget_deploy_client\s*\(")
PREDICT_CALL_RE = re.compile(r"\.\s*predict\s*\(")
NAME_ARG_RE = re.compile(r"\b(name|endpoint|model)\s*=\s*([^,)\s]+)")
DYNAMIC_MLFLOW_URI_RE = re.compile(r"endpoints:/(?=\{|['\"]\s*\+)")
# Tabular inputs only custom ML model endpoints take (LLM chat and embedding calls send messages, prompt or input).
TABULAR_ARG_RE = re.compile(r"\b(dataframe_records|dataframe_split|instances|inputs)\s*=")
TABULAR_CALL_SUGGESTION = ("probably no change: the endpoint name is a variable, but the call sends tabular input "
                           "(dataframe_records, dataframe_split, instances or inputs), the shape custom model endpoints "
                           "take, and custom model endpoints stay on /serving-endpoints. Confirm which endpoint it "
                           "calls: if it's a legacy endpoint, use the OpenAI client on <workspace>/ai-gateway/mlflow/v1")
# Patterns for unresolved calls: the scan can't name the endpoint, so readiness treats them like a dynamic URL.
VARIABLE_CALL_PATTERNS = ("sdk_openai_client", "sdk_serving_query", "mlflow_deployments_predict", "ChatDatabricks",
                          "mlflow_endpoint_uri")
# Patterns that become "no change" when the named endpoint is a custom model endpoint (not retired by Unity Gateway).
CUSTOM_CALL_PATTERNS = ("legacy_endpoint_name", "sdk_serving_query", "ai_query", "serving_endpoints_url",
                        "mlflow_deployments_predict", "config_value", "ChatDatabricks")


# MLflow model code: PythonModel and the agent base classes (agents.deploy serves ResponsesAgent and ChatAgent).
MODEL_BASES = r"(?:PythonModel|ResponsesAgent|ChatAgent|ChatModel)"
MODEL_CLASS_RE = re.compile(r"^([ \t]*)class\s+(\w+)\s*\([^)\n]*\b" + MODEL_BASES + r"\b[^)\n]*\)\s*:", re.M)
LOG_MODEL_RE = re.compile(r"\blog_model\s*\(")


def model_classes(text: str) -> dict[str, tuple[int, int]]:
    """MLflow model classes (PythonModel, ResponsesAgent, ChatAgent, ChatModel) in the text: class name -> (first
    line, last line) of its body."""
    lines = text.split("\n")
    out = {}
    for m in MODEL_CLASS_RE.finditer(text):
        start = text.count("\n", 0, m.start()) + 1
        indent, end = len(m.group(1)), start
        for i in range(start, len(lines)):  # lines[i] is line i + 1
            line = lines[i]
            if line.strip() and len(line) - len(line.lstrip()) <= indent:
                break
            end = i + 1
        out[m.group(2)] = (start, end)
    return out


def served_by(text: str, custom_models: dict[str, str]) -> dict[str, list[str]]:
    """Model class -> custom endpoints serving the model it is logged as (log_model(python_model=Class(...),
    registered_model_name=...)); matched on the model name's last part, since the catalog is often a variable."""
    out: dict[str, list[str]] = {}
    for m in LOG_MODEL_RE.finditer(text):
        args = _balanced_args(text, m.end() - 1)
        cls = re.search(r"python_model\s*=\s*(\w+)\s*\(", args)
        reg = re.search(r"registered_model_name\s*=\s*f?['\"]([^'\"]+)['\"]", args)
        if not cls or not reg:
            continue
        leaf = reg.group(1).split(".")[-1].split("}")[-1]
        out[cls.group(1)] = sorted(e for e, model in custom_models.items() if str(model).split(".")[-1] == leaf)
    return out


# How code should authenticate to /ai-gateway/ (security review, Nov 4): never a literal secret value.
CREDENTIALS_ADVICE = ("Credentials: service principal OAuth (M2M) first; a PAT with the ai-gateway scope only as a "
                      "fallback. Keep both in a secret scope and pass them as {{secrets/<scope>/<key>}} references "
                      "(for example in the endpoint's environment_vars), never as a literal value")


# Agent endpoints (agents.deploy and other agent/v1 endpoints) are custom serving endpoints: not retired.
AGENT_NEED = ("agent endpoint: not retired, and its callers need no change. Only the LLM calls inside it move to "
              "Unity Gateway services. Model Serving's automatic authentication can't call Unity Gateway services, "
              "so re-log the agent to call them with explicit credentials, or move it to Databricks Apps (the "
              "documented path)")
AGENT_ACTION = ("move the LLM calls inside the agent to system.ai or model services: re-log it with explicit "
                "credentials (automatic authentication can't call Unity Gateway services), or move it to Databricks "
                "Apps. Its callers need no change")
# Measured Nov 5, 2026: agent endpoints (agents.deploy, Knowledge Assistant) can't turn on usage tracking, so their
# requests aren't in system.serving.endpoint_usage. Zero requests there says nothing about whether the agent is used.
AGENT_TRAFFIC_UNKNOWN = ("traffic unknown: agent endpoints can't turn on usage tracking, so their requests aren't in "
                         "system.serving.endpoint_usage. Check the agent's inference table or MLflow traces")
# Knowledge Assistant and Supervisor Agent endpoints: Databricks builds and runs them, so there is no code to change.
AGENT_BRICKS_NEED = ("Agent Bricks {what}: not retired by this deadline, and its LLM calls are Databricks-managed, "
                     "so there is no code to change. Knowledge Assistant and Supervisor Agent are legacy offerings "
                     "with Genie Agents as the replacement: plan the move there. A Knowledge Assistant depends on AI "
                     "Search (every source, files included, syncs into an index), so it and the Supervisor agents "
                     "that use it break under Enforce (see the agent_bricks_vector_search blocker)")
AGENT_BRICKS_ACTION = ("no code change; plan the move to Genie Agents, the replacement for Knowledge Assistant and "
                       "Supervisor Agent. Knowledge Assistants, and Supervisor agents that use one, block Enforce")
# The Enforce limitations: Knowledge Assistant and Supervisor agents that depend on AI Search don't work with Enforce
# on. A Knowledge Assistant always does: a files or volume source syncs into the assistant's own index (measured
# Nov 5, 2026: a files-source assistant created its own AI Search endpoint and index). Lower this only if the Agent
# Bricks team confirms they work with Enforce on.
AGENT_BRICKS_BLOCK_ACTION = ("keep Enforce off while it's in use: Agent Bricks agents that depend on AI Search don't "
                             "work with Enforce on, and every Knowledge Assistant does (its sources sync into an AI "
                             "Search index). Plan the move to Genie Agents")


def annotate_agent_bricks(rows: list[PlanRow], agent_bricks: dict[str, str]) -> None:
    """Replace the custom agent advice on Knowledge Assistant and Supervisor Agent endpoints."""
    for row in rows:
        what = agent_bricks.get(row.legacy_endpoint)
        if what and row.kind == "agent":
            row.needs_human = [AGENT_BRICKS_NEED.format(what=what) if n == AGENT_NEED else n for n in row.needs_human]


def model_code_note(cls: str, endpoints: list[str] | None) -> str:
    where = (f"custom endpoint {', '.join(endpoints)}" if endpoints else "a custom serving endpoint, if one serves it")
    return (f"; this call is in MLflow model code (class {cls}), so it runs inside {where}. Under automatic "
            "authentication a Unity Gateway call from an endpoint fails with a misleading NotFound: re-log the model "
            "to call <workspace>/ai-gateway/mlflow/v1/chat/completions with explicit credentials and redeploy, or move "
            "the agent to a Databricks App. " + CREDENTIALS_ADVICE + ". On a custom model endpoint, also turn on usage "
            "tracking (agent endpoints can't); the endpoint's own callers need no change")


# The advice for an unnamed call that reaches a custom model or feature serving endpoint (same text in both guides).
CUSTOM_UNNAMED_ACTION = ("A custom model or feature serving endpoint: no change, and putting its name in the code or a "
                         "config value lets the next scan confirm it")
SYSTEM_SP_NAME = "System Service Principal"  # display name of a serving endpoint's automatic-auth identity


def custom_endpoint_suggestion(name: str) -> str:
    return (f"no change: {name} is a custom model endpoint. Custom model endpoints aren't retired by Unity Gateway "
            "or affected by Enforce, and /ai-gateway/ doesn't serve them, so callers stay on /serving-endpoints "
            "(and ai_query keeps the endpoint name)")


def variable_call_suggestion(client: str, names: list[str]) -> str:
    """Advice for a client call whose endpoint name the scan can't read."""
    fixes = {
        "sdk_openai_client": "w.serving_endpoints.get_open_ai_client() is bound to /serving-endpoints. Use "
                             "DatabricksOpenAI(use_ai_gateway=True) from databricks-openai, or "
                             "OpenAI(base_url='<workspace>/ai-gateway/mlflow/v1') with service principal OAuth (M2M), or an ai-gateway scoped PAT kept in a secret scope",
        "sdk_serving_query": "Databricks SDK serving_endpoints.query only calls serving endpoints; use the OpenAI "
                             "client on <workspace>/ai-gateway/mlflow/v1 with service principal OAuth (M2M), or an ai-gateway scoped PAT kept in a secret scope",
        "mlflow_deployments_predict": "the MLflow deployments client only calls /serving-endpoints/<name>/invocations; "
                                      "use the OpenAI client on <workspace>/ai-gateway/mlflow/v1",
        "ChatDatabricks": "ChatDatabricks needs model='<model service>' and use_ai_gateway=True "
                          "(databricks-langchain>=0.19.0)",
        "mlflow_endpoint_uri": "endpoints:/ URIs only reach serving endpoints; upgrade MLflow to 3.16+ and use "
                               "databricks:/<model service>",
    }[client]
    hint = f" This file also names {', '.join(names[:3])}, which may be the value." if names else ""
    return (f"manual: the endpoint name comes from a variable, so the scan can't tell which endpoint this calls. If it's "
            f"a legacy endpoint, changing only the name gives a 404: {fixes}. If it's a custom model endpoint, no "
            f"change.{hint}")
# Short or common names ("test", "gpt") only count when the line says what they are for.
GENERIC_NAMES = {"test", "default", "model", "llm", "chat", "prod", "dev", "demo", "embed", "embedding", "endpoint", "main"}
KEY_CONTEXT_RE = re.compile(r"(endpoint|model|serving|llm|embed)\w*['\"]?\s*[:=(,]\s*$", re.I)
MODEL_KEY_RE = re.compile(r"\bmodel\w*['\"]?\s*[:=]\s*$", re.I)  # `model=`, `"model":` just before a name
# Databricks SDK serving_endpoints.query(...): a call the SDK makes to a serving endpoint, not to a gateway route.
SDK_QUERY_RE = re.compile(r"serving_endpoints\s*\.\s*query\s*\(")
# MLflow deployments client (mlflow.deployments.get_deploy_client("databricks")): predict(endpoint=...) always calls
# /serving-endpoints/<endpoint>/invocations, so a Unity Gateway service name can't go there either.
MLFLOW_PREDICT_RE = re.compile(r"\.\s*predict\s*\([^()]*$")  # the name sits inside an open .predict( call
# The workspace /ai-gateway/ routes v2 clients call, with the API type they speak (openai/v1/responses, ...).
GATEWAY_ROUTE_RE = re.compile(r"/ai-gateway/((?:openai|mlflow)/v1(?:/[a-z_]+)*)")
GATEWAY_WINDOW = 400  # characters either side of a name that count as "near" a gateway route
# Legacy regional AI Gateway host (<id>.ai-gateway.<region>.databricks.com, or azuredatabricks.net). The docs and
# code in this repo don't show the exact shape, so the match is kept narrow: an ai-gateway label, then databricks.
REGIONAL_GATEWAY_RE = re.compile(r"https?://[A-Za-z0-9.\-]+\.ai-gateway\.[A-Za-z0-9.\-]*databricks\.(?:com|net)"
                                 r"(?:/[^\s'\"<>)]*)?")
MAX_STORED_LINE = 1000
SECRET_VALUE_RES = [
    re.compile(r"(?<![A-Za-z0-9_\-])(sk-[A-Za-z0-9_\-]{8,}|dapi[0-9a-f]{16,}(-\d+)?|ghp_[A-Za-z0-9]{20,}"
               r"|xox[abp]-[A-Za-z0-9\-]{10,}|AKIA[0-9A-Z]{16})"),
    # A credential-looking name (api_key, DB_PASS, password, secret, token, key, ...) assigned a value, quoted or
    # not. Names match only at word or underscore boundaries, so keyboard or monkey_patch don't.
    re.compile(r"(?i)(\b(?:[a-z0-9]+[_\-])*(?:api[_\-]?key|access[_\-]?key|private[_\-]?key|key|secret|token"
               r"|pass(?:word|wd|phrase)?|passwd|pwd|credential|authorization)(?:[_\-][a-z0-9_\-]*)?\b"
               r"['\"]?\]?\s*[:=]\s*(?:f?['\"](?:Bearer\s+)?|Bearer\s+)?)"
               r"(?!\{\{|Bearer\b)([^'\"\s{},;)\]]{6,})"),
    # Azure-style connection strings: AccountKey=...;  SharedAccessKey=...;
    re.compile(r"(?i)(\b(?:Account|SharedAccess)Key\s*=\s*)([^;'\"\s]{6,})"),
]


def scrub(line: str | None) -> str | None:
    """Hide credential-looking values in a stored code line (keys, tokens, passwords), quoted or not."""
    if not line:
        return line
    for pattern in SECRET_VALUE_RES[1:]:
        line = pattern.sub(lambda m: m.group(1) + "<hidden>", line)
    return SECRET_VALUE_RES[0].sub("<hidden>", line)


MAX_FIX_LINE = 5000


CALL_WINDOW = 4000  # how far into a call's arguments a short or common name still counts as an argument
_CALL_TOKEN_RE = re.compile(r'"""|\'\'\'|"|\'|#|//|--|\(|\)')
# `se = w.serving_endpoints` (an alias of the SDK's serving endpoints API) and the mention of the MLflow client
SERVING_ALIAS_RE = re.compile(r"\b(\w+)\s*=\s*[\w.]*\bserving_endpoints\b(?![\w.(])")
DEPLOY_CLIENT_MENTION_RE = re.compile(r"\bget_deploy_client\b")  # also `import get_deploy_client as gdc`


def _escaped(text: str, i: int) -> bool:
    """True if the character at i is preceded by an odd number of backslashes."""
    n = 0
    while i - 1 - n >= 0 and text[i - 1 - n] == "\\":
        n += 1
    return n % 2 == 1


def _call_still_open(text: str, start: int, at: int) -> bool:
    """True if the call whose "(" ends at start is still open at position at. Parentheses inside strings (single,
    double, triple quoted) and comments (# // --) don't count, so `content="Rules: 1) be brief"` doesn't close the
    call. Uncertain cases (a string or comment that runs to at) read as still open: the safe direction, because a
    name counted by mistake is a warning, while a name missed can list an endpoint under "Can be closed now"."""
    depth, i = 1, start
    while i < at:
        m = _CALL_TOKEN_RE.search(text, i, at)
        if not m:
            return True
        tok, i = m.group(), m.end()
        if tok in ('"""', "'''", '"', "'"):
            while True:
                j = text.find(tok, i, at)
                if j == -1:
                    return True
                i = j + len(tok)
                if not _escaped(text, j):
                    break
        elif tok in ("#", "//", "--"):
            nl = text.find("\n", i, at)
            if nl == -1:
                return True
            i = nl + 1
        elif tok == "(":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return False
    return True


class _CallContext:
    """Where a name sits relative to calls in one file. Everything is computed lazily and once per file, so a file
    with thousands of short-name matches costs one pass for each call kind, not one per match."""

    def __init__(self, text: str):
        self.text = text
        self._ends: dict[str, list[int]] = {}
        self._deploy: bool | None = None
        self._sdk_re: re.Pattern | None = None

    def uses_deploy_client(self) -> bool:
        """The file mentions get_deploy_client (the MLflow deployments client): its .predict( calls hit
        /serving-endpoints. Any model has a .predict, so this is what makes a predict( call count."""
        if self._deploy is None:
            self._deploy = bool(DEPLOY_CLIENT_MENTION_RE.search(self.text))
        return self._deploy

    def _sdk_query_re(self) -> re.Pattern:
        if self._sdk_re is None:
            aliases = sorted(set(SERVING_ALIAS_RE.findall(self.text)))
            if aliases:
                alt = "|".join(re.escape(a) for a in aliases)
                self._sdk_re = re.compile(SDK_QUERY_RE.pattern + r"|\b(?:" + alt + r")\s*\.\s*query\s*\(")
            else:
                self._sdk_re = SDK_QUERY_RE
        return self._sdk_re

    def _inside(self, key: str, regex: re.Pattern, at: int) -> bool:
        ends = self._ends.get(key)
        if ends is None:
            ends = self._ends[key] = [m.end() for m in regex.finditer(self.text)]
        k = bisect.bisect_right(ends, at) - 1  # right: a "(" that ends where the name starts, query("llm"), counts
        while k >= 0 and at - ends[k] <= CALL_WINDOW:  # the nearest calls first; a closed one may precede an open one
            if _call_still_open(self.text, ends[k], at):
                return True
            k -= 1
        return False

    def in_sdk_query(self, at: int) -> bool:
        return self._inside("sdk", self._sdk_query_re(), at)

    def in_predict(self, at: int) -> bool:
        return self._inside("predict", PREDICT_CALL_RE, at)


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
    def __init__(self, endpoint_names: Iterable[str], sys_map: dict[str, str], plan_rows: list[PlanRow],
                 endpoint_urls: dict[str, str] | None = None, v2_names: Iterable[str] | None = None,
                 target_api_types: dict[str, list[str]] | None = None,
                 custom_models: dict[str, str] | None = None):
        self.names = {n for n in endpoint_names if n}
        # Custom endpoint -> the UC model it serves, to tie calls inside MLflow model code to the endpoint.
        self.custom_models = {e: m for e, m in (custom_models or {}).items() if e and m}
        self.v2_names = {n for n in (v2_names or []) if n}  # workspace-bound v2 endpoints (route + model name)
        # supported_api_types of each system.ai target: a v2 route the target can't serve is a manual decision.
        self.target_api_types = target_api_types or {}
        self.generic = {n for n in self.names if len(n) < 6 or n.lower() in GENERIC_NAMES}
        # Host of each route-optimized endpoint URL -> endpoint name.
        self.url_hosts = {urlsplit(u).netloc: n for u, n in (endpoint_urls or {}).items() if u and n}
        self.sys_map = sys_map
        self.targets = {r.legacy_endpoint: r.target_service for r in plan_rows if r.target_service}
        # Custom model endpoints stay on legacy serving: their callers need no change.
        self.custom = {r.legacy_endpoint for r in plan_rows if r.kind in ("custom_model", "agent")}
        self.agent_bricks: dict[str, str] = {}  # serving endpoint -> "knowledge assistant X" / "supervisor agent Y"
        alt = "|".join(sorted((re.escape(n) for n in self.names), key=len, reverse=True))
        # Quoted legacy endpoint names; longest first so similar names don't shadow each other.
        self.name_re = re.compile(r"(['\"])(" + alt + r")\1") if self.names else None
        # Unquoted config values (YAML / HCL / .env, optionally "export NAME=") under endpoint-like keys.
        self.config_re = re.compile(r"^(\s*-?\s*(?:export\s+)?([\w.\-]+)\s*[:=]\s*)(" + alt + r")\s*(?:#.*)?$") \
            if self.names else None
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
            return (f"ai_query('{target}', ...); caveat: on Unity Gateway, ai_query applies usage tracking only "
                    "(no rate limits, fallbacks, inference tables or service policies)")
        if target:
            return (f"ai_query can't call Unity Gateway model services yet; keep {name} until it can, "
                    "or use a system.ai model")
        if name.startswith("databricks-"):
            return f"{name} has no system.ai model service (likely retired); pick a current system.ai model"
        return "map to a system.ai model service"

    def _ai_query_variable_suggestion(self, name: str) -> str:
        target = self._target_for(name)
        return (f"manual: this file calls ai_query, and {name} may reach it through a variable. ai_query only calls "
                "system.ai model services, so for ai_query set the variable to a system.ai model (or keep "
                f"{name} until ai_query can call Unity Gateway model services); other clients can use "
                f"'{target or '<model service>'}' on /ai-gateway/")

    def _mlflow_predict_suggestion(self, name: str) -> str:
        target = self._target_for(name)
        return (f"manual: the MLflow deployments client calls /serving-endpoints/{name}/invocations, which has no "
                "Unity Gateway form, so use the OpenAI client on <workspace>/ai-gateway/mlflow/v1 with "
                f"model='{target or '<model service>'}' and an ai-gateway scoped token")

    def _sdk_query_suggestion(self, name: str) -> str:
        target = self._target_for(name)
        return (f"manual: Databricks SDK serving_endpoints.query calls {name}. databricks-sdk 0.158.0 has no Unity "
                "Gateway query method (ServingEndpointsAPI.query only targets serving endpoints), so use the OpenAI "
                f"client on <workspace>/ai-gateway/mlflow/v1 with model='{target or '<model service>'}' and an "
                "ai-gateway scoped token")

    @staticmethod
    def _nearest_route(window: str, pos: int) -> str | None:
        """The API type of the /ai-gateway/ route closest to pos in window, e.g. openai/v1/responses."""
        best = None
        for m in GATEWAY_ROUTE_RE.finditer(window):
            d = abs(m.start() - pos)
            if best is None or d < best[0]:
                best = (d, m.group(1))
        return best[1] if best else None

    def _v2_model(self, asset_type, asset, line_no, token, name, text, at) -> None:
        """A v2 workspace endpoint's plain model name near an /ai-gateway/ route: rename it to the system.ai model.

        The route stays. If the target doesn't support the route's API type, the rename is not proposed (manual)."""
        target = self._target_for(name)
        start = max(0, at - GATEWAY_WINDOW)
        route = self._nearest_route(text[start:at + GATEWAY_WINDOW], at - start)
        supported = self.target_api_types.get(target) if target else None
        if not target:
            self._add(asset_type, asset, line_no, "v2_gateway_model", token, name,
                      f"{name} is a workspace-bound v2 endpoint with no system.ai model: pick a replacement model",
                      fixable=False)
        elif route and len(route.split("/")) >= 3 and supported is not None and route not in supported:
            self._add(asset_type, asset, line_no, "v2_gateway_model", token, name,
                      f"manual: {target} doesn't support {route} (supported_api_types: {', '.join(supported) or 'none'}). "
                      "Keep the route and pick a model that supports it; never move a Responses client to Chat Completions",
                      fixable=False)
        else:
            check = ("" if supported is not None or not route else
                     f"; could not read the supported API types of {target}, so check {route} by hand")
            self._add(asset_type, asset, line_no, "v2_gateway_model", token, name,
                      f"v2 workspace endpoint on the /ai-gateway/ route: set model to '{target}' and keep the route "
                      "(never switch a Responses route to Chat Completions)" + check)

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
        first = len(self.refs)
        self._scan_lines(asset_type, asset, text)
        self._mark_model_code(text, self.refs[first:])

    def _mark_model_code(self, text: str, refs: list) -> None:
        """Calls inside MLflow model code (a PythonModel or agent class) run inside the serving endpoint that serves it.

        Under automatic authentication a Unity Gateway call from there fails with a misleading NotFound, so the fix
        is a re-logged model with explicit credentials (or an app), and the endpoint's own callers don't change."""
        models = model_classes(text)
        if not models:
            return
        served = served_by(text, self.custom_models)
        for x in refs:
            cls = next((c for c, (start, end) in models.items() if x.line and start <= x.line <= end), None)
            if cls and x.pattern != "custom_endpoint_call":
                x.suggestion += model_code_note(cls, served.get(cls))

    def _scan_lines(self, asset_type: str, asset: str, text: str) -> None:
        lines = text.split("\n")
        ctx = _CallContext(text)

        def line_of(pos: int) -> int:
            return text.count("\n", 0, pos) + 1

        # Calls that can span lines: record (line -> [(pattern, name, token)]).
        # (pattern, name, token, split): split is True when the ChatDatabricks( call starts on another line.
        spanning: dict[int, list[tuple[str, str, str, bool]]] = {}
        for m in AI_QUERY_RE.finditer(text):
            name = m.group(2)
            if name.startswith("system.ai.") or name.count(".") == 2:
                continue
            spanning.setdefault(line_of(m.start(2)), []).append(("ai_query", name, m.group(1) + name + m.group(1), False))
        for m in CHAT_DATABRICKS_START_RE.finditer(text):
            args = _balanced_args(text, m.end() - 1)
            a = CHAT_DATABRICKS_ARG_RE.search(args)
            if a and a.group(3) in self.names:
                pos = m.end() + a.start(3)
                arg_line = line_of(pos)
                spanning.setdefault(arg_line, []).append(
                    ("ChatDatabricks", a.group(3), a.group(2) + a.group(3) + a.group(2),
                     arg_line != line_of(m.start())))
        variable = self._variable_calls(text, line_of)
        file_names = sorted({m.group(2) for m in self.name_re.finditer(text)} - self.custom) if self.name_re else []

        in_endpoint_block = 0  # lines left inside a YAML "serving_endpoint:" mapping
        previous = ""
        offset = 0  # position in text of the current line's first character
        for i, line in enumerate(lines, start=1):
            line_start, offset = offset, offset + len(line) + 1
            self._line = line
            # app.yaml env entries: "- name: MODEL_ENDPOINT" then "value: my-llm" on the next line.
            name_on_previous = re.match(r"^\s*-?\s*name\s*:\s*['\"]?([\w.\-]+)", previous)
            previous = line
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
            for pattern, name, token, split in spanning.get(i, []):
                if pattern == "ai_query":
                    self._add(asset_type, asset, i, "ai_query", token, name, self._ai_query_suggestion(name))
                else:
                    # The fix changes only the line with the name; on a multi-line call, use_ai_gateway goes on the call.
                    where = (" The ChatDatabricks( call spans lines: the fix changes only the model line, so add "
                             "use_ai_gateway=True to the call's arguments by hand." if split else "")
                    self._add(asset_type, asset, i, "ChatDatabricks", token, name,
                              "databricks-langchain>=0.19.0 (use_ai_gateway needs it): model="
                              f"'{self._target_for(name) or '<model service>'}' and use_ai_gateway=True; "
                              "check the current databricks-langchain docs for the endpoint= argument." + where)
                hits.add(name)
            for pattern, token in variable.get(i, []):
                advice = (TABULAR_CALL_SUGGESTION if pattern == "tabular_endpoint_call"
                          else variable_call_suggestion(pattern, file_names))
                self._add(asset_type, asset, i, pattern, token, None, advice, fixable=False)
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
                elif not name and DYNAMIC_URL_RE.search(line):
                    self._add(asset_type, asset, i, "serving_endpoints_url", m.group(0), None, DYNAMIC_URL_SUGGESTION)
                else:
                    target = self._target_for(name)
                    suggestion = ("use <workspace-url>/ai-gateway/mlflow/v1 with model="
                                  f"'{target or '<catalog>.<schema>.<service>'}' and an ai-gateway scoped token")
                    if name and m.group(3) == "/invocations":
                        suggestion += ("; embedding endpoint: /embeddings keeps the input format" if EMBEDDING_RE.search(name)
                                       else "; the /invocations body changes to OpenAI chat format (messages, model): "
                                            "edit the request by hand")
                    self._add(asset_type, asset, i, "serving_endpoints_url", m.group(0), name, suggestion)
                if name:
                    hits.add(name)
            for m in ROUTE_URL_RE.finditer(line):
                url = m.group(0).rstrip(".,;")
                name = self.url_hosts.get(urlsplit(url).netloc)
                self._add(asset_type, asset, i, "serving_endpoint_route_url", url, name,
                          f"route-optimized endpoint {name}: its own URL goes away with the endpoint; call "
                          "/ai-gateway/ instead" if name else "route-optimized endpoint URL not matched to a listed "
                          "endpoint: check which endpoint it calls")
                if name:
                    hits.add(name)
            for m in REGIONAL_GATEWAY_RE.finditer(line):
                self._add(asset_type, asset, i, "ai_gateway_regional_host", m.group(0).rstrip(".,;"), None,
                          "legacy regional AI Gateway host: move to the workspace /ai-gateway/ route; an ai-gateway "
                          "scoped PAT is enough there (the regional host needs all-apis)")
            if self.config_re:
                m = self.config_re.match(line)
                key = m.group(2) if m else ""
                if m and key == "value" and name_on_previous:
                    key = name_on_previous.group(1)  # the value of the env entry named on the line above
                if m and m.group(3) not in hits and CONFIG_KEY_RE.search(key):
                    self._add(asset_type, asset, i, "config_value", m.group(3), m.group(3),
                              f"replace with {self._target_for(m.group(3)) or '<model service>'} "
                              "(config value; check what reads it)")
                    hits.add(m.group(3))
            if self.name_re:
                for m in self.name_re.finditer(line):
                    name = m.group(2)
                    if name in hits:
                        continue
                    at = line_start + m.start()
                    in_sdk_query = bool(SDK_QUERY_RE.search(text[max(0, at - GATEWAY_WINDOW):at]))
                    # Same line, as before; or inside an open predict( that spans lines, in a file that uses the MLflow
                    # deployments client (that client's predict always calls /serving-endpoints, so no gateway rewrite).
                    in_predict = bool(MLFLOW_PREDICT_RE.search(line[:m.start()])) \
                        or (ctx.uses_deploy_client() and ctx.in_predict(at))
                    if name in self.generic and not KEY_CONTEXT_RE.search(line[:m.start()]):
                        # A short or common name needs a key or call context to count: inside the arguments of a
                        # serving_endpoints.query(...) call, or of a predict(...) call in a file that uses the
                        # MLflow deployments client (any model has a .predict).
                        in_sdk_query = ctx.in_sdk_query(at)
                        in_predict = (in_predict or ctx.in_predict(at)) and ctx.uses_deploy_client()
                        if not (in_sdk_query or in_predict):
                            continue
                    if in_sdk_query:
                        # Never rewritten: the SDK call has no gateway form to map onto (see the suggestion).
                        self._add(asset_type, asset, i, "sdk_serving_query", m.group(0), name,
                                  self._sdk_query_suggestion(name), fixable=False)
                    elif in_predict:
                        # Never rewritten: the MLflow deployments client only reaches /serving-endpoints/.
                        self._add(asset_type, asset, i, "mlflow_deployments_predict", m.group(0), name,
                                  self._mlflow_predict_suggestion(name), fixable=False)
                    elif name in self.v2_names and MODEL_KEY_RE.search(line[:m.start()]) \
                            and "/ai-gateway/" in text[max(0, at - GATEWAY_WINDOW):at + GATEWAY_WINDOW]:
                        self._v2_model(asset_type, asset, i, m.group(0), name, text, at)
                    elif AI_QUERY_CALL_RE.search(text) and not (self._target_for(name) or "").startswith("system.ai."):
                        # The name likely feeds ai_query through a variable. ai_query only calls system.ai services,
                        # so a custom model service name would break it: never rewritten.
                        self._add(asset_type, asset, i, "legacy_endpoint_name", m.group(0), name,
                                  self._ai_query_variable_suggestion(name), fixable=False)
                    else:
                        self._add(asset_type, asset, i, "legacy_endpoint_name", m.group(0), name,
                                  f"replace with '{self._target_for(name) or '<model service>'}' "
                                  "(and move the client to /ai-gateway/)")
                    hits.add(name)

    @staticmethod
    def _name_value(args: str, keys: tuple[str, ...]) -> str | None:
        """The raw value of the first keyword argument in keys, else the first positional argument."""
        for m in NAME_ARG_RE.finditer(args):
            if m.group(1) in keys:
                return m.group(2)
        first = args.split(",")[0].strip()
        return first if first and "=" not in first else None

    @staticmethod
    def _is_variable(value: str | None) -> bool:
        """True for a name, attribute, call or f-string; False for a quoted literal or nothing."""
        if not value:
            return False
        if value[0] in "'\"":
            return False
        return bool(re.match(r"[A-Za-z_]", value))

    def _variable_calls(self, text: str, line_of) -> dict[int, list[tuple[str, str]]]:
        """Client calls whose endpoint name isn't a literal: line -> [(pattern, token)].

        Literal names are left to the per-name checks (and literals that aren't legacy names are not our business)."""
        out: dict[int, list[tuple[str, str]]] = {}

        def add(pos: int, pattern: str, token: str) -> None:
            out.setdefault(line_of(pos), []).append((pattern, token))

        for m in OPENAI_CLIENT_RE.finditer(text):
            add(m.start(), "sdk_openai_client", m.group(0).rstrip("( "))
        for m in SDK_QUERY_RE.finditer(text):
            args = _balanced_args(text, m.end() - 1)
            if self._is_variable(self._name_value(args, ("name",))):
                tabular = TABULAR_ARG_RE.search(args)
                # The name is unknown, so it stays a finding (a warning): the input shape only suggests a custom model.
                add(m.start(), "tabular_endpoint_call" if tabular else "sdk_serving_query", "serving_endpoints.query")
        if DEPLOY_CLIENT_RE.search(text):
            for m in PREDICT_CALL_RE.finditer(text):
                args = _balanced_args(text, m.end() - 1)
                if "endpoint" in args and self._is_variable(self._name_value(args, ("endpoint",))):
                    add(m.start(), "mlflow_deployments_predict", "predict(endpoint=...)")
        for m in CHAT_DATABRICKS_START_RE.finditer(text):
            args = _balanced_args(text, m.end() - 1)
            if "use_ai_gateway" not in args and self._is_variable(self._name_value(args, ("endpoint", "model"))):
                add(m.start(), "ChatDatabricks", "ChatDatabricks(")
        for m in DYNAMIC_MLFLOW_URI_RE.finditer(text):
            add(m.start(), "mlflow_endpoint_uri", "endpoints:/{...}")
        return out

    def _add(self, asset_type, asset, line, pattern, match, legacy_endpoint, suggestion, fixable: bool = True) -> None:
        if legacy_endpoint in self.custom and pattern in CUSTOM_CALL_PATTERNS:
            pattern, suggestion, fixable = "custom_endpoint_call", custom_endpoint_suggestion(legacy_endpoint), False
        if legacy_endpoint and EMBEDDING_RE.search(legacy_endpoint) and asset_type != "vector_search_index":
            suggestion += ("; embedding model: if this feeds an AI Search index, keep it until AI Search "
                           "supports a system.ai embedding service for it")
        line_text = getattr(self, "_line", None) if line else None
        fixed, confidence = (None, None)
        if line_text is not None and fixable and len(line_text) <= MAX_FIX_LINE:
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
        """Propose a rewritten line. Every proposal is 'review': the new line needs a human check (ai_query
        and MLflow changes switch execution path, so they carry caveats in the suggestion)."""
        target = self._target_for(name)
        quoted = lambda t: match[0] + t + match[-1]  # noqa: E731
        if pattern == "ai_query" and target and target.startswith("system.ai."):
            new = self._replace_token(line, match, quoted(target), after="ai_query")
            return (new.strip(), "review") if new else (None, None)
        if pattern == "mlflow_endpoint_uri" and target:
            new = self._replace_token(line, match, f"databricks:/{target}")
            return (new.strip(), "review") if new else (None, None)
        if pattern == "config_value" and target and self.config_re:
            m = self.config_re.match(line)
            if m:
                return (line[:m.start(3)] + target + line[m.end(3):]).strip(), "review"
        if pattern in ("legacy_endpoint_name", "v2_gateway_model") and target:
            new = self._replace_token(line, match, quoted(target))
            return (new.strip(), "review") if new else (None, None)
        if pattern == "ChatDatabricks" and target:
            # databricks-langchain: `model` is the documented argument; check its docs before keeping `endpoint`.
            kw = re.search(r"\bendpoint(\s*=\s*)" + re.escape(match), line)
            new = (line[:kw.start()] + "model" + kw.group(1) + quoted(target) + line[kw.end():]) if kw \
                else self._replace_token(line, match, quoted(target))
            if new and "use_ai_gateway" not in new and "ChatDatabricks(" in new and new.rstrip().endswith(")"):
                new = new.rstrip()[:-1].rstrip().rstrip(",") + ", use_ai_gateway=True)"
            return (new.strip(), "review") if new else (None, None)
        if pattern == "serving_endpoints_url":
            if DYNAMIC_URL_RE.search(line):
                return None, None  # the endpoint name is built at run time: no safe rewrite
            if OPENAI_ROUTE_RE.search(match):
                return OPENAI_ROUTE_RE.sub(r"/ai-gateway/mlflow/v1/\1", line, count=1).strip(), "review"
            if name and target:
                if match.endswith(f"/{name}/invocations"):
                    if EMBEDDING_RE.search(name):
                        return line.replace(match, "/ai-gateway/mlflow/v1/embeddings", 1).strip(), "review"
                    return None, None  # chat-style body change: described in the suggestion, edit by hand
                if match == f"/serving-endpoints/{name}":
                    return line.replace(match, "/ai-gateway/mlflow/v1", 1).strip(), "review"
                return None, None
            if match == "/serving-endpoints":
                return line.replace(match, "/ai-gateway/mlflow/v1", 1).strip(), "review"
        return None, None


TOOLKIT_MARKERS = {"ug_migration_planner.py", "ug_migration_toolkit.marker"}
TOOLKIT_APP_DESCRIPTION = "Unity Gateway Migration Toolkit"  # every toolkit app's description starts with this
TOOLKIT_BUNDLE = "unity-gateway-migration-toolkit"  # bundle.name in databricks.yml
TOOLKIT_NOTE = "the toolkit's own install (its files name legacy endpoints on purpose)"
# Binary and media files: never source code, so leaving them out is not reported as a coverage note.
BINARY_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".bmp", ".pdf", ".zip", ".gz", ".tgz",
               ".tar", ".whl", ".jar", ".egg", ".so", ".dylib", ".dll", ".exe", ".bin", ".pyc", ".class", ".parquet",
               ".avro", ".orc", ".delta", ".pkl", ".pickle", ".pt", ".pth", ".onnx", ".safetensors", ".h5", ".npy",
               ".npz", ".xlsx", ".xls", ".docx", ".pptx", ".mp4", ".mp3", ".wav", ".woff", ".woff2", ".ttf", ".otf",
               ".lock", ".dbc"}


def _count_skipped_type(counts: dict[str, int], path: str) -> None:
    """Count a file left out of the scan by its extension, unless it's a binary or media file."""
    name = path.rsplit("/", 1)[-1].rsplit(os.sep, 1)[-1]
    ext = os.path.splitext(name)[1].lower() or "(no extension)"
    if ext not in BINARY_EXTS:
        counts[ext] = counts.get(ext, 0) + 1


def _skipped_note(dirs: list[str], types: dict[str, int]) -> str | None:
    """Coverage note for what a walk left out on purpose (dependency/build folders, other file types), or None."""
    parts = []
    if dirs:
        names = sorted({d.rstrip("/").rsplit("/", 1)[-1].rsplit(os.sep, 1)[-1] for d in dirs})
        parts.append(f"{_n(len(dirs), 'dependency or build folder')} ({', '.join(names[:6])})")
    if types:
        top = sorted(types.items(), key=lambda kv: (-kv[1], kv[0]))
        parts.append(f"{_n(sum(types.values()), 'file')} of other types ("
                     + ", ".join(f"{ext} {n}" for ext, n in top[:6]) + (" ..." if len(top) > 6 else "") + ")")
    return f"{NOT_SCANNED}: " + "; ".join(parts) if parts else None


def _walk_workspace(w: WorkspaceClient, roots: list[str], max_objects: int, threads: int = 16,
                    accept=None, skip_prefixes: Iterable[str] = ()) -> list[dict]:
    """List notebooks and files under the roots, one directory level at a time in parallel.

    Dependency and build folders (SKIP_DIRS) are not entered, and only objects that accept() takes count
    toward max_objects. The budget applies per root, so one big folder can't use up the others. Folders
    under skip_prefixes (the toolkit apps' source and deployment copies) are skipped like the install.
    """
    skip_prefixes = tuple(p.rstrip("/") for p in skip_prefixes if p)

    def toolkit_path(path: str) -> bool:
        return any(path == p or path.startswith(p + "/") for p in skip_prefixes)

    from concurrent.futures import ThreadPoolExecutor

    failures: list[str] = []

    def ls(path):
        try:
            return _get(w, "/api/2.0/workspace/list", {"path": path}).get("objects", [])
        except Exception as error:
            if "RESOURCE_DOES_NOT_EXIST" not in str(error) and "doesn't exist" not in str(error):
                failures.append(path)
            return []

    roots = list(dict.fromkeys(roots))
    skipped = [r for r in roots if toolkit_path(r)]
    unverified: list[str] = []  # folders with toolkit files that no verified toolkit app uses
    roots = [r for r in roots if not toolkit_path(r)]
    found, level, seen_dirs = [], [(r, r) for r in roots], set()
    skipped_dirs: list[str] = []  # dependency and build folders not entered
    skipped_types: dict[str, int] = {}  # extension -> files left out because accept() refused them
    counts = {r: 0 for r in roots}  # accepted objects per root
    with ThreadPoolExecutor(max_workers=threads) as pool:
        while level:
            live = [(root, path) for root, path in level if counts[root] < max_objects]
            next_level = []
            for (root, path), objects in zip(live, pool.map(ls, [p for _, p in live])):
                # The toolkit's own install (its files mention legacy endpoint names on purpose): skip it. A folder
                # with toolkit files that no verified toolkit app uses (is_toolkit_app) is skipped too, but as a
                # coverage gap: those file names prove nothing, so a caller could hide there.
                names = {o.get("path", "").rsplit("/", 1)[-1] for o in objects}
                if names & TOOLKIT_MARKERS:
                    (skipped if any(p == path or p.startswith(path + "/") for p in skip_prefixes)
                     else unverified).append(path)
                    continue
                for o in objects:
                    t = o.get("object_type")
                    if t in ("DIRECTORY", "REPO"):
                        if o["path"] in seen_dirs:
                            continue
                        if toolkit_path(o["path"]):
                            skipped.append(o["path"])
                            continue
                        if o["path"].rsplit("/", 1)[-1] in SKIP_DIRS:
                            skipped_dirs.append(o["path"])
                            continue
                        seen_dirs.add(o["path"])
                        next_level.append((root, o["path"]))
                    elif t in ("NOTEBOOK", "FILE") and accept is not None and not accept(o):
                        _count_skipped_type(skipped_types, o.get("path", ""))
                    elif t in ("NOTEBOOK", "FILE") and counts[root] < max_objects:
                        counts[root] += 1
                        found.append(o)
            level = next_level
    _walk_workspace.last_failures = failures
    _walk_workspace.skipped = skipped
    _walk_workspace.unverified = unverified
    _walk_workspace.skipped_dirs = skipped_dirs
    _walk_workspace.skipped_types = skipped_types
    if skipped:
        _log(f"  skipped the toolkit's own folders: {', '.join(skipped[:5])}")
    _walk_workspace.truncated = any(c >= max_objects for c in counts.values())
    if _walk_workspace.truncated:
        _log(f"  stopped after {max_objects} workspace objects per root (raise --max-objects)")
    if failures:
        _log(f"  could not list {len(failures)} folders")
    return found


def _decode(raw: bytes) -> str | None:
    """Decode text files, including UTF-16 with a BOM; None for binary content."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="ignore")
    if b"\x00" in raw[:4096]:
        return None
    return raw.decode("utf-8", errors="ignore")


def scan_workspace(w: WorkspaceClient, scanner: Scanner, roots: list[str], max_objects: int, threads: int = 16,
                   skip_prefixes: Iterable[str] = ()) -> None:
    """Export notebooks and text files in parallel and scan each distinct content once.

    Databricks Apps keep a copy of the source per deployment under
    /Workspace/Users/<sp>/src/<id>/, so identical files are reported once with
    a count of copies.
    """
    import hashlib
    from concurrent.futures import ThreadPoolExecutor

    objs = _walk_workspace(w, roots, max_objects, threads,
                           accept=lambda o: o["object_type"] == "NOTEBOOK" or o["path"].lower().endswith(WORKSPACE_EXTS),
                           skip_prefixes=skip_prefixes)

    if getattr(_walk_workspace, "truncated", False):
        scanner.note("workspace_files", f"truncated at {max_objects} objects per root")
    if getattr(_walk_workspace, "last_failures", None):
        scanner.note("workspace_files", f"partial: {len(_walk_workspace.last_failures)} folders unreadable")
    if getattr(_walk_workspace, "unverified", None):
        folders = sorted(_walk_workspace.unverified)
        scanner.note("workspace_files", f"partial: {_n(len(folders), 'folder')} skipped: they hold toolkit files, but "
                                        "no toolkit app installed here uses them, so check them by hand: "
                                        + ", ".join(folders[:5]) + (" ..." if len(folders) > 5 else ""))
    if getattr(_walk_workspace, "skipped", None):
        # A verified toolkit install, skipped on purpose like dependency folders: a note, not a coverage gap.
        folders = sorted(_walk_workspace.skipped)
        scanner.note("toolkit_install", f"{NOT_SCANNED}: {_n(len(folders), 'folder')}, {TOOLKIT_NOTE}: "
                                        + ", ".join(folders[:5]) + (" ..." if len(folders) > 5 else ""))
    left_out = _skipped_note(getattr(_walk_workspace, "skipped_dirs", []), getattr(_walk_workspace, "skipped_types", {}))
    if left_out:
        scanner.note("workspace_files_skipped", left_out)
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
        paths = by_hash[h]
        label = o["path"] + (f" (+{len(paths) - 1} identical copies)" if len(paths) > 1 else "")
        before = len(scanner.refs)
        scanner.scan_text("notebook" if o["object_type"] == "NOTEBOOK" else "file", label, text)
        for r in scanner.refs[before:]:
            r.also_in = paths[1:]  # callers in any copy's folder still link to the references
    if export_failures:
        scanner.note("workspace_files", f"partial: {len(export_failures)} files unreadable")
    scanner.note("workspace_files", "ok")
    _log(f"  scanned {len(objs)} notebooks and files ({len(texts)} distinct)")


SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build", ".terraform",
             ".mypy_cache", ".pytest_cache", ".idea", ".vscode", "target", ".databricks"}
LOCAL_EXTS = (".py", ".sql", ".scala", ".r", ".ipynb", ".yml", ".yaml", ".json", ".toml", ".js", ".ts", ".tsx",
              ".jsx", ".java", ".go", ".cs", ".txt", ".sh", ".cfg", ".ini", ".env", ".tf", ".tfvars", ".hcl",
              ".properties", ".conf")
WORKSPACE_EXTS = (".py", ".sql", ".scala", ".r", ".ipynb", ".yml", ".yaml", ".json", ".toml", ".js", ".ts", ".tsx",
                  ".jsx", ".java", ".go", ".txt", ".md", ".sh", ".cfg", ".ini", ".conf", ".properties", ".env",
                  ".tf", ".tfvars", ".hcl")


def scan_local(scanner: Scanner, paths: list[str], max_bytes: int = 2_000_000) -> None:
    """Scan local folders (cloned Git repos, bundle projects, Terraform) for legacy references.

    Skips dependency and build folders and binary files. Files over max_bytes are not scanned and
    make the local_files coverage partial. Identical files are scanned once and reported with a copy count.
    """
    import hashlib

    by_hash: dict[str, list[str]] = {}
    texts: dict[str, tuple[str, str]] = {}
    files = oversize = 0
    skipped_dirs: list[str] = []
    skipped_types: dict[str, int] = {}
    for root_path in paths:
        root_path = os.path.abspath(os.path.expanduser(root_path))
        for root, dirs, names in os.walk(root_path):
            skipped_dirs += [os.path.join(root, d) for d in dirs if d in SKIP_DIRS]
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for n in names:
                if not n.lower().endswith(LOCAL_EXTS) and n not in ("Dockerfile", "databricks.yml", ".env"):
                    _count_skipped_type(skipped_types, n)
                    continue
                path = os.path.join(root, n)
                try:
                    if os.path.getsize(path) > max_bytes:
                        oversize += 1
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
    if oversize:
        scanner.note("local_files", f"partial: {oversize} files over {max_bytes // 1_000_000} MB not scanned")
    left_out = _skipped_note(skipped_dirs, skipped_types)
    if left_out:
        scanner.note("local_files_skipped", left_out)
    for h, (rel, text) in texts.items():
        paths_for = by_hash[h]
        before = len(scanner.refs)
        scanner.scan_text("local_file", rel + (f" (+{len(paths_for) - 1} identical copies)" if len(paths_for) > 1 else ""),
                          text)
        for r in scanner.refs[before:]:
            r.also_in = paths_for[1:]
    scanner.note("local_files", "ok" if all(os.path.isdir(os.path.expanduser(p)) for p in paths)
                 else "failed: a --local-path folder doesn't exist")
    _log(f"  scanned {files} local files ({len(texts)} distinct) under {', '.join(paths)}")


MAX_TOOL_PAGES = 100  # a Supervisor Agent's tool pages read at most this many (100 tools each)


def supervisor_tools(w: WorkspaceClient, parent: str) -> list[dict]:
    """A Supervisor Agent's tools as the API returns them: every tool type with its spec, all pages.

    The SDK's typed Tool keeps the specs of only some tool types (knowledge_assistant, genie_space, app, ...), and
    drops the ones for vector_search_index, serving_endpoint and supervisor_agent, so the raw JSON is what shows
    what a Supervisor depends on. There is no fallback to the typed tools: without those specs a dependent
    Supervisor would read clean. A failure raises, and the caller counts the Supervisor as unreadable (a coverage
    gap). A page is tried twice, so one transient error doesn't make the scan incomplete."""
    out, token, seen = [], None, set()
    for _ in range(MAX_TOOL_PAGES):
        query = {"page_size": 100, **({"page_token": token} if token else {})}
        for attempt in (1, 2):
            try:
                page = _get(w, f"/api/2.1/{parent}/tools", query)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2)
        if not isinstance(page, dict):
            raise ValueError(f"unexpected response listing the tools of {parent}")
        out += [t for t in page.get("tools") or [] if isinstance(t, dict)]
        token = page.get("next_page_token")
        if not isinstance(token, str) or not token or token in seen:  # last page, or a token that repeats
            return out
        seen.add(token)
    return out


_TOOL_BOOKKEEPING = ("name", "tool_id", "id", "description", "tool_type")


def _tool_strings(tool: dict) -> list[str]:
    """Every string value in a tool's spec (the field named like its tool_type; else every nested value but the
    tool's own bookkeeping), so a tool is matched by what it points at without knowing the spec's field names."""
    kind = tool.get("tool_type")
    spec = tool.get(kind) if isinstance(kind, str) else None
    roots = [spec] if spec is not None else [v for k, v in tool.items() if k not in _TOOL_BOOKKEEPING]
    out: list[str] = []

    def walk(x):
        if isinstance(x, str):
            out.append(x)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    for r in roots:
        walk(r)
    return out


def _names_in(strings: list[str], ref: str) -> bool:
    """True if ref is one of the strings, or a path segment of one (serving-endpoints/<name>/invocations, a URL)."""
    for s in strings:
        if s == ref or ref in re.split(r"[/?#:]", s):
            return True
    return False


def supervisor_dependencies(supervisors: dict[str, dict], kas: dict[str, str],
                            ka_endpoints: dict[str, str]) -> dict[str, list[tuple[str, str, str]]]:
    """The Supervisor Agents that depend on AI Search, with why: {supervisor name: [(pattern, target, text)]}.

    Agent Bricks agents that depend on AI Search don't work with Enforce on. A Supervisor depends on it through:
    a knowledge_assistant tool (every Knowledge Assistant does), a vector_search_index tool, a serving_endpoint
    tool that is a Knowledge Assistant's endpoint (or another dependent Supervisor's), or a supervisor_agent tool
    (or an endpoint tool) pointing at a dependent Supervisor. Nested Supervisors are followed until nothing changes.
    supervisors is {name: {"label", "endpoint", "tools": [raw tool dicts]}}; kas {Knowledge Assistant name: display}."""
    by_ref: dict[str, str] = {}  # every way a tool can name a Supervisor -> its name
    for name, info in supervisors.items():
        display = str(info.get("label") or "").removeprefix("supervisor agent ")
        for ref in (name, name.rsplit("/", 1)[-1], info.get("endpoint"), display):
            if ref:
                by_ref[ref] = name
    found: dict[str, list[tuple[str, str, str]]] = {}

    def add(name: str, pattern: str, target: str, text: str) -> bool:
        if any(p == pattern and t == target for p, t, _ in found.get(name, [])):
            return False
        found.setdefault(name, []).append((pattern, target, text))
        return True

    for name, info in supervisors.items():  # direct dependencies
        for t in info["tools"]:
            kind, tool = t.get("tool_type"), t.get("tool_id") or str(t.get("name") or "?").rsplit("/", 1)[-1]
            strings = _tool_strings(t)
            if kind == "knowledge_assistant":
                spec = t.get("knowledge_assistant") if isinstance(t.get("knowledge_assistant"), dict) else {}
                ka_ref = str(spec.get("knowledge_assistant_id") or spec.get("name") or "")
                hit = (next((v for k, v in kas.items() if ka_ref and (ka_ref in k or k.endswith(ka_ref))), None)
                       or next((v for k, v in ka_endpoints.items() if _names_in(strings, k)), None)
                       or ka_ref or "a knowledge assistant")
                add(name, "supervisor_uses_vs_ka", hit,
                    f"tool {tool} uses knowledge assistant {hit}, which depends on AI Search")
            elif kind == "vector_search_index":
                target = next(iter(strings), "an AI Search index")
                add(name, "supervisor_uses_vs_index", target, f"tool {tool} is an AI Search index ({target})")
            elif kind == "serving_endpoint":
                for ep, display in ka_endpoints.items():
                    if _names_in(strings, ep):
                        add(name, "supervisor_uses_vs_ka", display,
                            f"tool {tool} calls the endpoint of knowledge assistant {display}, which depends on AI Search")
    changed = True
    while changed:  # a Supervisor that uses a dependent Supervisor depends too (also through its endpoint)
        changed = False
        for name, info in supervisors.items():
            for t in info["tools"]:
                if t.get("tool_type") not in ("supervisor_agent", "serving_endpoint"):
                    continue
                strings = _tool_strings(t)
                for ref, child in list(by_ref.items()):
                    if not _names_in(strings, ref):
                        continue
                    if child != name and child in found:
                        tool = t.get("tool_id") or str(t.get("name") or "?").rsplit("/", 1)[-1]
                        changed |= add(name, "supervisor_uses_supervisor", supervisors[child]["label"],
                                       f"tool {tool} uses {supervisors[child]['label']}, which depends on AI Search")
    return found


def scan_agent_bricks(w: WorkspaceClient, scanner: Scanner) -> None:
    """Knowledge Assistants and the Supervisor Agents that use them: all of them depend on AI Search.

    Agent Bricks agents that depend on AI Search don't work with Enforce on. Every Knowledge Assistant does: an
    AI Search index source directly, and a files or volume source through the assistant's own index. So every
    assistant is a finding (an index source also names its embedding endpoint), and so is every Supervisor Agent
    with a Knowledge Assistant tool.
    """
    kas: dict[str, str] = {}  # every Knowledge Assistant: name -> display name
    ka_endpoints: dict[str, str] = {}  # Knowledge Assistant serving endpoint -> display name
    n_ka = n_sa = bad_ka = bad_sa = 0
    try:
        for ka in w.knowledge_assistants.list_knowledge_assistants():
            n_ka += 1
            if getattr(ka, "endpoint_name", None):
                scanner.agent_bricks[ka.endpoint_name] = f"knowledge assistant {ka.display_name or ka.name}"
                ka_endpoints[ka.endpoint_name] = ka.display_name or ka.name
            kas[ka.name] = ka.display_name or ka.name
            readable = True
            try:
                sources = list(w.knowledge_assistants.list_knowledge_sources(parent=ka.name))
            except Exception:
                bad_ka += 1
                readable, sources = False, []  # still a finding: every Knowledge Assistant depends on AI Search
            label = f"knowledge assistant {ka.display_name or ka.name}"
            index_sources = [src for src in sources
                             if getattr(src, "index", None) and getattr(src.index, "index_name", None)]
            if not index_sources:
                kinds = sorted({str(getattr(src, "source_type", None) or "unknown") for src in sources})
                what = (f"sources ({', '.join(kinds)}) sync" if kinds else "its sources sync" if not readable
                        else "it has no sources yet; any source it gets syncs")
                scanner._add("knowledge_assistant", label, None, "ka_ai_search",
                             getattr(ka, "endpoint_name", None) or ka.name, None,
                             f"{what} into the assistant's own AI Search index, so it doesn't work with Enforce on"
                             + ("" if readable else " (its sources couldn't be read)"))
            for src in index_sources:
                embed = None
                try:
                    spec = w.vector_search_indexes.get_index(src.index.index_name).delta_sync_index_spec
                    cols = spec.embedding_source_columns if spec and spec.embedding_source_columns else []
                    embed = next((c.embedding_model_endpoint_name for c in cols if c.embedding_model_endpoint_name), None)
                except Exception:
                    pass
                scanner._add("knowledge_assistant", label, None,
                             "ka_vector_search_source", src.index.index_name, embed,
                             f"source {src.index.index_name} is an AI Search index"
                             + (f" embedded with {embed}" if embed else "")
                             + ": breaks under Enforce, and at the legacy deadline if the index embeds with a "
                               "databricks-* endpoint. Plan the move to Genie Agents")
    except Exception as error:
        _log(f"  could not list Knowledge Assistants: {error}")
        scanner.note("knowledge_assistants", f"failed: {str(error)[:120]}")
    scanner.note("knowledge_assistants", f"partial: {bad_ka} unreadable" if bad_ka else "ok")
    supervisors: dict[str, dict] = {}  # name -> {"label", "endpoint", "tools"}
    try:
        for sa in w.supervisor_agents.list_supervisor_agents():
            n_sa += 1
            label = f"supervisor agent {sa.display_name or sa.name}"
            endpoint = getattr(sa, "endpoint_name", None)
            if endpoint:
                scanner.agent_bricks[endpoint] = label
            try:
                tools = supervisor_tools(w, sa.name)
            except Exception:
                bad_sa += 1
                continue
            supervisors[sa.name] = {"label": label, "endpoint": endpoint, "tools": tools}
        for name, reasons in supervisor_dependencies(supervisors, kas, ka_endpoints).items():
            for pattern, target, text in reasons:
                scanner._add("supervisor_agent", supervisors[name]["label"], None, pattern, target, None, text)
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
            # None means the definition wasn't returned (unreadable), which is different from an empty one.
            return sp, w.genie.get_space(sp.space_id, include_serialized_space=True).serialized_space
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
    if REMOTE_SCAN:
        # information_schema is per metastore: from the hub it would list the hub's functions and views.
        for kind in ("uc_functions_skipped", "uc_views_skipped"):
            scanner.note(kind, f"{NOT_SCANNED}: central mode reads Unity Catalog definitions only from the hub's "
                               "metastore; scan this workspace from its own install or the CLI to include them")
        _log("  Unity Catalog functions and views not scanned (central mode)")
        return
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


def _workspace_text(w: WorkspaceClient, path: str) -> str | None:
    try:
        data = _get(w, "/api/2.0/workspace/export", {"path": path, "format": "AUTO"}).get("content")
        return base64.b64decode(data or "").decode("utf-8", errors="ignore")
    except Exception:
        return None


def is_toolkit_app(w: WorkspaceClient, app) -> bool:
    """A toolkit app: its description starts with the toolkit's, and its source is a toolkit install.

    The description alone is a field any app creator sets, so the source must also be bound to this app or to the
    toolkit's bundle. Installer installs: <folder>/ug_migration_toolkit.marker next to files/app names this app.
    Bundle installs (the app's source is the bundle root): the path is under .bundle/<TOOLKIT_BUNDLE>/ and the
    root holds the bundle's databricks.yml and ug_migration_planner.py. Neither is proof, so every skipped app is
    named in the coverage note.
    """
    if not (getattr(app, "description", None) or "").startswith(TOOLKIT_APP_DESCRIPTION):
        return False
    for p in {app.source_code_path, app.default_source_code_path} - {None}:
        p = p.removeprefix("/Workspace").rstrip("/")
        if p.endswith("/files/app"):
            marker = _workspace_text(w, p[: -len("/files/app")] + "/ug_migration_toolkit.marker")
            try:
                if marker and json.loads(marker).get("app") == app.name:
                    return True
            except (ValueError, AttributeError):
                pass
        if f"/.bundle/{TOOLKIT_BUNDLE}/" in p + "/":
            yml = _workspace_text(w, p + "/databricks.yml") or ""
            if re.search(rf"^bundle:\s*\n\s+name:\s*{re.escape(TOOLKIT_BUNDLE)}\s*$", yml, re.M) \
                    and _workspace_text(w, p + "/ug_migration_planner.py"):
                return True
    return False


def scan_apps(w: WorkspaceClient, scanner: Scanner, toolkit_apps: Iterable[str] = ()) -> None:
    n = 0
    skip = set(toolkit_apps)
    try:
        for app in w.apps.list():
            if app.name in skip:
                continue
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


def app_source_roots(w: WorkspaceClient, coverage: dict[str, str], toolkit: list[str] | None = None,
                     toolkit_apps: list[str] | None = None) -> list[str]:
    """Workspace folders that hold each app's source (current and default deployment), as scan roots.

    Toolkit apps (is_toolkit_app) are left out: their names go to toolkit_apps, and their folders and their
    service principal's deployment copies (/Users/<application ID>/src) go to toolkit, so the workspace walk
    skips them too. Coverage names each skipped app, so the skip is visible in the readiness report.
    """
    roots, skipped = [], []
    try:
        for app in w.apps.list():
            paths = [p[len("/Workspace"):] for p in (app.source_code_path, app.default_source_code_path)
                     if p and p.startswith("/Workspace/")]
            if is_toolkit_app(w, app):
                skipped.append(app.name)
                if toolkit is not None:
                    # Service principal homes use the application ID; the display name is never a folder.
                    toolkit += paths + ([f"/Users/{app.service_principal_client_id}/src"]
                                        if app.service_principal_client_id else [])
                continue
            roots += paths
    except Exception as error:
        _log(f"  could not list apps for their source folders: {error}")
        coverage["app_sources"] = f"failed: {str(error)[:120]}"
        return roots
    coverage["app_sources"] = "ok"
    if skipped:
        coverage["toolkit_apps"] = f"{NOT_SCANNED}: toolkit app {', '.join(sorted(skipped))}, {TOOLKIT_NOTE}"
    if toolkit_apps is not None:
        toolkit_apps += skipped
    return sorted(set(roots))


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
                                     name, AI_SEARCH_KEEP_TEXT)
    except Exception as error:
        _log(f"  could not list AI Search indexes: {error}")
        scanner.note("vector_search", f"failed: {str(error)[:120]}")
    scanner.note("vector_search", f"partial: {bad} unreadable" if bad else "ok")
    _log(f"  scanned {n} AI Search indexes")


# AI Search can't embed with a Unity Gateway service yet, and no date is announced. An index can't switch its
# embedding endpoint, and the databricks-* embedding endpoints retire with every legacy endpoint, Enforce or not.
AI_SEARCH_LIMITS = ("AI Search can't embed with a Unity Gateway service yet, and no date is announced. An index can't "
                    "switch its embedding endpoint: it has to be recreated on a supported embedding service. An index "
                    "on a databricks-* embedding endpoint stops working when legacy endpoints retire, even if Enforce "
                    "is never turned on")
AI_SEARCH_KEEP_TEXT = ("keep this embedding endpoint while the index uses it: don't enforce Unity Gateway or "
                       "rate-limit the endpoint to 0. " + AI_SEARCH_LIMITS + ", so plan the rebuild. An index with "
                       "self-managed embeddings (vectors you compute and store) doesn't depend on the endpoint: check "
                       "the AI Search docs before relying on one")
AI_SEARCH_KEEP_ACTION = ("keep the endpoint and don't enforce Unity Gateway yet. AI Search can't embed with a Unity "
                         "Gateway service (no date announced), an index can't switch its embedding endpoint, and an "
                         "index on a databricks-* embedding stops at the legacy deadline even with Enforce off: plan "
                         "to recreate the index once support arrives, or move it to self-managed embeddings")


def annotate_dependencies(rows: list[PlanRow], refs: list[ClientReference], days: int = 30) -> None:
    """Mark endpoints that AI Search indexes or apps depend on, so they aren't enforced early.

    Also replaces the generic no-traffic note: retiring is suggested only when no code references the endpoint.
    """
    by_ep: dict[str, list[ClientReference]] = {}
    for r in refs:
        if r.legacy_endpoint and r.asset_type in ("vector_search_index", "app", "knowledge_assistant"):
            by_ep.setdefault(r.legacy_endpoint, []).append(r)
    referenced = {r.legacy_endpoint for r in refs if r.legacy_endpoint}
    for row in rows:
        deps = by_ep.get(row.legacy_endpoint, [])
        indexes = [d.asset.removeprefix("index ") for d in deps if d.asset_type in ("vector_search_index", "knowledge_assistant")]
        apps = [d.asset.removeprefix("app ") for d in deps if d.asset_type == "app"]
        if indexes:
            row.needs_human.append(f"embedding model for {len(indexes)} AI Search index(es) "
                                   f"({', '.join(indexes[:3])}): keep the endpoint; blocks Enforce, and the index has to "
                                   "be recreated once AI Search supports Unity Gateway embedding services")
        if apps:
            row.needs_human.append(f"app resource in {', '.join(apps[:3])}: update the app before Enforce")
        if row.requests_window == 0 and any(n.startswith(NO_TRAFFIC_NEED) for n in row.needs_human):
            if row.legacy_endpoint in referenced:
                text = (f"No requests in {days} days, but code still references it (see client_references.csv): "
                        "keep it or move the callers")
            else:
                text = (f"No requests in {days} days and no code references it: confirm with the owner, then retire it")
            row.needs_human = [text + n[len(NO_TRAFFIC_NEED):] if n.startswith(NO_TRAFFIC_NEED) else n
                               for n in row.needs_human]


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
                         if seg and (seg.search(x.asset) or any(seg.search(p) for p in x.also_in))
                         and x.legacy_endpoint in (ep, None)})
        out.append({"endpoint_name": ep, "requester": who, "requester_name": names.get(who, who),
                    "api": r.get("api") or "v1", "caller_class": r.get("caller_class") or "unknown",
                    "user_agent": r.get("user_agent"), "requests": r.get("requests"), "tokens": r.get("tokens"),
                    "last_request": r.get("last_request"), "linked_code": linked[:20], "linked_count": len(linked)})
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


NOT_SCANNED = "not scanned"  # coverage values that are notes (what was left out), not gaps
VOLUMES_NOTE = (f"{NOT_SCANNED}: files in Unity Catalog volumes and DBFS aren't searched. A script there that calls "
                "a legacy endpoint shows only as traffic (none if it didn't run in the window): check them, or scan a "
                "copy with --local-path")
UNATTRIBUTED_NOTE = "unattributed"  # coverage["v1_unattributed"]: v1 requests not matched to an endpoint (a warning)
# Serving-endpoint resources declared by an app or bundle. Other app references are config values (warnings).
RESOURCE_PATTERNS = {"app_serving_endpoint_resource", "bundle_serving_endpoint_resource"}
PATTERN_TEXT = {  # code-reference pattern -> (plain label, one-line action)
    "serving_endpoints_url": ("Code calls a legacy serving URL", "point the call at /ai-gateway/ (see CODE_FIXES.md)"),
    "serving_endpoints_management_api": ("Automation manages legacy serving endpoints",
                                         "move it to the Unity Gateway APIs or Terraform resources"),
    "serving_endpoint_route_url": ("Code calls a route-optimized endpoint URL", "call /ai-gateway/ instead"),
    "legacy_endpoint_name": ("Code names a legacy endpoint",
                             "replace the name with its Unity Gateway service and move the client to /ai-gateway/"),
    "config_value": ("Config value names a legacy endpoint", "change the value and the code that reads it"),
    "ai_query": ("ai_query calls a legacy endpoint",
                 "switch to the system.ai model and read the caveats in CODE_FIXES.md"),
    "ChatDatabricks": ("LangChain client names a legacy endpoint", "update the client as shown in CODE_FIXES.md"),
    "mlflow_endpoint_uri": ("MLflow loads a model from a legacy endpoint",
                            "use the databricks:/ service URI (needs MLflow 3.16+)"),
    "app_serving_endpoint_resource": ("App declares a legacy serving endpoint resource",
                                      "replace the resource with the Unity Gateway service"),
    "bundle_serving_endpoint_resource": ("App declares a legacy serving endpoint resource",
                                         "replace the resource with the Unity Gateway service"),
    "mlflow_deployments_predict": ("MLflow deployments predict call names a legacy endpoint",
                                   "rewrite it by hand with the OpenAI client on /ai-gateway/mlflow/v1 (see CODE_FIXES.md)"),
    "sdk_serving_query": ("Databricks SDK query call names a legacy endpoint",
                          "rewrite it by hand with the OpenAI client on /ai-gateway/mlflow/v1 (see CODE_FIXES.md)"),
    "sdk_openai_client": ("Code uses the SDK's serving-endpoints OpenAI client",
                          "switch to DatabricksOpenAI(use_ai_gateway=True) or the OpenAI client on /ai-gateway/mlflow/v1"),
    "custom_endpoint_call": ("Code calls a custom model endpoint", "no change: custom model endpoints stay on legacy serving"),
    "tabular_endpoint_call": ("Code sends tabular input to an endpoint the scan can't name",
                              "confirm which endpoint it calls: a custom model endpoint needs no change, a legacy one "
                              "moves to the OpenAI client on /ai-gateway/mlflow/v1"),
    "v2_gateway_model": ("Client sends a legacy model name on the gateway route (v2)",
                         "set model to the system.ai model and keep the route (see CODE_FIXES.md)"),
    "ai_gateway_regional_host": ("Code calls a regional AI Gateway host",
                                 "move the call to the workspace /ai-gateway/ route and an ai-gateway token"),
}
KIND_NAMES = {"system_ppt": "Databricks pay-per-token (system)", "external_model": "External model",
              "provisioned_throughput": "Provisioned throughput", "custom_model": "Custom ML model",
              "agent": "Agent", "unknown": "Unknown", "out_of_scope": "Out of scope",
              "v2_workspace_endpoint": "AI Gateway v2 (workspace-bound)"}
ACTION_NAMES = {"use_system_ai": "Use a system.ai model", "create_model_service": "Create a Unity Gateway service",
                "out_of_scope": "Out of scope (custom model or agent)", "manual": "Manual (see needs)"}
STATUS_MEANING = {
    "READY": "no blockers, and no coverage gaps (the notes say what the scan never searches).",
    "READY_WITH_WARNINGS": "no blockers; review warnings first.",
    "BLOCKED": "enforcing now breaks the calls listed below.",
    "INCOMPLETE": "nothing blocking found, but part of the scan didn't run; fix the listed gap and re-run.",
}
NEXT_STEPS = {
    "BLOCKED": [
        "Fix each blocker below. Each one names the endpoint or the file to change.",
        "Make the code changes in CODE_FIXES.md, including its list of manual edits.",
        "Re-run the planner and confirm READINESS.md shows no blockers.",
        "Confirm with the owners of endpoints with no traffic that they are unused.",
        "Enforce Unity Gateway only after the re-run is clean.",
    ],
    "READY_WITH_WARNINGS": [
        "Review the warnings below (the full list is in readiness.json).",
        "Make the code changes in CODE_FIXES.md, including its list of manual edits.",
        "Confirm with the owners of endpoints with no traffic that they are unused.",
        "Re-run the planner, then enforce Unity Gateway.",
    ],
    "READY": [
        "Confirm with the owners of endpoints with no traffic that they are unused.",
        "Enforce Unity Gateway (see What Enforce does below).",
    ],
    "INCOMPLETE": [
        "Fix the gap listed under Incomplete scan (grant the missing access, or run without --skip-scan).",
        "Re-run the planner and read the new status.",
    ],
}
def glossary() -> list[str]:
    """Glossary lines. Built at call time so the retirement date follows the deadline in use."""
    return [
        "**Enforce**: the workspace setting Enforce Unity Gateway. When it is on, legacy `databricks-*` pay-per-token "
        "endpoints stop serving (calls fail with PERMISSION_DENIED).",
        f"**Legacy endpoint (v1 and v2)**: a Model Serving endpoint, or a workspace-bound AI Gateway v2 endpoint. All "
        f"legacy endpoints retire on {deadline_text()} ({DEADLINE_AS_OF}). Custom model and feature serving endpoints "
        "are not affected.",
        "**Workspace-bound v2 endpoint**: an AI Gateway v2 endpoint with no serving-endpoint object. It shows up only in "
        "system.ai_gateway.usage, and callers reach it on the /ai-gateway/ route with a plain model name.",
        "**Unity Gateway model service**: the replacement, a catalog object such as system.ai.<model> or "
        "<catalog>.<schema>.<name>, called through /ai-gateway/.",
        "**Provider service**: a Unity Gateway object that holds the credentials for an external provider "
        "(OpenAI, Anthropic and so on) and is used by model services.",
        "**Caller type**: who sent the requests. platform (Databricks-managed, for example Genie, Agent Bricks or AI "
        "Search), coding_agent (Claude Code, opencode and similar: move them with ucode), sdk (Databricks SDK or "
        "MLflow), llm_sdk (OpenAI, LiteLLM, Anthropic, LangChain), http (plain HTTP clients), service_principal, user, "
        "unknown.",
        "**Apply**: the step that creates the planned Unity Gateway services and provider services. It only changes "
        "things with --execute.",
        "**Dry run**: what apply does by default: it lists the changes it would make and creates nothing.",
        "**Blocker**: a finding that breaks live calls once Enforce is on. Fix it before enforcing.",
        f"**Warning**: a finding that breaks only if the code still runs, or before legacy endpoints retire "
        f"({deadline_text()}). Review it and fix it.",
    ]


def _flag(kind: str, item, detail: str, label: str, action: str) -> dict:
    """One blocker or warning. type is the stable machine name; label and action are for people."""
    return {"type": kind, "label": label, "item": item, "detail": detail, "action": action}


def _ref_text(x: ClientReference) -> tuple[str, str]:
    """(label, action) for a code reference. App references are config values unless they declare a resource."""
    if x.asset_type == "app" and x.pattern not in RESOURCE_PATTERNS:
        return ("App config value uses a legacy endpoint", "change the env value and the code that reads it")
    return PATTERN_TEXT.get(x.pattern, (f"Code reference ({x.pattern})", "review it in CODE_FIXES.md"))


def _classes_by_endpoint(callers: list[dict] | None) -> dict[str, dict[str, int]]:
    """Requests per caller class for each endpoint, from the per-caller rows (traffic_by_requester)."""
    out: dict[str, dict[str, int]] = {}
    for c in callers or []:
        d = out.setdefault(c.get("endpoint_name"), {})
        cls = c.get("caller_class") or "unknown"
        d[cls] = d.get(cls, 0) + int(c.get("requests") or 0)
    return out


def _coding_agents_by_endpoint(callers: list[dict] | None) -> dict[str, list[str]]:
    """The user agents of coding-agent callers per endpoint (v2 rows), so the owner can find each agent."""
    out: dict[str, set[str]] = {}
    for c in callers or []:
        if (c.get("caller_class") or "") == "coding_agent" and c.get("user_agent"):
            out.setdefault(c.get("endpoint_name"), set()).add(str(c["user_agent"])[:80])
    return {ep: sorted(agents) for ep, agents in out.items()}


def _class_text(classes: dict[str, int]) -> str:
    parts = [f"{cls} {n:,}" for cls, n in sorted(classes.items(), key=lambda kv: -kv[1]) if n]
    return "callers by type (requests): " + (", ".join(parts) or "none")


# v2 calls are "already failing" when at least V2_FAILING_MIN_REQUESTS v2 requests were made and at least
# V2_FAILING_SHARE_PERCENT of them failed. Failed means no status code, or status 0 or 501 (other 4xx and 5xx can be caller, permission, rate-limit or provider errors, not a gateway that is off).
V2_FAILING_MIN_REQUESTS = 10
V2_FAILING_SHARE_PERCENT = 95
V2_OFF_LABEL = "v2 calls are already failing in this workspace"
V2_OFF_ACTION = ("v2 is off here: these callers get errors now. Move them to {target} first (keep the /ai-gateway/ "
                 "route, change the model)")
UNAVAILABLE_LABEL = "Unity Gateway isn't available in this workspace"
UNAVAILABLE_ACTION = ("Ask your account team to enable Unity Gateway for this workspace and account. Nothing can be "
                      "migrated until it is.")


def v2_mostly_failing(r: PlanRow) -> bool:
    """Most of the endpoint's v2 requests failed (v2 is off for the workspace). Used for the blocker and the account view."""
    return r.v2_requests >= V2_FAILING_MIN_REQUESTS and 100 * r.v2_failed >= V2_FAILING_SHARE_PERCENT * r.v2_requests


def readiness(rows: list[PlanRow], refs: list[ClientReference], traffic_ok: bool, days: int,
              endpoints: list[LegacyEndpoint] | None = None, coverage: dict[str, str] | None = None,
              scanned: bool = True, callers: list[dict] | None = None) -> dict:
    """Decide whether Enforce Unity Gateway can be turned on, and list what blocks it.

    Blockers break traffic or dependencies when enforced. Warnings are code references that will break
    if they still run. The scan coverage must be complete for READY. Zero traffic in the window is not
    proof of no use, and endpoints with usage tracking off have unknown traffic, so both keep the result
    from being READY on their own. Close candidates are external model endpoints with no traffic, no
    dependents and no references in a complete scan; PT endpoints are never candidates because their
    Unity Gateway wrappers route through them.

    Traffic only from Databricks-managed callers (caller class "platform") is a warning, not a blocker: the
    customer can't change those callers. callers are the per-caller rows from traffic_by_requester().

    READY is capped at READY_WITH_WARNINGS when local folders were not scanned, or when a pay-per-token endpoint
    has no traffic and no known caller: each adds a warning, and any warning rules out plain READY.

    One pay-per-token blocker per endpoint carries the call-site count; the call sites are in CODE_FIXES.md.
    """
    blockers, warnings = [], []
    by_name = {e.name: e for e in endpoints or []}
    row_by = {r.legacy_endpoint: r for r in rows}
    v2_names = {e.name for e in endpoints or [] if e.kind == "v2_workspace_endpoint"}
    # Endpoints that retire (custom model and feature serving don't): unresolved calls only matter if any exist.
    retiring = any(r.action != "out_of_scope" for r in rows)
    index_endpoints = {x.legacy_endpoint for x in refs if x.asset_type == "vector_search_index" and x.legacy_endpoint}
    classes_by_ep = _classes_by_endpoint(callers)
    agents_by_ep = _coding_agents_by_endpoint(callers)
    traffic_blockers: dict[str, dict] = {}
    call_sites: dict[str, list[ClientReference]] = {}
    for r in rows:
        target = r.target_service or "a model service"
        classes = classes_by_ep.get(r.legacy_endpoint) or None
        if r.requests_window and r.action != "out_of_scope":
            detail = f"{r.requests_window:,} requests from {_n(r.requesters, 'caller')} in {days} days, last {r.last_request}"
            if classes:
                detail += "; " + _class_text(classes)
            if r.v2_requests:
                detail += (f"; {r.v2_requests:,} of them AI Gateway v2 traffic, which retires with all legacy endpoints "
                           f"on {deadline_text()}")
            ppt = ppt_backed_models(by_name[r.legacy_endpoint]) if r.legacy_endpoint in by_name else []
            if ppt:
                # It forwards to a databricks-* pay-per-token endpoint, which Enforce stops: its callers break too.
                direct = sorted({row_by[p].target_service for p in ppt if p in row_by and row_by[p].target_service})
                blockers.append(_flag("external_model_on_ppt", r.legacy_endpoint,
                                      f"{detail}; forwards to {', '.join(ppt)}, which Enforce stops",
                                      "External model endpoint forwards to a pay-per-token endpoint",
                                      f"move the callers to {target} (or straight to "
                                      f"{', '.join(direct) or 'the system.ai model'}) before enforcing"))
            elif r.kind in ("external_model", "provisioned_throughput"):
                # Enforce leaves existing external model and PT endpoints queryable; they retire with v1.
                warnings.append(_flag("legacy_traffic_kept_after_enforce", r.legacy_endpoint,
                                      detail + " (keeps working after Enforce)",
                                      "Callers use an external or PT endpoint that outlives Enforce",
                                      f"move them to {target} before legacy endpoints retire ({deadline_text()})"))
            elif classes and set(classes) == {"platform"}:
                flag = _flag("platform_managed_traffic", r.legacy_endpoint, detail,
                             "Databricks-managed callers use this endpoint", PLATFORM_ACTION)
                flag["caller_classes"] = classes
                warnings.append(flag)
            else:
                action = f"move the callers to {target} before enforcing"
                agents = agents_by_ep.get(r.legacy_endpoint) or []
                if classes and "coding_agent" in classes:
                    action += ("; coding agents: move the coding agent to Unity Gateway with ucode "
                               "(docs: coding agent integration)")
                    if agents:
                        detail += "; coding agent user agents: " + " | ".join(agents[:3])
                if classes and "no_client_info" in classes:
                    action += ("; calls with no client information are usually ai_query or batch inference in "
                               "notebooks and jobs (or a Databricks feature such as Genie running as that user): "
                               "check the listed users' jobs, notebooks and SQL")
                flag = _flag("legacy_traffic", r.legacy_endpoint, detail, "Callers still use a legacy endpoint", action)
                if classes:
                    flag["caller_classes"] = classes
                if agents:
                    flag["user_agents"] = agents
                traffic_blockers[r.legacy_endpoint] = flag
        if r.kind == "agent":
            # The endpoint isn't retired; what can break is the LLM calls inside it. Their traffic to an endpoint
            # Enforce stops is a blocker (custom_endpoint_inner_call), and so is their code where the scan sees it.
            # The model code itself is often a logged UC model the scan can't read, so the traffic is what counts.
            bricks = any(n.startswith("Agent Bricks") for n in r.needs_human)
            used = (f"{r.requests_window:,} requests in {days} days" if r.requests_window
                    else AGENT_TRAFFIC_UNKNOWN)
            if bricks:
                warnings.append(_flag("agent_bricks_endpoint", r.legacy_endpoint,
                                      f"{used}; " + "; ".join(r.needs_human),
                                      "Agent Bricks agent: a legacy offering, replaced by Genie Agents",
                                      AGENT_BRICKS_ACTION))
            else:
                warnings.append(_flag("agent_endpoint", r.legacy_endpoint, f"{used}; " + "; ".join(r.needs_human),
                                      "Agent endpoint: the LLM calls inside it must move",
                                      AGENT_ACTION if r.requests_window else
                                      "confirm with the owner whether it is still used (its traffic isn't recorded); "
                                      "if it is, " + AGENT_ACTION))
        # A PT endpoint behind a Unity Gateway model service keeps serving after the deadline (the service routes to
        # its capacity), so the wrapper itself needs no warning; direct callers of the endpoint are flagged as traffic.
    # Measured Nov 3, 2026: a custom agent endpoint's automatic-auth identity shows up as "System Service Principal".
    custom = sorted(r.legacy_endpoint for r in rows if r.kind in ("custom_model", "agent"))
    inner: dict[str, int] = {}
    for c in callers or []:
        ep = c.get("endpoint_name")
        if c.get("requester_name") == SYSTEM_SP_NAME and ep in row_by and row_by[ep].action != "out_of_scope":
            inner[ep] = inner.get(ep, 0) + int(c.get("requests") or 0)
    for ep, n in sorted(inner.items()):
        # Enforce stops databricks-* endpoints (and external models that forward to one): an agent calling them
        # from its model code breaks then, even when the code scan can't see that code (a logged UC model).
        stops = row_by[ep].kind == "system_ppt" or bool(ep in by_name and ppt_backed_models(by_name[ep]))
        (blockers if stops else warnings).append(_flag(
            "custom_endpoint_inner_call", ep,
            f"{n:,} requests from a {SYSTEM_SP_NAME}: usually a serving endpoint calling {ep} with automatic "
            "authentication, such as a custom agent"
            + ("; Enforce stops this endpoint, so those calls fail once it's on" if stops else "")
            + (f". Custom model and agent endpoints here: {', '.join(custom[:5])}" if custom else ""),
            "A serving endpoint calls this endpoint from its model code" if stops else
            "A serving endpoint may call this endpoint from its model code",
            "find the custom model or agent endpoint whose model code calls it: re-log the model with explicit credentials to call "
            "the model service (see CODE_FIXES.md). If it's a custom model endpoint, turn on its usage tracking (agent "
            "endpoints can't). Its own callers need no change"))
    for x in refs:
        loc = x.asset + (f":{x.line}" if x.line else "")
        if x.pattern == "custom_endpoint_call":
            continue  # custom model endpoints aren't retired: listed in CODE_FIXES.md as "no change", not a finding
        if x.pattern == "tabular_endpoint_call":
            if retiring:  # probably a custom model, but the scan can't name it: a warning, not a blocker
                label, action = PATTERN_TEXT[x.pattern]
                warnings.append(_flag(x.pattern, loc, x.suggestion, label, action))
            continue
        if x.pattern in VARIABLE_CALL_PATTERNS and not x.legacy_endpoint and retiring:
            # A client bound to /serving-endpoints with a run-time name: same unknown as a dynamic URL.
            blockers.append(_flag("unresolved_endpoint_call", loc, x.suggestion,
                                  "Code calls a serving endpoint the scan can't name",
                                  "find which endpoint it calls at run time. A legacy endpoint: rewrite the client "
                                  "as described (changing only the name gives a 404). " + CUSTOM_UNNAMED_ACTION))
            continue
        if x.asset_type == "vector_search_index":
            blockers.append(_flag("vector_search", x.asset.removeprefix("index "),
                                  f"embeds with {x.legacy_endpoint}; " + AI_SEARCH_LIMITS,
                                  "AI Search index embeds with a legacy endpoint", AI_SEARCH_KEEP_ACTION))
        elif x.asset_type in ("knowledge_assistant", "supervisor_agent"):
            blockers.append(_flag("agent_bricks_vector_search", x.asset, x.suggestion,
                                  "Agent Bricks agent uses AI Search", AGENT_BRICKS_BLOCK_ACTION))
        elif x.pattern in RESOURCE_PATTERNS:
            blockers.append(_flag("app_resource", x.asset.removeprefix("app "),
                                  f"serving endpoint resource {x.legacy_endpoint}",
                                  "App declares a legacy serving endpoint resource",
                                  "replace the resource with the Unity Gateway service, grant the app's service "
                                  "principal EXECUTE on it, and call /ai-gateway/ from the app code"))
        elif x.pattern == "ai_query" and x.suggestion.startswith("ai_query can't call"):
            row = row_by.get(x.legacy_endpoint)
            svc = row.target_service if row else None
            if row is not None and row.target_status == "exists":
                detail = (f"ai_query on {x.legacy_endpoint}: ai_query can't call Unity Gateway model services yet "
                          f"(service {svc} exists). Keep this call until it can.")
            else:
                detail = (f"ai_query on {x.legacy_endpoint}: its Unity Gateway service {svc} doesn't exist yet. "
                          "Keep this call until it does.")
            blockers.append(_flag("ai_query_custom", loc, detail,
                                  "ai_query calls a model with no Unity Gateway service yet",
                                  "keep this call, or switch it to a system.ai model (see CODE_FIXES.md)"))
        elif x.pattern == "serving_endpoints_url" and not x.legacy_endpoint \
                and x.suggestion.startswith(DYNAMIC_URL_SUGGESTION) and retiring:  # notes (model code) may follow
            # The name is built at run time, so the scan can't tell whether this call reaches a legacy endpoint.
            # With legacy endpoints in the workspace that is an unknown caller, so it holds readiness back.
            blockers.append(_flag("unresolved_endpoint_call", loc,
                                  "a /serving-endpoints/ call whose endpoint name is built at run time: the scan "
                                  "can't tell whether it reaches a legacy endpoint",
                                  "Code calls a serving endpoint the scan can't name",
                                  "find which endpoint it calls at run time. A legacy endpoint: move the call to "
                                  "/ai-gateway/ (see CODE_FIXES.md). " + CUSTOM_UNNAMED_ACTION))
        elif x.asset_type == "app":
            label, action = _ref_text(x)
            warnings.append(_flag(x.pattern, loc, x.suggestion, label, action))
        elif x.legacy_endpoint and (x.legacy_endpoint.startswith("databricks-") or x.legacy_endpoint in v2_names) \
                and x.pattern != "serving_endpoints_management_api":
            # Pay-per-token and v2 calls fail under Enforce whether or not the endpoint has traffic in the window.
            call_sites.setdefault(x.legacy_endpoint, []).append(x)
        else:
            label, action = _ref_text(x)
            warnings.append(_flag(x.pattern, loc, x.suggestion, label, action))
    # v2 calls that already fail (v2 is off for the workspace). For a workspace-bound v2 endpoint this one blocker
    # replaces its plain v2 blocker: its traffic and call-site details are folded in, so nothing is counted twice.
    # A serving endpoint that also gets failing v2 calls keeps its own blockers (its v1 callers still break).
    v2_off = []
    for ep_name, r in row_by.items():
        if not v2_mostly_failing(r):
            continue
        detail = (f"{r.v2_failed:,} of {r.v2_requests:,} AI Gateway v2 requests failed in {days} days "
                  f"({r.v2_status_501:,} with HTTP 501)")
        traffic = None
        if ep_name in v2_names:
            traffic = traffic_blockers.pop(ep_name, None)
            if traffic:
                detail += "; " + traffic["detail"]
            if ep_name in call_sites:
                detail += "; " + f"{_n(len(call_sites.pop(ep_name)), 'call site')}: see CODE_FIXES.md"
        flag = _flag("v2_off_failing_calls", ep_name, detail, V2_OFF_LABEL,
                     V2_OFF_ACTION.format(target=r.target_service or "a model service"))
        for key in ("caller_classes", "user_agents"):
            if traffic and key in traffic:
                flag[key] = traffic[key]
        v2_off.append(flag)
    for ep_name, sites in call_sites.items():
        target = row_by[ep_name].target_service if ep_name in row_by else None
        detail = f"{_n(len(sites), 'call site')}: see CODE_FIXES.md"
        if ep_name in traffic_blockers:
            detail = traffic_blockers.pop(ep_name)["detail"] + "; " + detail
        if ep_name in v2_names:
            blockers.append(_flag("v2_workspace_call", ep_name, detail, "Code calls a v2 workspace endpoint",
                                  f"set the model to {target or 'a model service'} and keep the /ai-gateway/ route "
                                  "(see CODE_FIXES.md), then re-scan"))
        elif ep_name in index_endpoints:
            # The same embedding endpoint also feeds an AI Search index: only the direct calls move.
            blockers.append(_flag("pay_per_token_call", ep_name, detail,
                                  "Code calls a Databricks pay-per-token endpoint",
                                  f"switch only the direct query calls to {target or 'a model service'} (see "
                                  "CODE_FIXES.md), then re-scan. Keep the endpoint itself: an AI Search index still "
                                  "embeds with it"))
        else:
            blockers.append(_flag("pay_per_token_call", ep_name, detail,
                                  "Code calls a Databricks pay-per-token endpoint",
                                  f"switch the calls to {target or 'a model service'} (see CODE_FIXES.md), then re-scan"))
    blockers += traffic_blockers.values()
    coverage = coverage or {}
    unavailable = coverage.get("system_ai_map", "")
    if unavailable.startswith(UNAVAILABLE):
        # Without the system.ai listing no replacement can be chosen, so nothing can be migrated.
        blockers.append(_flag("unity_gateway_unavailable", "system.ai", "could not list the system.ai model services: "
                              + unavailable[len(UNAVAILABLE) + 2:], UNAVAILABLE_LABEL, UNAVAILABLE_ACTION))
    # The v2 and Unity Gateway blockers come first; the order of the rest is unchanged.
    blockers = sorted(blockers + v2_off, key=lambda b: 0 if b["type"] == "unity_gateway_unavailable"
                      else 1 if b["type"] == "v2_off_failing_calls" else 2)
    gaps = {k: v for k, v in coverage.items() if v != "ok" and not v.startswith(NOT_SCANNED)
            and not v.startswith(UNAVAILABLE) and not v.startswith(UNATTRIBUTED_NOTE)}
    if coverage.get("v1_unattributed", "").startswith(UNATTRIBUTED_NOTE):
        # Their endpoint is unknown, so any endpoint's "no traffic" could be wrong: never plain READY.
        warnings.append(_flag("unattributed_legacy_traffic", "system.serving.endpoint_usage",
                              coverage["v1_unattributed"][len(UNATTRIBUTED_NOTE) + 2:],
                              "Legacy requests couldn't be matched to an endpoint",
                              "their served entity has no system.serving.served_entities row, so the traffic per "
                              "endpoint may be low. Check SELECT access to system.serving.served_entities and "
                              "confirm with owners before enforcing or pausing"))
    notes = {k: v for k, v in coverage.items() if v.startswith(NOT_SCANNED)}
    if not traffic_ok:
        # A permissions or data problem, not something Enforce would break: readiness can't be decided yet.
        gaps["traffic"] = "not confirmed: system tables couldn't be read or have no rows for this workspace"
    if not scanned:
        gaps["code_scan"] = "skipped"
    if scanned and coverage.get("local_files", "").startswith(NOT_SCANNED):
        # Cloned repos and bundle folders on a laptop are where many callers live: their absence caps READY.
        warnings.append(_flag("local_folders_not_scanned", "local_files",
                              "no --local-path was given, so cloned repos and bundle folders were not searched for "
                              "calls to legacy endpoints",
                              "Local folders were not scanned",
                              "re-run with --local-path for each cloned repo or bundle folder, or confirm that none "
                              "calls a legacy endpoint"))
    left_out = {k: v for k, v in notes.items() if k.endswith("_skipped")}
    if scanned and left_out:
        # Dependency and build folders and other file types are left out on purpose; a caller there would be
        # missed, so their absence caps READY the same way unscanned local folders do.
        warnings.append(_flag("skipped_paths_not_scanned", ", ".join(sorted(left_out)),
                              "; ".join(f"{k}: {v[len(NOT_SCANNED) + 2:]}" for k, v in sorted(left_out.items())),
                              "Some folders or file types were not scanned",
                              "check the listed folders and file types for calls to legacy endpoints, or confirm "
                              "they hold none (vendored packages and build output usually don't)"))
    referenced = {x.legacy_endpoint for x in refs if x.legacy_endpoint}
    if traffic_ok:
        # Measured: endpoints with usage tracking off still log rows in system.serving.endpoint_usage, so zero
        # rows isn't proof of "untracked". Warn (callers outside the window), don't hold readiness back.
        untracked = [r.legacy_endpoint for r in rows if not r.requests_window and r.legacy_endpoint in by_name
                     and r.kind != "v2_workspace_endpoint" and r.action != "out_of_scope"
                     and by_name[r.legacy_endpoint].usage_tracking is not True]
        if untracked:
            warnings.append(_flag(
                "no_traffic_in_window", _n(len(untracked), "endpoint"),
                "no requests in the window and usage tracking off: " + ", ".join(untracked[:5])
                + (" ..." if len(untracked) > 5 else ""),
                "No requests in the window and usage tracking is off",
                "confirm with the owners that no infrequent job (monthly, quarterly) calls them"))
        quiet_ppt = []
        for r in rows:
            if r.kind in ("system_ppt", "v2_workspace_endpoint") and not r.requests_window \
                    and r.legacy_endpoint not in referenced:
                if r.kind == "system_ppt":
                    quiet_ppt.append(r.legacy_endpoint)  # folded into one warning: a workspace lists dozens
                    continue
                warnings.append(_flag(
                    "confirm_infrequent_callers", r.legacy_endpoint,
                    f"no requests in {days} days and no code found that calls it: a job that runs monthly or "
                    "quarterly would not show up in the window",
                    "v2 endpoint had traffic before the window but none in it, and no known callers",
                    "confirm infrequent callers (monthly or quarterly jobs) with the owners before enforcing"))
        if quiet_ppt:
            flag = _flag(
                "confirm_infrequent_callers", quiet_ppt[0] if len(quiet_ppt) == 1 else _n(len(quiet_ppt), "endpoint"),
                f"{_n(len(quiet_ppt), 'pay-per-token endpoint')} with no requests in {days} days and no code found "
                "that calls them: a job that runs monthly or quarterly would not show up in the window. "
                + ", ".join(quiet_ppt[:8]) + (" ..." if len(quiet_ppt) > 8 else ""),
                "Pay-per-token endpoint has no traffic and no known callers" if len(quiet_ppt) == 1
                else "Pay-per-token endpoints have no traffic and no known callers",
                "confirm infrequent callers (monthly or quarterly jobs) with the owners before enforcing. Built-in "
                "endpoints nobody calls need no action")
            flag["endpoints"] = quiet_ppt
            warnings.append(flag)
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
    # Any warning above rules out plain READY (the caution rules in the docstring rely on this).
    if blockers:
        status = "BLOCKED"
    elif gaps:
        status = "INCOMPLETE"
    else:
        status = "READY_WITH_WARNINGS" if warnings else "READY"
    return {"status": status, "blockers": blockers, "warnings": warnings, "coverage_gaps": gaps,
            "coverage": coverage, "notes": notes, "rate_limit_zero_candidates": candidates}


def _next_steps(r: dict) -> list[str]:
    steps = list(NEXT_STEPS[r["status"]])
    if r.get("coverage_gaps") and r["status"] == "BLOCKED":
        steps.insert(0, "Close the Incomplete scan gaps too: the code scan isn't complete, so the call sites are not all known.")
    return steps


def _md(v) -> str:
    return str(v if v is not None else "").replace("|", "\\|").replace("\n", " ")


def _capped(items: list[str], cap: int, more_in: str) -> list[str]:
    out = items[:cap]
    if len(items) > cap:
        out.append(f"- +{len(items) - cap} more in {more_in}")
    return out


def _enforce_lines(enforce: str | None, status: str) -> list[str]:
    if not enforce:
        return []
    text = {"on": "on", "off": "off"}.get(enforce, f"unknown ({enforce.removeprefix('unknown: ')})")
    lines = [f"Enforce Unity Gateway is currently **{text}** in this workspace."]
    if enforce == "on" and status == "BLOCKED":
        lines.append("Enforce is already on, so the blockers below are calls that fail now.")
    return lines + [""]


def readiness_md(ws_url: str, r: dict, days: int) -> str:
    from collections import Counter
    import shlex
    status = r["status"]
    lines = ["# Enforce Unity Gateway readiness", "", f"Workspace: {ws_url}",
             f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} (traffic window {days} days) "
             f"by unity-gateway-migration-toolkit {__version__}",
             f"Legacy endpoints (v1 and v2) retire on {deadline_text()} ({DEADLINE_AS_OF}).", "",
             f"> {DISCLAIMER}", "",
             f"**Status: {status}**", "", *_enforce_lines(r.get("enforce"), status), "## Status", "",
             *[f"- **{k}**: {v}" for k, v in STATUS_MEANING.items()], "",
             "## Next steps", "", *[f"{i}. {s}" for i, s in enumerate(_next_steps(r), 1)], ""]
    if r.get("scan_roots"):
        lines += [f"Workspace folders scanned: {', '.join(r['scan_roots'])}", ""]
    lines += ["## Glossary", "", *[f"- {g}" for g in glossary()], ""]
    if r["blockers"]:
        lines += [f"## Blockers ({len(r['blockers'])})", "", "| Finding | Count |", "|---|---|",
                  *[f"| {_md(k)} | {v} |" for k, v in Counter(b["label"] for b in r["blockers"]).most_common()], ""]
        lines += _capped([f"- **{b['label']}** ({b['item']}): {b['detail'].rstrip('.')}. Action: {b['action']}."
                          for b in r["blockers"]], 60, "readiness.json") + [""]
    if r["warnings"]:
        lines += [f"## Warnings ({len(r['warnings'])}): code that will break if it still runs", "",
                  "| Finding | Count |", "|---|---|",
                  *[f"| {_md(k)} | {v} |" for k, v in Counter(w["label"] for w in r["warnings"]).most_common()], "",
                  *_capped([f"- **{w['label']}** ({w['item']}): {w['detail'].rstrip('.')}. Action: {w['action']}."
                            for w in r["warnings"]], 60, "readiness.json"), "",
                  "Every warning is in readiness.json. Each code location is in client_references.csv, with the "
                  "proposed change in CODE_FIXES.md.", ""]
    if r.get("coverage_gaps"):
        lines += ["## Incomplete scan", "", "These surfaces weren't fully scanned, so readiness and close "
                  "suggestions can't be trusted until they are:", "", "| Surface | Status |", "|---|---|",
                  *[f"| {_md(k)} | {_md(v)} |" for k, v in sorted(r["coverage_gaps"].items())], ""]
    if r.get("notes"):
        lines += ["## Not covered (notes, not gaps)", "", "| Surface | Status |", "|---|---|",
                  *[f"| {_md(k)} | {_md(v)} |" for k, v in sorted(r["notes"].items())], ""]
    if r["rate_limit_zero_candidates"]:
        lines += ["## Can be stopped now (no new service needed)", "",
                  "External model endpoints with no traffic in the window, no code references and no dependents. "
                  "The command sets the endpoint's rate limit to 0 calls per minute, which Databricks documents as "
                  "a deny-all limit (it can take up to 60 seconds to apply). It keeps the endpoint's other rate limits "
                  "and settings; the undo command restores the current config. Usage covers only the traffic window: "
                  "confirm with the owner first.", "",
                  "The second column says whether the Unity Gateway service that would replace the endpoint already "
                  "exists. Stopping doesn't need it; migrating does (apply creates it).", "",
                  "| Endpoint | Replacement service exists |", "|---|---|",
                  *[f"| {_md(c['endpoint'])} | {'yes' if c['target_ready'] else 'no (apply creates it)'} |"
                    for c in r["rate_limit_zero_candidates"]], "", "```bash"]
        for c in r["rate_limit_zero_candidates"]:
            path = f"/api/2.0/serving-endpoints/{c['endpoint']}/ai-gateway"
            lines.append(f"# stop {c['endpoint']}")
            lines.append(f"databricks api put {shlex.quote(path)} --json {shlex.quote(json.dumps(c['ai_gateway_body']))}")
            lines.append(f"# undo {c['endpoint']}")
            lines.append(f"databricks api put {shlex.quote(path)} --json {shlex.quote(json.dumps(c['undo_body']))}")
        lines += ["```", ""]
    lines += ["## What Enforce does", "",
              "Enforce Unity Gateway is a workspace admin setting (Settings > Advanced > Enforce Unity Gateway, per the AI "
              "Gateway migration docs). When it is on, legacy `databricks-*` pay-per-token endpoints stop serving: calls to them fail "
              "with PERMISSION_DENIED (HTTP 403). Existing callers are not redirected automatically. New external "
              "model and provisioned throughput endpoints must be created through Unity Gateway. Existing external "
              f"model and PT endpoints stay queryable until they retire ({deadline_text()}), so migrate their callers too.", "",
              f"Zero requests in the last {days} days is not proof that nothing calls an endpoint: callers that "
              "moved recently, jobs that run less often than the window, and endpoints with usage tracking off all "
              "look the same. Confirm with the owners before enforcing.", ""]
    return "\n".join(lines) + "\n"


def code_fixes_md(refs: list[ClientReference]) -> str:
    """Proposed line changes grouped by file (a reviewable pseudo-diff), then the references that need a manual edit."""
    fixable = [r for r in refs if r.fixed_line and r.fixed_line != r.line_text]
    manual = [r for r in refs if not (r.fixed_line and r.fixed_line != r.line_text)]
    by_asset: dict[str, list[ClientReference]] = {}
    for r in fixable:
        by_asset.setdefault(r.asset, []).append(r)
    lines = ["# Proposed code fixes", "", f"> {DISCLAIMER}", "",
             f"{_n(len(fixable), 'proposed line change')} across {_n(len(by_asset), 'file')} (each one needs a review "
             f"before it is applied), and {len(manual)} references need a manual edit (listed at the end). Nothing was changed: "
             "apply these in the source (and its Git repo if there is one), then re-run.", ""]
    if fixable:
        lines += ["## Proposed line changes", ""]
    for asset, items in sorted(by_asset.items()):
        lines += [f"### {asset}", "", "```diff"]
        for r in sorted(items, key=lambda r: r.line or 0):
            lines += [f"@@ line {r.line} @@", f"- {r.line_text}", f"+ {r.fixed_line}", f"# note: {r.suggestion}"]
        lines += ["```", ""]
    if manual:
        lines += [f"## References that need a manual edit ({len(manual)})", "",
                  "No safe one-line rewrite exists for these. Each one shows where it is and what to do.", ""]
        for r in sorted(manual, key=lambda r: (r.asset, r.line or 0)):
            loc = r.asset + (f":{r.line}" if r.line else "")
            lines.append(f"- `{r.match[:80]}` in {loc} ({_ref_text(r)[0].lower()}): {r.suggestion}")
        lines.append("")
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
               refs: list[ClientReference], days: int, traffic_ok: bool, callers: list[dict] | None = None,
               status: str | None = None) -> str:
    from collections import Counter
    kinds = Counter(e.kind for e in endpoints)
    actions = Counter(r.action for r in rows)
    active = [r for r in rows if r.requests_window > 0]
    v2_total = sum(r.v2_requests for r in rows)
    lines = [
        "# Unity Gateway migration plan (prototype, read-only)",
        "",
        f"Workspace: {ws_url}",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} by unity-gateway-migration-toolkit {__version__}",
        "",
    ]
    if status:
        lines += [f"Status: {status}. Start with READINESS.md.", ""]
    lines += [f"Legacy endpoints (v1 and v2) retire on {deadline_text()} ({DEADLINE_AS_OF}).", ""]
    lines += [f"> {DISCLAIMER}", "", "## Glossary", "", *[f"- {g}" for g in glossary()], "",
              "## Endpoints", "",
              "| Kind | Count |", "|---|---|",
              *[f"| {_md(KIND_NAMES.get(k, k))} | {v} |" for k, v in kinds.most_common()],
              "",
              "| Plan action | Count |", "|---|---|",
              *[f"| {_md(ACTION_NAMES.get(k, k))} | {v} |" for k, v in actions.most_common()],
              "",
              (f"{_n(len(active), 'endpoint')} had traffic in the last {days} days." if traffic_ok
               else "Traffic not available (system.serving tables need account admin access or a warehouse)."),
              ""]
    v2_only = [e for e in endpoints if e.kind == "v2_workspace_endpoint"]
    if v2_only:
        lines += [f"{_n(len(v2_only), 'workspace-bound AI Gateway v2 endpoint')} found in system.ai_gateway.usage. They "
                  "are not serving endpoints, so the serving list doesn't show them.", ""]
    if v2_total:
        lines += [f"{v2_total:,} of those requests were AI Gateway v2 traffic (all legacy endpoints retire on "
                  f"{deadline_text()}).", ""]
    failing = [r for r in rows if v2_mostly_failing(r)]
    if failing:
        lines += [f"v2 calls already failing (v2 is off for this workspace): "
                  + "; ".join(f"{_md(r.legacy_endpoint)} ({r.v2_failed:,} of {r.v2_requests:,} failed, "
                              f"{r.v2_status_501:,} with HTTP 501)" for r in failing) + ".", ""]
    tokens_total = sum(r.tokens_window for r in rows)
    if tokens_total:
        lines += [f"{tokens_total:,} input and output tokens in the window (v1 and v2). Shown for sizing only: "
                  "readiness uses requests.", ""]
    if active:
        lines += ["| Endpoint | Kind | Requests | Tokens | Requesters | Last request | Target |",
                  "|---|---|---|---|---|---|---|"]
        for r in sorted(active, key=lambda r: -r.requests_window)[:25]:
            lines.append(f"| {_md(r.legacy_endpoint)} | {_md(KIND_NAMES.get(r.kind, r.kind))} | {r.requests_window} | "
                         f"{r.tokens_window:,} | {r.requesters} | {r.last_request} | {r.target_service or '-'} |")
        lines.append("")
    if callers:
        lines += ["## Who calls legacy endpoints", "", "| Endpoint | Caller | Caller type | API | Requests | Last request | Code found |",
                  "|---|---|---|---|---|---|---|"]
        for c in sorted(callers, key=lambda c: -int(c["requests"] or 0))[:30]:
            code = "; ".join(c["linked_code"][:2]) + (f" (+{c['linked_count'] - 2})" if c["linked_count"] > 2 else "")
            lines.append(f"| {_md(c['endpoint_name'])} | {_md(c['requester_name'])} | {_md(c.get('caller_class'))} | "
                         f"{_md(c.get('api'))} | {c['requests']} | "
                         f"{c['last_request']} | {_md(code or 'no code found: check jobs, external apps or local code')} |")
        lines += ["", "Caller type: platform = Databricks-managed (warning, not a blocker); coding_agent = move with ucode; "
                  "see the glossary.", ""]
        lines.append("")
    if providers:
        lines += ["## Provider services", "", "Status: automated (apply creates it), manual_supported (Unity Gateway "
                  "supports it, apply doesn't), no_ug_provider (Unity Gateway has no such provider).", "",
                  "| Provider service | Provider | Status | Models | Legacy endpoints | Secrets |", "|---|---|---|---|---|---|"]
        for p in providers:
            lines.append(f"| {p['provider_service']} | {p['provider']} | {p.get('provider_status') or '-'} | "
                         f"{', '.join(p['models'])} | {len(p['legacy_endpoints'])} | {', '.join(p['secrets']) or '-'} |")
        lines.append("")
    human = [r for r in rows if r.needs_human]
    if human:
        plaintext = sum(1 for r in rows if PLAINTEXT_KEY_NEED in r.needs_human)
        lines += [f"## Needs a human ({_n(len(human), 'endpoint')})", ""]
        if plaintext:
            lines += [f"Plaintext API keys: {_n(plaintext, 'endpoint')} with a key stored in plaintext in the endpoint config (values not "
                      "shown). Move each key to a secret scope or Unity Catalog secret before migrating.", ""]
        lines += _capped([f"- **{r.legacy_endpoint}** ({KIND_NAMES.get(r.kind, r.kind)}): "
                          + "; ".join(n.rstrip(".") for n in r.needs_human)
                          for r in human], 50, "migration_plan.csv") + [""]
    by_label = Counter(_ref_text(r)[0] for r in refs)
    lines += ["## Client references", "", f"{_n(len(refs), 'reference')} in code and jobs.", "",
              "| Finding | Count |", "|---|---|",
              *[f"| {_md(k)} | {v} |" for k, v in by_label.most_common()], ""]
    for r in refs[:40]:
        loc = f"{r.asset}" + (f":{r.line}" if r.line else "")
        lines.append(f"- `{r.match[:80]}` in {loc} ({r.asset_type}): {r.suggestion}")
    if len(refs) > 40:
        lines.append(f"- ... {len(refs) - 40} more in client_references.csv")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


DEFAULT_SCAN_ROOTS = ["/Users", "/Shared", "/Repos"]


def run(w: WorkspaceClient, out_dir: str, warehouse_id: str | None = None, days: int = 30,
        target_catalog: str = "ai_gateway", target_schema: str = "migrated",
        scan_roots: list[str] | None = None, max_objects: int = 20000, skip_scan: bool = False,
        workspace_id: str | None = None, threads: int = 16, local_paths: list[str] | None = None,
        allow_spark: bool = True, ack_guardrails: bool = False, deadline: str | None = None,
        remote: bool = False) -> dict:
    """Plan and scan one workspace. deadline (ISO date) overrides the legacy retirement date for this run only.

    remote: w is another workspace of the account (central mode) while Spark runs in the hub. System tables are
    account-wide, so traffic still comes from Spark; Unity Catalog definitions are per metastore, so they're
    left out (and noted) rather than read from the hub's metastore."""
    global ALLOW_SPARK, LEGACY_DEADLINE, REMOTE_SCAN
    previous, ALLOW_SPARK = ALLOW_SPARK, allow_spark
    previous_remote, REMOTE_SCAN = REMOTE_SCAN, remote
    previous_deadline = LEGACY_DEADLINE
    if deadline:
        LEGACY_DEADLINE = validate_deadline(deadline)
    try:
        return _run(w, out_dir, warehouse_id, days, target_catalog, target_schema, scan_roots, max_objects,
                    skip_scan, workspace_id, threads, local_paths, ack_guardrails)
    finally:
        ALLOW_SPARK = previous
        REMOTE_SCAN = previous_remote
        LEGACY_DEADLINE = previous_deadline


def _run(w, out_dir, warehouse_id, days, target_catalog, target_schema, scan_roots, max_objects, skip_scan,
         workspace_id, threads, local_paths, ack_guardrails=False) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    ws_url = w.config.host
    workspace_id = workspace_id or workspace_id_of(w)
    _log(f"Workspace {ws_url} ({workspace_id})")
    coverage: dict[str, str] = {}
    target_api_types: dict[str, list[str]] = {}

    _log("1. Inventory")
    endpoints = inventory(w)
    sys_map = system_ai_map(w, coverage, target_api_types)
    uc_models = system_ai_uc_models(w, coverage)

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
        try:
            unmatched = unattributed_v1(w, warehouse_id, workspace_id, days)
        except Exception as error:
            coverage["v1_unattributed"] = f"failed: {str(error)[:120]}"
        else:
            coverage["v1_unattributed"] = (f"{UNATTRIBUTED_NOTE}: {unmatched:,} v1 requests in {days} days have no "
                                           "served_entities match, so they aren't counted for any endpoint"
                                           if unmatched else "ok")
    except Exception as error:
        traffic_ok = False
        traffic_status = f"failed: {str(error)[:200]}"
    if not traffic_ok:
        _log(f"  traffic not confirmed: {traffic_status}")
    # Workspace-bound v2 endpoints exist only in the traffic: add the ones with v2 requests in the window, and the
    # dormant ones seen before it, so the scan still finds code that names them.
    dormant: list[str] = []
    if traffic_ok:
        try:
            dormant = [n for n in v2_endpoint_history(w, warehouse_id, workspace_id, max(days, V2_HISTORY_DAYS))
                       if not int((usage.get(n) or {}).get("v2_requests") or 0)]
        except Exception as error:
            coverage["v2_history"] = f"failed: {str(error)[:120]}"
        else:
            coverage["v2_history"] = "ok"
    v2_endpoints = v2_workspace_endpoints(usage, (e.name for e in endpoints), dormant)
    if v2_endpoints:
        _log(f"  {len(v2_endpoints)} workspace-bound AI Gateway v2 endpoints (not in the serving list)")
    endpoints += v2_endpoints

    _log("3. Plan")
    rows, providers = plan(endpoints, sys_map, usage, target_catalog, target_schema, traffic_ok, ack_guardrails,
                           target_api_types, uc_models)
    check_targets(w, rows)

    refs: list[ClientReference] = []
    roots: list[str] = []
    if not skip_scan:
        _log("4. Client reference scan")
        roots = list(scan_roots or DEFAULT_SCAN_ROOTS)
        if scan_roots and set(scan_roots) != set(DEFAULT_SCAN_ROOTS):
            coverage["scan_roots"] = (f"partial: only {', '.join(scan_roots)} "
                                      f"(defaults {', '.join(DEFAULT_SCAN_ROOTS)} narrowed)")
        else:
            coverage["scan_roots"] = "ok"
        # Never walked, whatever the roots: say so, so READY isn't read as "every file was searched".
        coverage["volumes_dbfs"] = VOLUMES_NOTE
        toolkit_paths: list[str] = []
        toolkit_apps: list[str] = []
        app_roots = app_source_roots(w, coverage, toolkit_paths, toolkit_apps)
        roots += [r for r in app_roots if r not in roots]
        scanner = Scanner((e.name for e in endpoints), sys_map, rows,
                          {e.endpoint_url: e.name for e in endpoints if e.endpoint_url},
                          custom_models={e.name: d.get("model") for e in endpoints if e.kind in ("custom_model", "agent")
                                         for d in e.destinations if d.get("model")},
                          v2_names=[e.name for e in endpoints if e.kind == "v2_workspace_endpoint"]
                          + [n for n, u in usage.items() if int(u.get("v2_requests") or 0)],
                          target_api_types=target_api_types)
        scan_workspace(w, scanner, roots, max_objects, threads, toolkit_paths)
        scan_jobs(w, scanner)
        scan_sql_queries(w, scanner, threads)
        scan_dashboards(w, scanner)
        scan_apps(w, scanner, toolkit_apps)
        scan_vector_search(w, scanner)
        scan_agent_bricks(w, scanner)
        scan_genie(w, scanner, threads)
        scan_custom_endpoints(w, scanner, endpoints)
        scan_uc_sql(w, scanner, warehouse_id)
        scan_pipelines(w, scanner)
        if local_paths:
            scan_local(scanner, local_paths)
        else:
            coverage["local_files"] = ("not scanned: no --local-path given, so cloned repos and bundle folders "
                                       "on a laptop are not covered")
        coverage.update(scanner.coverage)
        refs = scanner.refs
        annotate_dependencies(rows, refs, days)
        annotate_agent_bricks(rows, scanner.agent_bricks)

    _write_csv(os.path.join(out_dir, "legacy_endpoints.csv"), [asdict(e) for e in endpoints])
    _write_csv(os.path.join(out_dir, "migration_plan.csv"), [asdict(r) for r in rows])
    _write_csv(os.path.join(out_dir, "provider_services.csv"),
               [{k: v for k, v in p.items() if k != "provider_key"} for p in providers])
    _write_csv(os.path.join(out_dir, "client_references.csv"), [asdict(r) for r in refs])
    callers = link_callers(by_req, refs, resolve_requesters(w, (r.get("requester") for r in by_req)))
    _write_csv(os.path.join(out_dir, "callers.csv"), callers)
    with open(os.path.join(out_dir, "system_ai_map.json"), "w") as f:
        json.dump(sys_map, f, indent=1, sort_keys=True)
    # The named callers: readiness reads requester_name (a custom agent's identity is "System Service Principal").
    ready = readiness(rows, refs, traffic_ok, days, endpoints, coverage, scanned=not skip_scan, callers=callers)
    ready["traffic_status"] = traffic_status
    ready["workspace_id"] = workspace_id
    ready["enforce"] = enforce_status(w)
    ready["scan_roots"] = roots
    with open(os.path.join(out_dir, "READINESS.md"), "w") as f:
        f.write(readiness_md(ws_url, ready, days))
    with open(os.path.join(out_dir, "readiness.json"), "w") as f:
        json.dump(ready, f, indent=1)
    with open(os.path.join(out_dir, "CODE_FIXES.md"), "w") as f:
        f.write(code_fixes_md(refs))
    with open(os.path.join(out_dir, "SUMMARY.md"), "w") as f:
        f.write(summary_md(ws_url, endpoints, rows, providers, refs, days, traffic_ok, callers, ready["status"]))
    _log(f"Done. Results in {out_dir}")
    return {"version": __version__, "endpoints": len(endpoints), "plan_rows": len(rows), "providers": len(providers),
            "v2_workspace_endpoints": len(v2_endpoints), "client_references": len(refs), "traffic_ok": traffic_ok,
            "readiness": ready["status"], "deadline": LEGACY_DEADLINE}


def _deadline_arg(value: str) -> str:
    try:
        return validate_deadline(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--profile", help="Databricks CLI profile")
    p.add_argument("--warehouse-id", help="SQL warehouse for system table queries")
    p.add_argument("--out", default="./ug_migration_out", help='Output folder (default ./ug_migration_out)')
    p.add_argument("--days", type=int, default=30, help='Traffic window in days (default 30)')
    p.add_argument("--target-catalog", default="ai_gateway", help='Catalog the plan targets for new model services (default ai_gateway)')
    p.add_argument("--target-schema", default="migrated", help='Schema the plan targets for new model services (default migrated)')
    p.add_argument("--scan-root", action="append", help="Workspace path to scan (repeatable; replaces the defaults /Users, /Shared, /Repos)")
    p.add_argument("--max-objects", type=int, default=20000, help='Stop listing workspace files after this many per root (default 20000)')
    p.add_argument("--workspace-id", help="Override the detected workspace ID")
    p.add_argument("--threads", type=int, default=16, help='Parallel API calls for the code scan (default 16)')
    p.add_argument("--local-path", action="append", help="Also scan this local folder, e.g. a cloned repo (repeatable)")
    p.add_argument("--skip-scan", action="store_true", help='Skip the code scan (inventory, traffic and plan only)')
    p.add_argument("--ack-guardrails", action="store_true",
                   help="Accept that legacy guardrails aren't carried over; without it, endpoints with guardrails block apply")
    p.add_argument("--deadline", type=_deadline_arg, default=None,
                   help=f"Retirement date for all legacy endpoints (v1 and v2), ISO format (default {LEGACY_DEADLINE}; "
                        "confirmed as of 2026-11-01)")
    a = p.parse_args(argv)
    w = WorkspaceClient(profile=a.profile) if a.profile else WorkspaceClient()
    result = run(w, a.out, a.warehouse_id, a.days, a.target_catalog, a.target_schema,
                 a.scan_root, a.max_objects, a.skip_scan, a.workspace_id, a.threads, a.local_path,
                 ack_guardrails=a.ack_guardrails, deadline=a.deadline)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
