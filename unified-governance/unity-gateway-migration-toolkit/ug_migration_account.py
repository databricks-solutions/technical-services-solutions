"""Unity Gateway migration: account-wide view (prototype; read-only unless you ask for snapshots).

Uses account-level system tables, so one query covers every workspace:
  system.serving.served_entities   legacy (v1) endpoints and what they serve
  system.serving.endpoint_usage    legacy (v1) traffic and callers
  system.ai_gateway.usage          Unity Gateway (v3) traffic, v2 workspace endpoints and their callers
  system.access.workspaces_latest  workspace names, URLs and status
  system.billing.usage             product activity (AI Search, Apps, Agent Bricks, AI Functions)

It ranks workspaces, proposes migration waves, splits legacy traffic into customer-owned and Databricks-managed,
flags custom endpoint names that repeat across workspaces (they'd collide in one target schema), and can
deep-scan selected workspaces with ug_migration_planner.

    python ug_migration_account.py --profile P --warehouse-id W --out ./account_out
    python ug_migration_account.py --profile P --warehouse-id W --out ./account_out --deep-scan 3
    python ug_migration_account.py --profile P --warehouse-id W --out ./account_out --wave 0 --deep-scan 5
    python ug_migration_account.py --profile P --warehouse-id W --out ./account_out --deadline 2027-03-30

Wave 0 means "no legacy traffic seen", not "ready". A workspace is ready only after a passing workspace scan
(READY or READY_WITH_WARNINGS) exists; the app's overview joins the scan results for that.

Deep scans connect to each workspace URL with the default auth chain (a
service principal in DATABRICKS_CLIENT_ID / DATABRICKS_CLIENT_SECRET that is
assigned to the workspaces, or a CLI login for each host). Each connection is
checked against the target workspace ID before anything runs.

Needs read access to the system tables (account admin by default). Written by
STS as a prototype; not an official Databricks tool.
"""

from __future__ import annotations

import argparse
import json
import re
import os
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone

from databricks.sdk import WorkspaceClient

import ug_migration_planner as planner

HISTORY_DAYS = 365  # last-seen check, "traffic unknown" test and billing lookback
TEN_K = 10_000

# Wave names (the app's overview matches on these; keep in sync with app/backend/main.py)
W_HIGH = "2: high volume"
W_V2 = "v2 traffic"
W_SMALL = "1: small"
W_CLEANUP = "1: cleanup"
W_UNKNOWN_TRAFFIC = "0: traffic unknown"
W_NO_TRAFFIC = "0: no legacy traffic"
W_NO_DATA = "no endpoint data"
W_NOT_RUNNING = "not running"
W_UNKNOWN = "unknown"
W_CUSTOM_ONLY = "no legacy endpoints (custom ML only)"
# Old wave names still found in snapshots: "v2 first" was renamed when the v2 deadline went away (one date now).
LEGACY_WAVE_NAMES = {"v2 first": W_V2, "0: enforce candidate": W_NO_TRAFFIC}
# Meaning of each wave, in the order the rules in build() apply them (volume first, then risk). Shown in
# ACCOUNT_SUMMARY.md. Thresholds are the rules in build().
WAVE_MEANING = {
    W_HIGH: f"Legacy requests (v1 + v2) of {TEN_K:,} or more in the window.",
    W_V2: "Workspace with v2 requests below the high-volume line. v2 endpoints are workspace-bound and not in the "
          "serving inventory, so only traffic shows them: they rank above small v1 traffic for that reason.",
    W_SMALL: f"v1 requests from 1 to {TEN_K - 1:,} in the window, and no v2 requests.",
    W_CLEANUP: "No v1 traffic, but external model, provisioned throughput or other endpoints exist. They block wave 0 "
               "until they are retired or applied.",
    W_UNKNOWN_TRAFFIC: "Live legacy endpoints with no usage rows in the history window (usage tracking may be off). "
                       "Not a candidate until a workspace scan confirms.",
    W_NO_TRAFFIC: "No v1 or v2 requests in the window and no unknown endpoints. A candidate only: a passing workspace "
                  "scan (READY or READY_WITH_WARNINGS) is required.",
    W_CUSTOM_ONLY: "Only custom ML or feature serving endpoints, which this toolkit doesn't migrate. Nothing to migrate, "
                   "but notebooks and jobs here can still call legacy pay-per-token endpoints: scan it with --workspace "
                   "before Enforce. Not counted as no-traffic, so --wave 0 skips it.",
    W_NO_DATA: "Running workspace with no served-entity, usage or AI Gateway rows. Only a workspace scan can say whether "
               "anything needs migrating.",
    W_NOT_RUNNING: "Workspace status isn't RUNNING. Not counted in the running total.",
    W_UNKNOWN: "A required account query failed, so nothing can be decided for this workspace.",
}

# One retirement date for every legacy endpoint: v1 and v2, pay-per-token, embeddings, provisioned throughput and
# external (confirmed as of 2026-11-01). Custom model and feature serving endpoints aren't
# affected. Override with UGMIG_DEADLINE or --deadline when the date moves.
DEADLINE_AS_OF = "2026-11-01"
LEGACY_DEADLINE = os.environ.get("UGMIG_DEADLINE", "2027-03-30")

INVENTORY_SQL = """
-- Live endpoints: latest row per served entity, only entities in the endpoint's latest config version.
WITH latest AS (
  SELECT *,
         row_number() OVER (PARTITION BY workspace_id, endpoint_id, served_entity_name ORDER BY change_time DESC) AS rn,
         max(endpoint_config_version) OVER (PARTITION BY workspace_id, endpoint_id) AS latest_version
  FROM system.serving.served_entities
)
SELECT workspace_id, endpoint_name, endpoint_id, served_entity_name, entity_type, entity_name, task,
       external_model_config.provider AS provider,
       foundation_model_config.max_provisioned_throughput IS NOT NULL AS is_pt,
       created_by
FROM latest
WHERE rn = 1 AND endpoint_delete_time IS NULL
  AND (endpoint_config_version = latest_version OR latest_version IS NULL)
"""

# One row per endpoint. Window columns cover the traffic window; last_seen looks back over the history.
V1_TRAFFIC_SQL = """
SELECT eu.workspace_id, se.endpoint_id, max(se.endpoint_name) AS endpoint_name,
       count(DISTINCT CASE WHEN eu.request_time >= current_timestamp() - INTERVAL {days} DAYS
                           THEN eu.databricks_request_id END) AS requests,
       count(DISTINCT CASE WHEN eu.request_time >= current_timestamp() - INTERVAL {days} DAYS
                           THEN eu.requester END) AS requesters,
       count(DISTINCT CASE WHEN eu.request_time >= current_timestamp() - INTERVAL {days} DAYS AND eu.status_code = 429
                           THEN eu.databricks_request_id END) AS throttled,
       sum(CASE WHEN eu.request_time >= current_timestamp() - INTERVAL {days} DAYS
                THEN coalesce(eu.input_token_count, 0) + coalesce(eu.output_token_count, 0) END) AS tokens,
       CAST(max(CASE WHEN eu.request_time >= current_timestamp() - INTERVAL {days} DAYS
                     THEN eu.request_time END) AS STRING) AS last_request,
       CAST(max(eu.request_time) AS STRING) AS last_seen
FROM system.serving.endpoint_usage AS eu
JOIN (SELECT DISTINCT served_entity_id, endpoint_id, endpoint_name FROM system.serving.served_entities) AS se
  ON eu.served_entity_id = se.served_entity_id
WHERE eu.request_time >= current_timestamp() - INTERVAL {history} DAYS
GROUP BY eu.workspace_id, se.endpoint_id
"""

