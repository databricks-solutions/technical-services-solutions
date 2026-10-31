"""Unity Gateway migration: account-wide view (prototype; read-only unless you ask for snapshots).

Uses account-level system tables, so one query covers every workspace:
  system.serving.served_entities   legacy endpoints and what they serve
  system.serving.endpoint_usage    legacy (v1) traffic
  system.ai_gateway.usage          Unity Gateway (v3) and v2 traffic
  system.access.workspaces_latest  workspace names, URLs and status
  system.billing.usage             product activity (AI Search, Apps, Agent Bricks, AI Functions)

It ranks workspaces, proposes migration waves, flags custom endpoint names
that repeat across workspaces (they'd collide in one target schema), and can
deep-scan selected workspaces with ug_migration_planner.

    python ug_migration_account.py --profile P --warehouse-id W --out ./account_out
    python ug_migration_account.py --profile P --warehouse-id W --out ./account_out --deep-scan 3
    python ug_migration_account.py --profile P --warehouse-id W --out ./account_out --wave 0 --deep-scan 5

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
W_V2 = "v2 first"
W_HIGH = "2: high volume"
W_SMALL = "1: small"
W_CLEANUP = "1: cleanup"
W_UNKNOWN_TRAFFIC = "0: traffic unknown"
W_NO_TRAFFIC = "0: no legacy traffic"
W_NO_DATA = "no endpoint data"
W_NOT_RUNNING = "not running"
W_UNKNOWN = "unknown"

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

UG_TRAFFIC_SQL = """
-- One row per invocation in ai_gateway.usage, so count distinct request IDs.
-- v2 = rows with no service_type (undocumented NULL in the schema; verified against live rows, see NOTES_account.md).
SELECT workspace_id,
       count(DISTINCT CASE WHEN service_type = 'MODEL_SERVICE' THEN request_id END) AS v3_requests,
       count(DISTINCT CASE WHEN service_type = 'MODEL_SERVICE' THEN requester END) AS v3_requesters,
       count(DISTINCT CASE WHEN service_type IS NULL AND endpoint_name IS NOT NULL THEN request_id END) AS v2_requests,
       CAST(max(CASE WHEN service_type IS NULL AND endpoint_name IS NOT NULL THEN event_time END) AS STRING)
         AS v2_last_request
FROM system.ai_gateway.usage
WHERE event_time >= current_timestamp() - INTERVAL {days} DAYS
GROUP BY workspace_id
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
    "VECTOR_SEARCH": "AI Search (Vector Search): re-index embeddings after Unity Gateway",
    "AGENT_BRICKS": "Agent Bricks: check its vector search and endpoints",
    "SUPERVISOR_AGENT": "Agent Bricks supervisor: check its endpoints",
    "APPS": "Databricks Apps: check serving endpoint resources",
    "AI_FUNCTIONS": "AI Functions: ai_query may call legacy endpoints",
}
DELETED = "deleted_or_unknown"
# Retirement dates as of October 30, 2026. Confirm with your account team; the overview shows them as such.
V2_DATE = "2026-11-30"  # v2 endpoints stop serving
V1_DATE = "2027-03-30"  # v1 (legacy) serving retires


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