# v1 requests by caller (requester is a service principal UUID or a user email). Counts sum to V1_TRAFFIC_SQL requests.
V1_CLASS_SQL = """
SELECT eu.workspace_id, se.endpoint_id, max(se.endpoint_name) AS endpoint_name, eu.requester,
       count(DISTINCT eu.databricks_request_id) AS requests
FROM system.serving.endpoint_usage AS eu
JOIN (SELECT DISTINCT served_entity_id, endpoint_id, endpoint_name FROM system.serving.served_entities) AS se
  ON eu.served_entity_id = se.served_entity_id
WHERE eu.request_time >= current_timestamp() - INTERVAL {days} DAYS
GROUP BY eu.workspace_id, se.endpoint_id, eu.requester
"""

UG_TRAFFIC_SQL = """
-- One row per invocation in ai_gateway.usage, so count distinct request IDs.
-- v2 = rows with no service_type (undocumented NULL in the schema; verified against live rows).
-- v2_failed: no status code, or status 0 or 501 (other 4xx and 5xx can be caller, permission, rate-limit or provider errors, not a gateway that is off) (the planner's rule). v2_tokens: total_tokens.
SELECT workspace_id,
       count(DISTINCT CASE WHEN service_type = 'MODEL_SERVICE' THEN request_id END) AS v3_requests,
       count(DISTINCT CASE WHEN service_type = 'MODEL_SERVICE' THEN requester END) AS v3_requesters,
       count(DISTINCT CASE WHEN service_type IS NULL AND endpoint_name IS NOT NULL THEN request_id END) AS v2_requests,
       count(DISTINCT CASE WHEN service_type IS NULL AND endpoint_name IS NOT NULL
                           AND (status_code IS NULL OR status_code IN (0, 501)) THEN request_id END)
         AS v2_failed,
       coalesce(sum(CASE WHEN service_type IS NULL AND endpoint_name IS NOT NULL THEN total_tokens END), 0) AS v2_tokens,
       CAST(max(CASE WHEN service_type IS NULL AND endpoint_name IS NOT NULL THEN event_time END) AS STRING)
         AS v2_last_request
FROM system.ai_gateway.usage
WHERE event_time >= current_timestamp() - INTERVAL {days} DAYS
GROUP BY workspace_id
"""

# v2 workspace-bound endpoints. They have no endpoint ID and no served-entity row, so the name is the key. Window
# counts cover the traffic window; last_seen looks back over the history.
V2_ENDPOINT_SQL = """
SELECT workspace_id, endpoint_name,
       count(DISTINCT CASE WHEN event_time >= current_timestamp() - INTERVAL {days} DAYS THEN request_id END) AS requests,
       count(DISTINCT CASE WHEN event_time >= current_timestamp() - INTERVAL {days} DAYS THEN requester END) AS requesters,
       coalesce(sum(CASE WHEN event_time >= current_timestamp() - INTERVAL {days} DAYS THEN total_tokens END), 0)
         AS tokens,
       CAST(max(CASE WHEN event_time >= current_timestamp() - INTERVAL {days} DAYS THEN event_time END) AS STRING)
         AS last_request,
       CAST(max(event_time) AS STRING) AS last_seen
FROM system.ai_gateway.usage
WHERE event_time >= current_timestamp() - INTERVAL {history} DAYS
  AND service_type IS NULL AND endpoint_name IS NOT NULL
GROUP BY workspace_id, endpoint_name
"""

# v2 requests by caller. url is only a set/unset flag here (the caller classes need no more than that).
V2_CLASS_SQL = """
SELECT workspace_id, endpoint_name, user_agent,
       CASE WHEN url IS NULL THEN NULL ELSE 'set' END AS url, requester,
       count(DISTINCT request_id) AS requests
FROM system.ai_gateway.usage
WHERE event_time >= current_timestamp() - INTERVAL {days} DAYS
  AND service_type IS NULL AND endpoint_name IS NOT NULL
GROUP BY 1, 2, 3, 4, 5
"""
WORKSPACES_SQL = """
SELECT workspace_id, workspace_name, workspace_url, status FROM system.access.workspaces_latest
"""
CONFIG_SQL = """
-- Product activity per workspace over the history window: blockers the traffic tables can't see.
SELECT workspace_id, billing_origin_product
FROM system.billing.usage
WHERE usage_date >= current_date() - INTERVAL {history} DAYS
  AND billing_origin_product IN ('VECTOR_SEARCH', 'AGENT_BRICKS', 'SUPERVISOR_AGENT', 'APPS', 'AI_FUNCTIONS')
GROUP BY workspace_id, billing_origin_product
"""
CONFIG_LABELS = {
    "VECTOR_SEARCH": "AI Search: keep embedding endpoints its indexes use",
    "AGENT_BRICKS": "Agent Bricks: check its vector search and endpoints",
    "SUPERVISOR_AGENT": "Agent Bricks supervisor: check its endpoints",
    "APPS": "Databricks Apps: check serving endpoint resources",
    "AI_FUNCTIONS": "AI Functions: ai_query may call legacy endpoints",
}
DELETED = "deleted_or_unknown"
V2_KIND = "v2_workspace_endpoint"

# Caller classes (classes of requests, by who sent them). The planner applies the same rules in caller_class(); keep
# them in sync. First match wins. USER_GUIDE.md, Caller types, lists the classes.
CODING_AGENT_TOKENS = ("claude-code", "opencode", "codex", "cursor", "copilot", "gemini-cli", "aider")
SDK_TOKENS = ("databricks-sdk", "mlflow")
LLM_SDK_TOKENS = ("openai", "litellm", "anthropic", "langchain")
HTTP_TOKENS = ("python-requests", "curl", "axios", "go-http", "java")
SYSTEM_REQUESTERS = {"system", "databricks", "databricks-system"}  # same as the planner
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
CUSTOMER_CLASS_NOTE = ("customer-owned: every class except platform (known Databricks system identities). v2 calls "
                       "with no client information (most likely ai_query or batch from notebooks and jobs) count as "
                       "customer-owned. v1 rows have no user agent, so their Databricks-managed share can't be seen "
                       "and counts as customer-owned.")


def caller_class(user_agent: str | None, url: str | None, requester: str | None, source: str = "v2") -> str:
    """Who sent one request, from its system table row.

    source "v1" (system.serving.endpoint_usage has no user agent or URL columns): requester UUID is a
    service principal, requester with "@" is a user, anything else is unknown.
    source "v2" (system.ai_gateway.usage): a known Databricks system identity is platform; no user agent and no URL
    is no_client_info (measured: user identities, bursty, so most likely ai_query or batch from notebooks and
    jobs; it counts as customer-owned); otherwise the user agent decides: coding agent, SDK, LLM SDK, HTTP
    client, else unknown.
    Coding agents are checked before SDKs because their agent tag arrives inside a databricks-sdk user agent.
    """
    if (requester or "").strip().lower() in SYSTEM_REQUESTERS:
        return "platform"
    if source == "v1":
        r = requester or ""
        if UUID_RE.fullmatch(r):
            return "service_principal"
        if "@" in r:
            return "user"
        return "unknown"
    ua = (user_agent or "").lower()
    if not ua and not url:
        return "no_client_info"  # most likely ai_query or batch from notebooks and jobs: customer-owned
    for kind, tokens in (("coding_agent", CODING_AGENT_TOKENS), ("sdk", SDK_TOKENS), ("llm_sdk", LLM_SDK_TOKENS),
                         ("http", HTTP_TOKENS)):
        if any(t in ua for t in tokens):
            return kind
    return "unknown"