def build(inventory: list[dict], v1: list[dict], ug: list[dict], workspaces: list[dict], days: int,
          config: list[dict] | None = None, history_days: int = HISTORY_DAYS) -> dict:
    """Turn the query rows into endpoint and workspace rows with waves.

    ug and workspaces may be empty when their query failed; the caller marks waves unknown in that case.
    config is None when the billing query failed (config signals are then unknown, not absent).
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
    for key, t in traffic.items():
        if key not in endpoints:  # traffic to an endpoint deleted since; kept apart from live counts
            endpoints[key] = {"workspace_id": key[0], "endpoint_name": t["endpoint_name"] or key[1],
                              "kinds": {DELETED}, "providers": set(), "entities": 0, "created_by": None}

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
        rows.append({"workspace_id": e["workspace_id"],
                     "workspace_name": ws_meta.get(e["workspace_id"], {}).get("workspace_name"),
                     "endpoint_name": e["endpoint_name"], "kind": "+".join(sorted(kinds)),
                     "providers": ",".join(sorted(e["providers"])) or None, "served_entities": e["entities"],
                     "requests": requests, "requesters": _int(t.get("requesters")),
                     "throttled": _int(t.get("throttled")), "tokens": _int(t.get("tokens")),
                     "last_request": t.get("last_request"), "last_seen": last_seen,
                     "traffic_status": status, "created_by": e["created_by"]})
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
        for k in ("v3_requests", "v3_requesters", "v2_requests"):
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
        custom, unknown = c["custom_legacy_endpoints"], c["unknown_traffic_endpoints"]
        has_data = wid in ws or wid in ug_by
        last = ws_last.get(wid)
        extra = f"; {custom} external model / Provisioned Throughput / other endpoint(s) also present" \
            if custom and v1n else ""
        if status not in (None, "RUNNING"):
            wave, hint = W_NOT_RUNNING, f"workspace status {status}; not counted in the running total"
        elif not has_data:
            wave, hint = W_NO_DATA, ("no served endpoints, v1 traffic or AI Gateway rows in the account tables; "
                                     "only a workspace scan confirms nothing needs migrating")
        elif v2:
            wave = W_V2
            hint = (f"{v2:,} v2 requests in {days} days; v2 endpoints stop serving "
                    f"{V2_DATE} (confirm with your account team)")
        elif v1n:
            wave = W_HIGH if v1n >= TEN_K else W_SMALL
            hint = f"{v1n:,} v1 requests in {days} days from {c['active_endpoints']} endpoint(s){extra}"
        elif custom:
            wave = W_CLEANUP
            hint = (f"no v1 traffic in {days} days, but {custom} external model / Provisioned Throughput / other "
                    f"endpoint(s) ({', '.join(sorted(ws_kinds[wid]))}) block wave 0: retire or apply, then enforce")
        elif unknown:
            wave = W_UNKNOWN_TRAFFIC
            hint = (f"{unknown} live legacy endpoint(s) with no usage rows in {history_days} days; usage tracking "
                    "may be off, so traffic is unverified until a workspace scan")
        else:
            wave = W_NO_TRAFFIC
            hint = f"no v1 requests in {days} days" + (f"; last seen {_day(last)}" if last else "") + \
                ". Not ready: a passing workspace scan is required"
        legacy = v1n + v2
        ws_rows.append({"workspace_id": wid, "workspace_name": meta.get("workspace_name"),
                        "workspace_url": meta.get("workspace_url"), "status": status,
                        "legacy_endpoints": c["endpoints"], "custom_legacy_endpoints": custom,
                        "out_of_scope_endpoints": c["out_of_scope_endpoints"], "deleted_endpoints": c["deleted_endpoints"],
                        "active_legacy_endpoints": c["active_endpoints"], "unknown_traffic_endpoints": unknown,
                        "v1_requests": v1n, "v2_requests": v2, "legacy_requests": legacy,
                        "legacy_tokens": c["legacy_tokens"], "legacy_throttled": c["throttled"],
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


def summary_md(result: dict) -> str:
    ws, eps, days = result["workspaces"], result["endpoints"], result["days"]
    history = result.get("history_days", HISTORY_DAYS)
    live = [e for e in eps if set(e["kind"].split("+")) - {"out_of_scope", DELETED}]
    deleted = [e for e in eps if DELETED in e["kind"].split("+")]
    running = [w for w in ws if w["wave"] != W_NOT_RUNNING]
    waves = Counter(w["wave"] for w in ws)
    v1_total = sum(w["v1_requests"] for w in ws)
    v2_total = sum(w["v2_requests"] for w in ws)
    v3_total = sum(w["v3_requests"] for w in ws)
    deleted_total = sum(w["deleted_endpoint_requests"] for w in ws)
    total = v1_total + v2_total + v3_total
    no_traffic = waves.get(W_NO_TRAFFIC, 0)
    no_data = waves.get(W_NO_DATA, 0)
    unknown = waves.get(W_UNKNOWN_TRAFFIC, 0)
    lines = ["# Unity Gateway migration: account view (prototype, read-only)", "",
             f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}, traffic window {days} days "
             f"(last-seen check {history} days), by unity-gateway-migration-toolkit {planner.__version__}", "",
             f"> {planner.DISCLAIMER}", "",
             f"- Running workspaces: **{len(running)}** (no endpoint data in the account tables: {no_data})",
             f"- Workspaces with legacy endpoints or Unity Gateway traffic: **{len(running) - no_data}**",
             f"- No legacy traffic in {days} days: **{no_traffic} of {len(running)}** running workspaces. "
             f"This is not 'ready': each needs a passing workspace scan. Traffic unknown (no usage rows in "
             f"{history} days, tracking may be off): {unknown}",
             f"- Legacy model endpoints in scope (live): **{len(live)}** (plus {len(eps) - len(live) - len(deleted)} "
             f"custom ML / feature serving endpoints, not affected; {len(deleted)} deleted endpoints with traffic, "
             f"listed apart)",
             f"- Requests: legacy v1 **{v1_total:,}**, legacy v2 **{v2_total:,}**, Unity Gateway **{v3_total:,}**"
             + (f" ({v3_total / total:.0%} of model traffic on Unity Gateway)" if total else "")
             + f"; traffic to deleted endpoints (not in the live counts) **{deleted_total:,}**",
             "", "## Endpoints by kind", "", "| Kind | Count |", "|---|---|",
             *[f"| {_md(k)} | {v} |" for k, v in Counter(e["kind"] for e in eps).most_common()], "",
             "## Waves", "", "| Wave | Workspaces |", "|---|---|",
             *[f"| {_md(k)} | {v} |" for k, v in sorted(waves.items())], "",
             "## Workspaces (busiest first)", "",
             "| Workspace | Legacy endpoints (external/PT/other) | Active | v1 requests | v2 requests | "
             "Throttled | Unity Gateway requests | Share on Unity Gateway | Wave |",
             "|---|---|---|---|---|---|---|---|---|"]
    for w in ws[:40]:
        share = f"{w['v3_share']:.0%}" if w["v3_share"] is not None else "-"
        lines.append(f"| {_md(w['workspace_name'] or w['workspace_id'])} ({w['workspace_id']}) | {w['legacy_endpoints']} "
                     f"({w['custom_legacy_endpoints']}) | {w['active_legacy_endpoints']} | "
                     f"{w['v1_requests']:,} | {w['v2_requests']:,} | {w['legacy_throttled']:,} | {w['v3_requests']:,} | "
                     f"{share} | {_md(w['wave'])} |")
    if len(ws) > 40:
        lines.append(f"\n{len(ws) - 40} more in account_workspaces.csv")
    lines += ["", "## Workspace signals", "",
              "| Workspace | Traffic unknown (endpoints) | Last seen | Deleted-endpoint requests | Config signals (last year) |",
              "|---|---|---|---|---|"]
    for w in ws[:40]:
        signals = ", ".join(CONFIG_LABELS.get(s, s) for s in (w["config_signals"] or "").split(",") if s) or \
            ("not checked" if result.get("config_checked") is False else "none seen")
        lines.append(f"| {_md(w['workspace_name'] or w['workspace_id'])} | {w['unknown_traffic_endpoints']} | "
                     f"{_md(_day(w['last_seen']) or '-')} | {w['deleted_endpoint_requests']:,} | {_md(signals)} |")
    top = sorted((e for e in live if e["requests"]), key=lambda e: -e["requests"])[:20]
    if top:
        lines += ["", "## Busiest legacy v1 endpoints", "", "| Workspace | Endpoint | Kind | Requests | Callers | Last request |",
                  "|---|---|---|---|---|---|",
                  *[f"| {_md(e['workspace_name'] or e['workspace_id'])} | {_md(e['endpoint_name'])} | {_md(e['kind'])} | "
                    f"{e['requests']:,} | {e['requesters']} | {_md(e['last_request'])} |" for e in top]]
    if result["collisions"]:
        lines += ["", "## Name collisions", "",
                  "These external model / PT endpoint names exist in several workspaces. If the workspaces share a "
                  "metastore, give each workspace its own target schema (deep scan does this with "
                  "`<schema>_<workspace_id>`).", "",
                  "| Endpoint | Workspaces |", "|---|---|",
                  *[f"| {_md(c['endpoint_name'])} | {c['count']} |" for c in result["collisions"][:20]]]
    lines += ["", "## Notes", "",
              "- Requests are distinct request IDs from your system tables. Some v1 rows can be the backend "
              "leg of Unity Gateway calls; the account tables can't tell those apart (no request ID matched "
              "ai_gateway.usage in a 7-day check), so validate busy endpoints with the per-workspace deep scan.",
              "- v2 counts come from `system.ai_gateway.usage` rows with no service type. No inventory signal for "
              "v2 endpoints was found in the system tables, so v2 endpoints with no traffic in the window aren't seen.",
              "- Wave 0 means no legacy traffic seen in the window. It is not ready until a workspace scan passes "
              "(READY or READY_WITH_WARNINGS); scan the candidates with `--wave 0`.",
              "- 'Traffic unknown' means live legacy endpoints with no usage rows in the history window. Usage tracking "
              "is per endpoint and the system tables don't show whether it's on, so this stays unverified until a scan.",
              "- Config signals come from billing product activity (last year), not configuration. They show where a "
              "scan must look; a workspace scan is the only check for ai_query, app resources and agent endpoints.",
              "- Live counts exclude endpoints deleted since, whose traffic is listed separately."]
    if result.get("errors"):
        lines += ["", "## Query errors", "", *[f"- {_md(e)}" for e in result["errors"]],
                  "", "Waves are unknown for every workspace; no snapshot was written."]
    if result.get("warnings"):
        lines += ["", "## Warnings", "", *[f"- {_md(e)}" for e in result["warnings"]]]
    return "\n".join(lines) + "\n"


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
SNAPSHOT_COLUMNS = {
    "workspaces": ["workspace_id", "workspace_name", "status", "legacy_endpoints", "custom_legacy_endpoints",
                   "active_legacy_endpoints", "unknown_traffic_endpoints", "deleted_endpoint_requests",
                   "v1_requests", "legacy_requests", "legacy_tokens", "legacy_throttled", "v2_requests",
                   "v3_requests", "v3_share", "last_seen", "config_signals", "wave"],
    "endpoints": ["workspace_id", "workspace_name", "endpoint_name", "kind", "providers", "requests",
                  "requesters", "throttled", "tokens", "last_request", "last_seen", "traffic_status"],
}
# Columns every snapshot row carries; older tables get them with ALTER TABLE ADD COLUMNS.
RUN_COLUMNS = ["run_id", "window_days", "complete"]
NUMERIC = {"legacy_endpoints", "custom_legacy_endpoints", "active_legacy_endpoints", "unknown_traffic_endpoints",
           "deleted_endpoint_requests", "legacy_requests", "v1_requests", "legacy_tokens", "legacy_throttled",
           "v2_requests", "v3_requests", "requests", "requesters", "throttled", "tokens", "window_days"}


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
        deep_wave: str | None = None) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    days = int(days)
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
    workspaces = optional("system.access.workspaces_latest", WORKSPACES_SQL)
    config = optional("system.billing.usage", CONFIG_SQL.format(history=history), required=False)
    planner._log(f"  {len(inventory)} served entities, {len(v1)} endpoints with usage rows, "
                 f"{len(workspaces or [])} workspaces")
    result = build(inventory, v1, ug or [], workspaces or [], days, config=config, history_days=history)
    result["config_checked"] = config is not None
    result["errors"], result["warnings"] = errors, warnings
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
            "workspaces": len(result["workspaces"]), "endpoints": len(result["endpoints"]),
            "collisions": len(result["collisions"]), "errors": errors, "deep_scans": scans}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--profile", help='Databricks CLI profile (default: the CLI default)')
    p.add_argument("--warehouse-id", help="SQL warehouse for the account queries")
    p.add_argument("--out", default="./ug_account_out", help='Output folder (default ./ug_account_out)')
    p.add_argument("--days", type=int, default=30, help='Traffic window in days (default 30)')
    p.add_argument("--deep-scan", type=int, help="Deep-scan the N busiest workspaces (or N of --wave)")
    p.add_argument("--wave", help="Deep-scan the workspaces in this wave (prefix: 0 = wave 0 candidates, 1, 2, 'v2')")
    p.add_argument("--workspace", action="append", help="Deep-scan this workspace ID (repeatable)")
    p.add_argument("--deep-warehouse-id", help="Warehouse to use inside deep-scanned workspaces (without it, their traffic and Unity Catalog queries are reported as not confirmed)")
    p.add_argument("--target-catalog", default="ai_gateway", help='Catalog the plan targets for new model services (default ai_gateway)')
    p.add_argument("--target-schema", default="migrated", help='Schema the plan targets for new model services (default migrated)')
    p.add_argument("--snapshot-table", help="Append results to <catalog.schema.prefix>_workspaces/_endpoints (opt-in write)")
    a = p.parse_args(argv)
    w = WorkspaceClient(profile=a.profile) if a.profile else WorkspaceClient()
    res = run(w, a.warehouse_id, a.out, days=a.days, deep=a.deep_scan, deep_ids=a.workspace,
              target_catalog=a.target_catalog, target_schema=a.target_schema,
              deep_warehouse_id=a.deep_warehouse_id, snapshot_prefix=a.snapshot_table, deep_wave=a.wave)
    print(json.dumps(res, default=str)[:2000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