def classify(row: dict) -> str:
    t = (row.get("entity_type") or "").upper()
    if t == "EXTERNAL_MODEL":
        return "external_model"
    if t == "FOUNDATION_MODEL":
        if str(row.get("is_pt")).lower() == "true":
            return "provisioned_throughput"
        if (row.get("endpoint_name") or "").startswith("databricks-"):
            return "system_ppt"
        return "foundation_model_other"
    if t in ("CUSTOM_MODEL", "FEATURE_SPEC"):
        return "out_of_scope"
    return "unknown"


def _int(v) -> int:
    """Numbers from SQL results arrive as int, float or strings like '20000' or '20000.0'."""
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


CUSTOM_KINDS = {"external_model", "provisioned_throughput", "foundation_model_other"}


def _md(v) -> str:
    """Markdown table cell text."""
    return str(v if v is not None else "").replace("|", "\\|").replace("\n", " ")


def _day(v) -> str:
    return str(v or "")[:10]


def _v2_key(name) -> str:
    """v2 endpoints have no endpoint ID: their key is the name, kept apart from v1 endpoint IDs."""
    return "v2:" + str(name)


def build(inventory: list[dict], v1: list[dict], ug: list[dict], workspaces: list[dict], days: int,
          config: list[dict] | None = None, history_days: int = HISTORY_DAYS,
          v2_endpoints: list[dict] | None = None, classes: list[dict] | None = None) -> dict:
    """Turn the query rows into endpoint and workspace rows with waves.

    ug and workspaces may be empty when their query failed; the caller marks waves unknown in that case.
    config is None when the billing query failed (config signals are then unknown, not absent).
    v2_endpoints: one row per v2 endpoint name (window requests, last seen over the history window).
    classes: request counts by caller, each with source "v1" or "v2" (see caller_class).
    """
    ws_meta = {str(w["workspace_id"]): w for w in workspaces}
    # One row per endpoint ID (names can be reused after deletion; an endpoint has several entities).
    endpoints: dict[tuple[str, str], dict] = {}
    for r in inventory:
        wid = str(r["workspace_id"])
        key = (wid, str(r.get("endpoint_id") or r["endpoint_name"]))
        e = endpoints.setdefault(key, {"workspace_id": wid, "endpoint_name": r["endpoint_name"],
                                       "kinds": set(), "providers": set(), "entities": 0,
                                       "created_by": r.get("created_by")})
        e["kinds"].add(classify(r))
        if r.get("provider"):
            e["providers"].add(r["provider"])
        e["entities"] += 1
    traffic: dict[tuple[str, str], dict] = {}
    for r in v1:  # duplicate rows are summed, not overwritten
        key = (str(r["workspace_id"]), str(r.get("endpoint_id") or r["endpoint_name"]))
        t = traffic.setdefault(key, {"endpoint_name": r.get("endpoint_name"), "requests": 0, "requesters": 0,
                                     "throttled": 0, "tokens": 0, "last_request": None, "last_seen": None})
        for k in ("requests", "requesters", "throttled", "tokens"):
            t[k] += _int(r.get(k))
        for k in ("last_request", "last_seen"):
            if r.get(k) and (not t[k] or str(r[k]) > str(t[k])):
                t[k] = r[k]
    for r in v2_endpoints or []:
        key = (str(r["workspace_id"]), _v2_key(r["endpoint_name"]))
        endpoints.setdefault(key, {"workspace_id": key[0], "endpoint_name": r["endpoint_name"], "kinds": {V2_KIND},
                                   "providers": set(), "entities": 0, "created_by": None})
        t = traffic.setdefault(key, {"endpoint_name": r["endpoint_name"], "requests": 0, "requesters": 0,
                                     "throttled": 0, "tokens": 0, "last_request": None, "last_seen": None})
        t["requests"] += _int(r.get("requests"))
        t["tokens"] += _int(r.get("tokens"))
        t["requesters"] = max(t["requesters"], _int(r.get("requesters")))
        for k in ("last_request", "last_seen"):
            if r.get(k) and (not t[k] or str(r[k]) > str(t[k])):
                t[k] = r[k]
    for key, t in traffic.items():
        if key not in endpoints:  # traffic to an endpoint deleted since; kept apart from live counts
            endpoints[key] = {"workspace_id": key[0], "endpoint_name": t["endpoint_name"] or key[1],
                              "kinds": {DELETED}, "providers": set(), "entities": 0, "created_by": None}

    def scoped(key: tuple[str, str]) -> bool:
        kinds = endpoints[key]["kinds"]
        return kinds != {DELETED} and bool(kinds - {"out_of_scope"})

    # Caller classes count only in-scope endpoints (the same endpoints the live counts use).
    ep_cls: dict[tuple[str, str], Counter] = defaultdict(Counter)
    ws_cls: dict[str, Counter] = defaultdict(Counter)
    for r in classes or []:
        wid = str(r["workspace_id"])
        v2 = r.get("source") == "v2"
        key = (wid, _v2_key(r["endpoint_name"])) if v2 else (wid, str(r.get("endpoint_id") or r["endpoint_name"]))
        if key not in endpoints or not scoped(key):
            continue
        k = caller_class(r.get("user_agent"), r.get("url"), r.get("requester"), source="v2" if v2 else "v1")
        n = _int(r.get("requests"))
        ep_cls[key][k] += n
        ws_cls[wid][k] += n

    ws: dict[str, Counter] = defaultdict(Counter)
    ws_kinds: dict[str, set] = defaultdict(set)
    ws_last: dict[str, str] = {}
    rows = []
    for key, e in endpoints.items():
        t = traffic.get(key, {})
        kinds = e["kinds"]
        deleted = kinds == {DELETED}
        in_scope = not deleted and bool(kinds - {"out_of_scope"})
        requests = _int(t.get("requests"))
        last_seen = t.get("last_seen")
        if deleted:
            status = "endpoint deleted (traffic only)"
        elif not in_scope:
            status = None
        elif requests:
            status = f"{requests:,} requests in {days} days"
        elif last_seen:
            status = f"no requests in {days} days; last seen {_day(last_seen)}"
        else:
            status = f"no usage rows in {history_days} days: traffic unknown (usage tracking may be off)"
        if in_scope:
            platform = ep_cls[key]["platform"]
            caller = {"customer_requests": max(requests - platform, 0), "platform_requests": platform,
                      "coding_agent_requests": ep_cls[key]["coding_agent"]}
        else:
            caller = {"customer_requests": None, "platform_requests": None, "coding_agent_requests": None}
        rows.append({"workspace_id": e["workspace_id"],
                     "workspace_name": ws_meta.get(e["workspace_id"], {}).get("workspace_name"),
                     "endpoint_name": e["endpoint_name"], "kind": "+".join(sorted(kinds)),
                     "providers": ",".join(sorted(e["providers"])) or None, "served_entities": e["entities"],
                     "requests": requests, "requesters": _int(t.get("requesters")),
                     "throttled": _int(t.get("throttled")), "legacy_tokens": _int(t.get("tokens")),
                     "last_request": t.get("last_request"), "last_seen": last_seen,
                     "traffic_status": status, "created_by": e["created_by"], **caller})
        wid = e["workspace_id"]
        c = ws[wid]
        if deleted:
            c["deleted_endpoints"] += 1
            c["deleted_endpoint_requests"] += requests
        elif not in_scope:
            c["out_of_scope_endpoints"] += 1
            continue
        if last_seen and (wid not in ws_last or str(last_seen) > ws_last[wid]):
            ws_last[wid] = str(last_seen)  # legacy endpoints only (live or deleted), not custom ML endpoints
        if deleted:
            continue
        c["endpoints"] += 1
        if V2_KIND in kinds:  # v2 traffic is counted from the workspace's v2 rows, not as v1 requests
            c["v2_endpoints"] += 1
            if requests:
                c["active_endpoints"] += 1
            continue
        if kinds & CUSTOM_KINDS:
            c["custom_legacy_endpoints"] += 1
            ws_kinds[wid] |= kinds & CUSTOM_KINDS
        if requests:
            c["active_endpoints"] += 1
            c["v1_requests"] += requests
            c["legacy_tokens"] += _int(t.get("tokens"))
            c["throttled"] += _int(t.get("throttled"))
        elif not last_seen:
            c["unknown_traffic_endpoints"] += 1

    ug_by: dict[str, Counter] = {}
    for r in ug:
        u = ug_by.setdefault(str(r["workspace_id"]), Counter())
        for k in ("v3_requests", "v3_requesters", "v2_requests", "v2_failed", "v2_tokens"):
            u[k] += _int(r.get(k))
    cfg: dict[str, set] = defaultdict(set)
    for r in config or []:
        cfg[str(r["workspace_id"])].add(str(r["billing_origin_product"]))

    ws_rows = []
    # Every workspace from the account list, so running workspaces with no endpoint data still show up.
    for wid in set(ws_meta) | set(ws) | set(ug_by) | set(cfg):
        c = ws.get(wid, Counter())
        u = ug_by.get(wid, Counter())
        meta = ws_meta.get(wid, {})
        status = meta.get("status")
        v1n, v2, v3 = c["v1_requests"], _int(u.get("v2_requests")), _int(u.get("v3_requests"))
        v2_failed, v2_tokens = _int(u.get("v2_failed")), _int(u.get("v2_tokens"))
        legacy = v1n + v2
        custom, unknown = c["custom_legacy_endpoints"], c["unknown_traffic_endpoints"]
        platform = ws_cls.get(wid, Counter())["platform"]
        has_data = wid in ws or wid in ug_by
        last = ws_last.get(wid)
        extra = f"; {custom} external model / Provisioned Throughput / other endpoint(s) also present" \
            if custom and legacy else ""
        if status not in (None, "RUNNING"):
            wave, hint = W_NOT_RUNNING, f"workspace status {status}; not counted in the running total"
        elif not has_data:
            wave, hint = W_NO_DATA, ("no served endpoints, v1 traffic or AI Gateway rows in the account tables; "
                                     "only a workspace scan confirms nothing needs migrating")
        elif legacy >= TEN_K:
            wave = W_HIGH
            hint = (f"{legacy:,} legacy requests in {days} days ({v1n:,} v1, {v2:,} v2) from "
                    f"{planner._n(c['active_endpoints'], 'active endpoint')}{extra}")
        elif v2:
            wave = W_V2
            hint = (f"{v2:,} v2 requests in {days} days" + (f" and {v1n:,} v1" if v1n else "") + "; v2 endpoints "
                    "are workspace-bound and not in the serving inventory, so the workspace scan is the check")
        elif v1n:
            wave = W_SMALL
            hint = f"{v1n:,} v1 requests in {days} days from {planner._n(c['active_endpoints'], 'active endpoint')}{extra}"
        elif not c["endpoints"] and c["out_of_scope_endpoints"]:
            wave = W_CUSTOM_ONLY
            hint = (f"only {planner._n(c['out_of_scope_endpoints'], 'custom ML or feature serving endpoint')}; "
                    "nothing for this toolkit to migrate")
        elif custom:
            wave = W_CLEANUP
            hint = (f"no v1 traffic in {days} days, but {custom} external model / Provisioned Throughput / other "
                    f"endpoint(s) ({', '.join(sorted(ws_kinds[wid]))}) block wave 0: retire or apply, then enforce")
        elif unknown:
            wave = W_UNKNOWN_TRAFFIC
            hint = (f"{planner._n(unknown, 'live legacy endpoint')} with no usage rows in {history_days} days; usage "
                    "tracking may be off, so traffic is unverified until a workspace scan")
        else:
            wave = W_NO_TRAFFIC
            hint = f"no v1 requests in {days} days" + (f"; last seen {_day(last)}" if last else "") + \
                ". Not ready: a passing workspace scan is required"
        ws_rows.append({"workspace_id": wid, "workspace_name": meta.get("workspace_name"),
                        "workspace_url": meta.get("workspace_url"), "status": status,
                        "legacy_endpoints": c["endpoints"], "v2_endpoints": c["v2_endpoints"],
                        "custom_legacy_endpoints": custom,
                        "out_of_scope_endpoints": c["out_of_scope_endpoints"], "deleted_endpoints": c["deleted_endpoints"],
                        "active_legacy_endpoints": c["active_endpoints"], "unknown_traffic_endpoints": unknown,
                        "v1_requests": v1n, "v2_requests": v2, "legacy_requests": legacy,
                        "customer_requests": max(legacy - platform, 0), "platform_requests": platform,
                        "coding_agent_requests": ws_cls.get(wid, Counter())["coding_agent"],
                        "legacy_tokens": c["legacy_tokens"] + v2_tokens, "v2_tokens": v2_tokens,
                        "v2_failed": v2_failed, "legacy_throttled": c["throttled"],
                        "deleted_endpoint_requests": c["deleted_endpoint_requests"],
                        "v3_requests": v3, "v3_requesters": _int(u.get("v3_requesters")),
                        "v3_share": round(v3 / (v3 + legacy), 3) if (v3 + legacy) else None,
                        "last_seen": last, "config_signals": (",".join(sorted(cfg[wid])) or None) if config is not None else None,
                        "wave": wave, "hint": hint})
    ws_rows.sort(key=lambda r: (-(r["legacy_requests"] or 0), -r["custom_legacy_endpoints"], r["workspace_id"]))

    # External model / PT endpoint names that repeat across workspaces would collide in one target schema.
    by_name = defaultdict(set)
    for e in endpoints.values():
        if e["kinds"] & CUSTOM_KINDS and DELETED not in e["kinds"]:
            by_name[e["endpoint_name"]].add(e["workspace_id"])
    collisions = [{"endpoint_name": n, "workspaces": sorted(w), "count": len(w)} for n, w in by_name.items() if len(w) > 1]
    collisions.sort(key=lambda c: -c["count"])
    return {"endpoints": rows, "workspaces": ws_rows, "collisions": collisions, "days": days,
            "history_days": history_days}


KIND_LABELS = {"external_model": "External model", "provisioned_throughput": "Provisioned throughput",
               "system_ppt": "Pay-per-token (system)", "foundation_model_other": "Other foundation model",
               "custom_model": "Custom ML", "out_of_scope": "Custom ML / feature serving",
               V2_KIND: "v2 workspace endpoint", DELETED: "Deleted (traffic only)", "unknown": "Unknown"}


def _kind_name(kind: str) -> str:
    return " + ".join(KIND_LABELS.get(k, k) for k in str(kind).split("+"))


def _days_left(iso: str, today) -> str:
    n = (datetime.strptime(iso, "%Y-%m-%d").date() - today).days
    return f"{n} days from today" if n >= 0 else f"passed {-n} days ago"


def _deadline(value: str | None) -> str:
    """The legacy serving deadline as YYYY-MM-DD (the --deadline flag, else UGMIG_DEADLINE, else 2027-03-30)."""
    d = value or LEGACY_DEADLINE
    try:
        datetime.strptime(d, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"deadline must be a date like 2027-03-30, not {d!r}")
    return d


def _pct(part: int, whole: int) -> str:
    return f"{part / whole:.0%}" if whole else "n/a"


def _v2_failing(w: dict) -> bool:
    """Most of the workspace's v2 requests failed: v2 is already off there (the planner's rule, per workspace)."""
    v2 = _int(w.get("v2_requests"))
    return v2 >= planner.V2_FAILING_MIN_REQUESTS and 100 * _int(w.get("v2_failed")) >= planner.V2_FAILING_SHARE_PERCENT * v2


def summary_md(result: dict) -> str:
    ws, eps, days = result["workspaces"], result["endpoints"], result["days"]
    history = result.get("history_days", HISTORY_DAYS)
    deadline = result.get("deadline") or LEGACY_DEADLINE
    today = datetime.now(timezone.utc).date()
    live = [e for e in eps if set(e["kind"].split("+")) - {"out_of_scope", DELETED}]
    deleted = [e for e in eps if DELETED in e["kind"].split("+")]
    running = [w for w in ws if w["wave"] != W_NOT_RUNNING]
    waves = Counter(w["wave"] for w in ws)
    v1_total = sum(w["v1_requests"] for w in ws)
    v2_total = sum(w["v2_requests"] for w in ws)
    v3_total = sum(w["v3_requests"] for w in ws)
    legacy_total = v1_total + v2_total
    customer_total = sum(w["customer_requests"] or 0 for w in ws)
    platform_total = sum(w["platform_requests"] or 0 for w in ws)
    coding_total = sum(w["coding_agent_requests"] or 0 for w in ws)
    deleted_total = sum(w["deleted_endpoint_requests"] for w in ws)
    total = v1_total + v2_total + v3_total
    no_traffic = waves.get(W_NO_TRAFFIC, 0)
    no_data = waves.get(W_NO_DATA, 0)
    custom_only = waves.get(W_CUSTOM_ONLY, 0)
    legacy_tokens_total = sum(w["legacy_tokens"] or 0 for w in ws)
    v2_failing = [w for w in ws if _v2_failing(w)]
    unknown_ws = [w for w in ws if w["unknown_traffic_endpoints"]]
    unknown_eps = sum(w["unknown_traffic_endpoints"] for w in ws)
    custom_eps = len(eps) - len(live) - len(deleted)
    blocking = [w for w in running if (w["customer_requests"] or 0) > 0]
    managed_only = [w for w in running if not w["customer_requests"] and w["platform_requests"]]
    lines = ["# Unity Gateway migration: account view (prototype, read-only)", "",
             f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}, traffic window {days} days "
             f"(last-seen check {history} days), by unity-gateway-migration-toolkit {planner.__version__}", "",
             f"> {planner.DISCLAIMER}", "",
             f"## Deadline (confirmed as of {DEADLINE_AS_OF})", "",
             f"- Legacy endpoints stop serving: **{deadline}** ({_days_left(deadline, today)}). One date for v1 and v2, "
             "pay-per-token, embeddings, provisioned throughput and external endpoints.",
             "- Custom model and feature serving endpoints are not affected. Government cloud workspaces can have different dates: ask your account team.", "",
             "## Headline", "",
             f"- Running workspaces: **{len(running)}** (no endpoint data: {no_data}; custom ML only: {custom_only})",
             f"- Workspaces with legacy endpoints or Unity Gateway traffic: **{len(running) - no_data - custom_only}**",
             f"- No legacy traffic in {days} days: **{no_traffic} of {len(running) - custom_only}** running workspaces "
             "(custom-ML-only workspaces excluded). This is not 'ready': each needs a passing workspace scan.",
             f"- Traffic unknown (no usage rows in {history} days, tracking may be off): **{_n_ep(unknown_eps)} in "
             f"{_n_ws(len(unknown_ws))}**. Unverified until a workspace scan.",
             f"- Legacy model endpoints in scope (live): **{len(live)}**; custom ML / feature serving "
             f"endpoints: **{custom_eps}** (not migrated by this toolkit); {planner._n(len(deleted), 'deleted endpoint')} "
             "with traffic, listed apart",
             f"- Requests in the last {days} days: legacy v1 **{v1_total:,}**, legacy v2 **{v2_total:,}**, Unity Gateway "
             f"**{v3_total:,}**"
             + (f" (about {v3_total / total:.0%} of model traffic on Unity Gateway; approximate, since v1 rows can "
                "include Unity Gateway backend legs)" if total else "")
             + f"; traffic to deleted endpoints (not in the live counts) **{deleted_total:,}**",
             f"- Tokens in the last {days} days (input and output, v1 and v2): **{legacy_tokens_total:,}**. Shown for "
             "sizing; the waves and the readiness checks use requests.",
             f"- **v2 failing** (v2 is already off there, so most v2 calls get errors now): **{_n_ws(len(v2_failing))}**. "
             "Marked in the workspace signals table.",
             "", "## Customer-owned vs Databricks-managed traffic", "",
             f"- Legacy requests in {days} days: **{legacy_total:,}**. Customer-owned: **{customer_total:,}** "
             f"({_pct(customer_total, legacy_total)}). Databricks-managed: **{platform_total:,}** "
             f"({_pct(platform_total, legacy_total)}): AI Gateway v2 rows with no user agent and no URL (Genie, Agent "
             "Bricks, Assistant, ai_query and similar).",
             f"- Coding agents (Claude Code, OpenCode, Codex and similar) are customer-owned: **{coding_total:,}** "
             f"({_pct(coding_total, legacy_total)}). Customers can change these callers.",
             "- v1 rows carry no user agent, so their Databricks-managed share can't be seen. All v1 requests count as "
             "customer-owned, so the Databricks-managed figure is a floor.", "",
             "## Enforce readiness (account view; a passing workspace scan is still required)", "",
             f"- **Blocking**: **{len(blocking)}** running workspaces have customer-owned legacy traffic. Move it or "
             "retire it before Enforce.",
             f"- **Warning**: **{len(managed_only)}** running workspaces have Databricks-managed traffic only. Enforce "
             "affects those Databricks services, so check them before Enforce.",
             f"- **No legacy traffic seen**: **{no_traffic}** running workspaces (wave 0). Candidates only until a "
             "passing scan.", "",
             "## Endpoints by kind", "", "| Kind | Count |", "|---|---|",
             *[f"| {_md(_kind_name(k))} | {v} |" for k, v in Counter(e["kind"] for e in eps).most_common()], "",
             "## Waves", "", "Each workspace gets one wave. The first rule that matches wins, in this order: "
             "not running, no endpoint data, high volume (legacy requests of 10,000 or more), v2 traffic, small, "
             "custom-ML only, cleanup, traffic unknown, no legacy traffic.", "",
             "| Wave | Workspaces | Meaning |", "|---|---|---|",
             *[f"| {_md(k)} | {waves.get(k, 0)} | {_md(v)} |" for k, v in WAVE_MEANING.items()], "",
             "## Workspaces (busiest first)", "",
             "| Workspace | Legacy endpoints | Of which external, PT or other | Active | v1 requests | v2 requests | "
             "Throttled | Unity Gateway requests | Share on Unity Gateway (approx.) | Wave |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for w in ws[:40]:
        share = f"about {w['v3_share']:.0%}" if w["v3_share"] is not None else "-"
        lines.append(f"| {_md(w['workspace_name'] or w['workspace_id'])} ({w['workspace_id']}) | {w['legacy_endpoints']} | "
                     f"{w['custom_legacy_endpoints']} | {w['active_legacy_endpoints']} | "
                     f"{w['v1_requests']:,} | {w['v2_requests']:,} | {w['legacy_throttled']:,} | {w['v3_requests']:,} | "
                     f"{share} | {_md(w['wave'])} |")
    if len(ws) > 40:
        lines.append(f"\n{len(ws) - 40} more in account_workspaces.csv")
    lines += ["", "## Customer-owned vs Databricks-managed by workspace", "",
              "| Workspace | Legacy requests | Customer-owned requests | Databricks-managed requests | Coding agent requests |",
              "|---|---|---|---|---|"]
    for w in [w for w in ws if w["legacy_requests"]][:40]:
        lines.append(f"| {_md(w['workspace_name'] or w['workspace_id'])} | {w['legacy_requests']:,} | "
                     f"{(w['customer_requests'] or 0):,} | {(w['platform_requests'] or 0):,} | "
                     f"{(w['coding_agent_requests'] or 0):,} |")
    lines += ["", "## Workspace signals", "",
              "| Workspace | Endpoints with unknown traffic | Last seen | Deleted-endpoint requests | v2 calls | "
              "Config signals (last year) |",
              "|---|---|---|---|---|---|"]
    for w in ws[:40]:
        signals = ", ".join(CONFIG_LABELS.get(s, s) for s in (w["config_signals"] or "").split(",") if s) or \
            ("not checked" if result.get("config_checked") is False else "none seen")
        v2_note = (f"v2 failing: {_int(w['v2_failed']):,} of {_int(w['v2_requests']):,} requests"
                   if _v2_failing(w) else "-")
        lines.append(f"| {_md(w['workspace_name'] or w['workspace_id'])} | {w['unknown_traffic_endpoints']} | "
                     f"{_md(_day(w['last_seen']) or '-')} | {w['deleted_endpoint_requests']:,} | {_md(v2_note)} | "
                     f"{_md(signals)} |")
    top = sorted((e for e in live if e["requests"]), key=lambda e: -e["requests"])[:20]
    if top:
        lines += ["", "## Busiest legacy endpoints (v1 and v2)", "",
                  "| Workspace | Endpoint | Kind | Requests | Callers | Last request | Databricks-managed requests |",
                  "|---|---|---|---|---|---|---|",
                  *[f"| {_md(e['workspace_name'] or e['workspace_id'])} | {_md(e['endpoint_name'])} | {_md(_kind_name(e['kind']))} | "
                    f"{e['requests']:,} | {e['requesters']} | {_md(e['last_request'])} | "
                    f"{(e['platform_requests'] or 0):,} |" for e in top]]
    if result["collisions"]:
        lines += ["", "## Name collisions", "",
                  "External model / PT endpoint names that exist in more than one workspace. If the workspaces share a "
                  "metastore, give each workspace its own target schema (deep scan does this with "
                  "`<schema>_<workspace_id>`).", "",
                  "| Endpoint | Workspace IDs | Workspaces |", "|---|---|---|",
                  *[f"| {_md(c['endpoint_name'])} | {_md(', '.join(c['workspaces']))} | {c['count']} |"
                    for c in result["collisions"][:20]]]
    lines += ["", "## Notes", "",
              "- Requests are distinct request IDs from your system tables. Some v1 rows can be the backend "
              "leg of Unity Gateway calls; the account tables can't tell those apart (no request ID matched "
              "ai_gateway.usage in a 7-day check), so the Unity Gateway share is approximate. Validate busy endpoints "
              "with the per-workspace deep scan.",
              "- v2 counts come from `system.ai_gateway.usage` rows with no service type. v2 endpoints have no ID or "
              "inventory row, so they are listed by name from the usage rows (kind `v2_workspace_endpoint`) and count "
              "as legacy endpoints; one with no requests in the window shows its last-seen date.",
              "- Customer-owned and Databricks-managed split: " + CUSTOMER_CLASS_NOTE + " Caller classes come from "
              "caller_class() (rules: USER_GUIDE.md, Caller types).",
              "- Wave 0 means no legacy traffic seen in the window. It is not ready until a workspace scan passes "
              "(READY or READY_WITH_WARNINGS); scan the candidates with `--wave 0`.",
              "- 'Traffic unknown' means live legacy endpoints with no usage rows in the history window. Usage tracking "
              "is per endpoint and the system tables don't show whether it's on, so this stays unverified until a scan.",
              "- Config signals come from billing product activity (last year), not configuration. They show where a "
              "scan must look; a workspace scan is the only check for ai_query, app resources and agent endpoints.",
              "- Live counts exclude endpoints deleted since, whose traffic is listed separately.",
              "- v2 failing: at least 10 v2 requests in the window and at least 95% of them failed (no status code, status "
              "0 or 501; counted per distinct request). Those callers already get errors, so move them first.",
              "- Tokens: input and output tokens from system.serving.endpoint_usage (v1) and total_tokens from "
              "system.ai_gateway.usage (v2). Shown for sizing only.",
              "- Enforce status (the workspace setting) is not in the account tables and isn't read here; the "
              "workspace scan reports it in READINESS.md."]
    if result.get("errors"):
        lines += ["", "## Query errors", "", *[f"- {_md(e)}" for e in result["errors"]],
                  "", "Waves are unknown for every workspace; no snapshot was written."]
    if result.get("warnings"):
        lines += ["", "## Warnings", "", *[f"- {_md(e)}" for e in result["warnings"]]]
    return "\n".join(lines) + "\n"


def _n_ep(n: int) -> str:
    return planner._n(n, "endpoint")


def _n_ws(n: int) -> str:
    return planner._n(n, "workspace")


def _norm(host: str | None) -> str:
    return (host or "").lower().rstrip("/").removeprefix("https://").removeprefix("http://")


def _profiles_for(url: str) -> list[str]:
    """CLI profiles in ~/.databrickscfg whose host is this workspace."""
    import configparser

    path = os.environ.get("DATABRICKS_CONFIG_FILE", os.path.expanduser("~/.databrickscfg"))
    cfg = configparser.ConfigParser()
    try:
        cfg.read(path)
    except Exception:
        return []
    names = (["DEFAULT"] if cfg.defaults().get("host") else []) + cfg.sections()
    return [n for n in names if _norm((cfg.defaults() if n == "DEFAULT" else cfg[n]).get("host")) == _norm(url)]


def connect(url: str, parent: WorkspaceClient | None = None, expect_id: str | None = None) -> WorkspaceClient:
    """Connect to a workspace: same host as the account client, a matching CLI profile, a service
    principal from the environment, or a CLI login for the host, in that order.

    With expect_id, a client that reaches a different workspace is rejected (the next method is tried).
    """
    def verified(c: WorkspaceClient) -> WorkspaceClient:
        if expect_id:
            got = planner.workspace_id_of(c)
            if str(got) != str(expect_id):
                raise RuntimeError(f"connected to workspace {got}, not {expect_id}")
        return c

    if parent is not None and _norm(parent.config.host) == _norm(url):
        return verified(parent)
    attempts = [{"profile": p} for p in _profiles_for(url)]
    attempts += [{"host": url}, {"host": url, "auth_type": "databricks-cli"}]
    errors = []
    for kwargs in attempts:
        try:
            c = WorkspaceClient(**kwargs)
            c.current_user.me()
            return verified(c)
        except Exception as e:
            errors.append(f"{kwargs}: {str(e).splitlines()[0][:120]}")
    raise RuntimeError("can't authenticate (" + "; ".join(errors) + "). Use a service principal assigned to the "
                       f"workspace (DATABRICKS_CLIENT_ID/SECRET) or run: databricks auth login --host {url}")


def deep_scan(result: dict, out_dir: str, count: int | None, ids: list[str] | None, target_catalog: str,
              target_schema: str, days: int, warehouse_id: str | None, parent: WorkspaceClient | None = None,
              wave: str | None = None) -> list[dict]:
    """Run the per-workspace planner on selected workspaces.

    Selection: explicit IDs (ids), else every workspace whose wave starts with `wave` (e.g. "0" for the
    candidates), else the N busiest with legacy traffic or custom endpoints. count caps the wave and busiest
    selections. Workspaces that can't be scanned are reported as skipped, with the reason.
    """
    by_id = {str(w["workspace_id"]): w for w in result["workspaces"]}
    out: list[dict] = []
    if ids:
        chosen = []
        for wid in ids:
            w = by_id.get(str(wid))
            if w is None:
                out.append({"workspace_id": str(wid), "status": "skipped", "error": "not in the account tables"})
                planner._log(f"Skipped workspace {wid}: not in the account tables")
            elif w.get("status") not in (None, "RUNNING") or not w.get("workspace_url"):
                reason = f"workspace status {w.get('status')}" if w.get("status") not in (None, "RUNNING") \
                    else "no workspace URL"
                out.append({"workspace_id": str(wid), "status": "skipped", "error": reason})
                planner._log(f"Skipped workspace {wid}: {reason}")
            else:
                chosen.append(w)
    else:
        candidates = [w for w in result["workspaces"] if w.get("workspace_url") and w.get("status") in (None, "RUNNING")]
        if wave is not None:
            chosen = [w for w in candidates if str(w.get("wave") or "").startswith(str(wave))]
        else:
            chosen = [w for w in candidates if w["legacy_requests"] or w["custom_legacy_endpoints"]] if count else []
        if count:
            chosen = chosen[:count]
    for w in chosen:
        url = w["workspace_url"] if w["workspace_url"].startswith("http") else f"https://{w['workspace_url']}"
        ws_out = os.path.join(out_dir, "workspaces", w["workspace_id"])
        planner._log(f"Deep scan {w['workspace_name']} ({url}), wave {w.get('wave')}")
        try:
            client = connect(url, parent, expect_id=w["workspace_id"])
            principal = client.current_user.me().user_name
            # This process's Spark session belongs to another workspace: only a warehouse in the scanned
            # workspace may run its system-table and UC queries.
            res = planner.run(client, ws_out, warehouse_id=warehouse_id, days=days, target_catalog=target_catalog,
                              target_schema=f"{target_schema}_{w['workspace_id']}", workspace_id=w["workspace_id"],
                              allow_spark=False)
            out.append({"workspace_id": w["workspace_id"], "workspace_name": w.get("workspace_name"),
                        "principal": principal, "status": "ok", **res})
        except Exception as e:
            out.append({"workspace_id": w["workspace_id"], "workspace_name": w.get("workspace_name"),
                        "status": "error", "error": str(e)[:300]})
    return out


PASSING = ("READY", "READY_WITH_WARNINGS")
CALLER_COLUMNS = ["customer_requests", "platform_requests", "coding_agent_requests"]
SNAPSHOT_COLUMNS = {
    "workspaces": ["workspace_id", "workspace_name", "status", "legacy_endpoints", "custom_legacy_endpoints",
                   "active_legacy_endpoints", "unknown_traffic_endpoints", "deleted_endpoint_requests",
                   "v1_requests", "legacy_requests", "legacy_tokens", "legacy_throttled", "v2_requests",
                   "v2_failed", "v2_tokens", "v3_requests", "v3_share", "last_seen", "config_signals", "wave"]
                  + CALLER_COLUMNS,
    "endpoints": ["workspace_id", "workspace_name", "endpoint_name", "kind", "providers", "requests",
                  "requesters", "throttled", "legacy_tokens", "last_request", "last_seen", "traffic_status"]
                 + CALLER_COLUMNS,
}
# Columns every snapshot row carries; older tables get them with ALTER TABLE ADD COLUMNS.
RUN_COLUMNS = ["run_id", "window_days", "complete"]
NUMERIC = {"legacy_endpoints", "custom_legacy_endpoints", "active_legacy_endpoints", "unknown_traffic_endpoints",
           "deleted_endpoint_requests", "legacy_requests", "v1_requests", "legacy_tokens", "legacy_throttled",
           "v2_requests", "v2_failed", "v2_tokens", "v3_requests", "requests", "requesters", "throttled",
           "window_days"} | set(CALLER_COLUMNS)


def _col_type(c: str) -> str:
    if c in NUMERIC:
        return "BIGINT"
    if c == "v3_share":
        return "DOUBLE"
    if c == "complete":
        return "BOOLEAN"
    return "STRING"


def write_snapshot(w: WorkspaceClient, warehouse_id: str | None, prefix: str, result: dict, run_id: str,
                   epoch: int) -> None:
    """Append this run to <prefix>_endpoints and <prefix>_workspaces (opt-in; the only write in this tool).

    Each run's rows are written with complete = FALSE, then marked TRUE: endpoints first, workspaces last, so a
    run counts only once every row of it is in. The app's overview reads complete runs only. Old tables get the
    new columns with ALTER TABLE ADD COLUMNS; rows from before the marker have complete NULL and count as complete.
    snapshot_time is written from the epoch seconds, so it doesn't depend on the session time zone.
    """
    if not re.fullmatch(r"[A-Za-z0-9_]+(\.[A-Za-z0-9_]+){2}", prefix or ""):
        raise ValueError("snapshot table prefix must look like catalog.schema.name (letters, digits, underscores)")
    days = int(result["days"])

    def lit(col, v):
        if v is None:
            return "NULL"
        if col in NUMERIC:
            return str(int(v))
        if col == "v3_share":
            return str(float(v))
        return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"

    order = ["endpoints", "workspaces"]  # endpoints first: the overview only reads a run once workspaces are complete
    for kind in order:
        cols = SNAPSHOT_COLUMNS[kind]
        table = f"{prefix}_{kind}"
        all_cols = cols + RUN_COLUMNS
        ddl = ", ".join(f"{c} {_col_type(c)}" for c in all_cols)
        planner._sql(w, warehouse_id, f"CREATE TABLE IF NOT EXISTS {table} (snapshot_time TIMESTAMP, {ddl}) "
                                      "COMMENT 'Unity Gateway migration snapshots (prototype)'")
        try:  # tables from older versions: add new columns
            have = {r["col_name"] for r in planner._sql(w, warehouse_id, f"DESCRIBE TABLE {table}")}
            for c in all_cols:
                if c not in have:
                    planner._sql(w, warehouse_id, f"ALTER TABLE {table} ADD COLUMNS ({c} {_col_type(c)})")
        except Exception as e:
            raise RuntimeError(f"could not check or add columns of {table}: {e}")
        rows = result[kind]
        for i in range(0, len(rows), 200):
            values = ",\n".join(
                f"(timestamp_seconds({int(epoch)}), " + ", ".join(lit(c, r.get(c)) for c in cols)
                + f", {lit('run_id', run_id)}, {days}, FALSE)"
                for r in rows[i:i + 200])
            if values:
                planner._sql(w, warehouse_id, f"INSERT INTO {table} (snapshot_time, {', '.join(cols)}, "
                                              f"run_id, window_days, complete) VALUES {values}")
        planner._sql(w, warehouse_id, f"UPDATE {table} SET complete = TRUE WHERE run_id = '{run_id}'")
        planner._log(f"  wrote {len(rows)} rows to {table} (run {run_id[:8]})")


def run(w: WorkspaceClient, warehouse_id: str | None, out_dir: str, days: int = 30, deep: int | None = None,
        deep_ids: list[str] | None = None, target_catalog: str = "ai_gateway", target_schema: str = "migrated",
        deep_warehouse_id: str | None = None, snapshot_prefix: str | None = None,
        deep_wave: str | None = None, deadline: str | None = None) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    days = int(days)
    deadline = _deadline(deadline)
    history = max(HISTORY_DAYS, days)
    run_id = str(uuid.uuid4())
    epoch = int(datetime.now(timezone.utc).timestamp())
    planner._log(f"Account inventory from system tables (run {run_id[:8]})")
    # The inventory and traffic queries abort the run: an empty result would look like "no endpoints".
    inventory = planner._sql(w, warehouse_id, INVENTORY_SQL)
    v1 = planner._sql(w, warehouse_id, V1_TRAFFIC_SQL.format(days=days, history=history))
    errors, warnings = [], []

    def optional(name: str, sql: str, required: bool = True):
        try:
            return planner._sql(w, warehouse_id, sql)
        except Exception as e:
            planner._log(f"  {name} unavailable: {e}")
            (errors if required else warnings).append(f"{name}: {str(e)[:200]}")
            return None

    ug = optional("system.ai_gateway.usage", UG_TRAFFIC_SQL.format(days=days))
    v2_eps = optional("system.ai_gateway.usage (v2 endpoints)", V2_ENDPOINT_SQL.format(days=days, history=history))
    v1_cls = optional("system.serving.endpoint_usage (callers)", V1_CLASS_SQL.format(days=days))
    v2_cls = optional("system.ai_gateway.usage (callers)", V2_CLASS_SQL.format(days=days))
    workspaces = optional("system.access.workspaces_latest", WORKSPACES_SQL)
    config = optional("system.billing.usage", CONFIG_SQL.format(history=history), required=False)
    classes = [dict(r, source="v1") for r in v1_cls or []] + [dict(r, source="v2") for r in v2_cls or []]
    planner._log(f"  {len(inventory)} served entities, {len(v1)} endpoints with usage rows, "
                 f"{len(v2_eps or [])} v2 endpoints, {len(workspaces or [])} workspaces")
    result = build(inventory, v1, ug or [], workspaces or [], days, config=config, history_days=history,
                   v2_endpoints=v2_eps or [], classes=classes)
    result["config_checked"] = config is not None
    result["errors"], result["warnings"] = errors, warnings
    result["deadline"] = deadline
    if errors:
        # A failed query would otherwise look like "no traffic": every wave is unknown instead.
        for r in result["workspaces"]:
            r["wave"], r["hint"] = W_UNKNOWN, "a query failed, so this wave is unknown (see Query errors)"
    result.update({"run_id": run_id, "snapshot_epoch": epoch, "window_days": days})
    planner._write_csv(os.path.join(out_dir, "account_workspaces.csv"), result["workspaces"])
    planner._write_csv(os.path.join(out_dir, "account_endpoints.csv"), result["endpoints"])
    planner._write_csv(os.path.join(out_dir, "account_collisions.csv"), result["collisions"])
    with open(os.path.join(out_dir, "ACCOUNT_SUMMARY.md"), "w") as f:
        f.write(summary_md(result))
    if snapshot_prefix and errors:
        # A partial snapshot would distort the trend, so nothing is written and the run fails.
        raise SystemExit("snapshot not written: some account queries failed (see ACCOUNT_SUMMARY.md): "
                         + "; ".join(errors)[:500])
    if snapshot_prefix:
        if not warehouse_id and planner._active_spark() is None:
            raise SystemExit("--snapshot-table needs --warehouse-id (or run in a notebook)")
        write_snapshot(w, warehouse_id, snapshot_prefix, result, run_id, epoch)
    scans = []
    if deep or deep_ids or deep_wave is not None:
        scans = deep_scan(result, out_dir, deep, deep_ids, target_catalog, target_schema, days, deep_warehouse_id,
                          w, wave=deep_wave)
        with open(os.path.join(out_dir, "deep_scans.json"), "w") as f:
            json.dump(scans, f, indent=1)
    planner._log(f"Done. Results in {out_dir}")
    return {"version": planner.__version__, "run_id": run_id,
            "snapshot_time": datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "deadline": deadline, "workspaces": len(result["workspaces"]), "endpoints": len(result["endpoints"]),
            "collisions": len(result["collisions"]), "errors": errors, "deep_scans": scans}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--profile", help='Databricks CLI profile (default: the CLI default)')
    p.add_argument("--warehouse-id", help="SQL warehouse for the account queries")
    p.add_argument("--out", default="./ug_account_out", help='Output folder (default ./ug_account_out)')
    p.add_argument("--days", type=int, default=30, help='Traffic window in days (default 30)')
    p.add_argument("--deadline", help=f"Legacy serving deadline YYYY-MM-DD (default {LEGACY_DEADLINE}, as of "
                                      f"{DEADLINE_AS_OF}; UGMIG_DEADLINE sets the default)")
    p.add_argument("--deep-scan", type=int, help="Deep-scan the N busiest workspaces (or N of --wave)")
    p.add_argument("--wave", help="Deep-scan the workspaces in this wave (prefix: 0 = wave 0 candidates, 1, 2, 'v2')")
    p.add_argument("--workspace", action="append", help="Deep-scan this workspace ID (repeatable)")
    p.add_argument("--deep-warehouse-id", help="Warehouse to use inside deep-scanned workspaces (without it, their traffic and Unity Catalog queries are reported as not confirmed)")
    p.add_argument("--target-catalog", default="ai_gateway", help='Catalog the plan targets for new model services (default ai_gateway)')
    p.add_argument("--target-schema", default="migrated", help='Schema the plan targets for new model services (default migrated)')
    p.add_argument("--snapshot-table", help="Append results to <catalog.schema.prefix>_workspaces/_endpoints (opt-in write)")
    a = p.parse_args(argv)
    _deadline(a.deadline)  # fails early on a malformed date
    w = WorkspaceClient(profile=a.profile) if a.profile else WorkspaceClient()
    res = run(w, a.warehouse_id, a.out, days=a.days, deep=a.deep_scan, deep_ids=a.workspace,
              target_catalog=a.target_catalog, target_schema=a.target_schema,
              deep_warehouse_id=a.deep_warehouse_id, snapshot_prefix=a.snapshot_table, deep_wave=a.wave,
              deadline=a.deadline)
    print(json.dumps(res, default=str)[:2000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
