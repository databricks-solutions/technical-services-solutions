"""Unity Gateway migration: account-wide view (prototype; read-only unless you ask for snapshots).

Uses account-level system tables, so one query covers every workspace:
  system.serving.served_entities   legacy endpoints and what they serve
  system.serving.endpoint_usage    legacy (v1) traffic
  system.ai_gateway.usage          Unity Gateway (v3) and v2 traffic
  system.access.workspaces_latest  workspace names and URLs

It ranks workspaces, proposes migration waves, flags custom endpoint names
that repeat across workspaces (they'd collide in one target schema), and can
deep-scan selected workspaces with ug_migration_planner.

    python ug_migration_account.py --profile P --warehouse-id W --out ./account_out
    python ug_migration_account.py --profile P --warehouse-id W --out ./account_out --deep-scan 3

Deep scans connect to each workspace URL with the default auth chain (a
service principal in DATABRICKS_CLIENT_ID / DATABRICKS_CLIENT_SECRET that is
assigned to the workspaces, or a CLI login for each host).

Needs read access to the system tables (account admin by default). Written by
STS as a prototype; not an official Databricks tool.
"""

from __future__ import annotations

import argparse
import json
import re
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

from databricks.sdk import WorkspaceClient

import ug_migration_planner as planner

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

V1_TRAFFIC_SQL = """
SELECT eu.workspace_id, se.endpoint_id, max(se.endpoint_name) AS endpoint_name,
       count(DISTINCT eu.databricks_request_id) AS requests,
       count(DISTINCT eu.requester) AS requesters,
       CAST(max(eu.request_time) AS STRING) AS last_request,
       count(DISTINCT CASE WHEN eu.status_code = 429 THEN eu.databricks_request_id END) AS throttled,
       sum(coalesce(eu.input_token_count, 0) + coalesce(eu.output_token_count, 0)) AS tokens
FROM system.serving.endpoint_usage AS eu
JOIN (SELECT DISTINCT served_entity_id, endpoint_id, endpoint_name FROM system.serving.served_entities) AS se
  ON eu.served_entity_id = se.served_entity_id
WHERE eu.request_time >= current_timestamp() - INTERVAL {days} DAYS
GROUP BY eu.workspace_id, se.endpoint_id
"""

UG_TRAFFIC_SQL = """
-- One row per invocation in ai_gateway.usage, so count distinct request IDs.
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


def build(inventory: list[dict], v1: list[dict], ug: list[dict], workspaces: list[dict], days: int) -> dict:
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
                                     "throttled": 0, "tokens": 0, "last_request": None})
        for k in ("requests", "requesters", "throttled", "tokens"):
            t[k] += _int(r.get(k))
        if r.get("last_request") and (not t["last_request"] or str(r["last_request"]) > str(t["last_request"])):
            t["last_request"] = r["last_request"]
    for key, t in traffic.items():
        if key not in endpoints:  # traffic to an endpoint deleted since; still worth knowing
            endpoints[key] = {"workspace_id": key[0], "endpoint_name": t["endpoint_name"] or key[1],
                              "kinds": {"deleted_or_unknown"}, "providers": set(), "entities": 0, "created_by": None}

    ws: dict[str, Counter] = defaultdict(Counter)
    rows = []
    for key, e in endpoints.items():
        t = traffic.get(key, {})
        kinds = e["kinds"]
        kind = "+".join(sorted(kinds))
        in_scope = bool(kinds - {"out_of_scope"})
        row = {"workspace_id": e["workspace_id"],
               "workspace_name": ws_meta.get(e["workspace_id"], {}).get("workspace_name"),
               "endpoint_name": e["endpoint_name"], "kind": kind,
               "providers": ",".join(sorted(e["providers"])) or None, "served_entities": e["entities"],
               "requests": _int(t.get("requests")), "requesters": _int(t.get("requesters")),
               "throttled": _int(t.get("throttled")), "tokens": _int(t.get("tokens")),
               "last_request": t.get("last_request"), "created_by": e["created_by"]}
        rows.append(row)
        c = ws[e["workspace_id"]]
        if in_scope:
            c["endpoints"] += 1
        else:
            c["out_of_scope_endpoints"] += 1
        if row["requests"] and in_scope:
            c["v1_requests"] += row["requests"]
            c["legacy_tokens"] += row["tokens"]
            c["active_endpoints"] += 1
            c["throttled"] += row["throttled"]
        if kinds & CUSTOM_KINDS:
            c["custom_legacy_endpoints"] += 1

    ug_by: dict[str, dict] = {}
    for r in ug:
        u = ug_by.setdefault(str(r["workspace_id"]), Counter())
        for k in ("v3_requests", "v3_requesters", "v2_requests"):
            u[k] += _int(r.get(k))
    all_ws = set(ws) | set(ug_by)
    ws_rows = []
    for wid in all_ws:
        c = ws.get(wid, Counter())
        u = ug_by.get(wid, {})
        meta = ws_meta.get(wid, {})
        v1n, v2, v3 = c["v1_requests"], _int(u.get("v2_requests")), _int(u.get("v3_requests"))
        legacy = v1n + v2
        if v2:
            wave, hint = "v2 first", "v2 traffic: v2 endpoints stop serving first (November 30, 2026 per Databricks, as of October 30, 2026; confirm with your account team)"
        elif not v1n and not c["custom_legacy_endpoints"]:
            wave, hint = "0: enforce candidate", ("no legacy traffic and no external model/PT endpoints: "
                                                  "run the readiness check, then enforce")
        elif not v1n:
            wave, hint = "1: cleanup", "external model/PT endpoints but no traffic: retire or apply, then enforce"
        elif legacy < 10_000:
            wave, hint = "1: small", "low legacy traffic"
        else:
            wave, hint = "2: high volume", "high legacy traffic"
        ws_rows.append({"workspace_id": wid, "workspace_name": meta.get("workspace_name"),
                        "workspace_url": meta.get("workspace_url"), "status": meta.get("status"),
                        "legacy_endpoints": c["endpoints"], "custom_legacy_endpoints": c["custom_legacy_endpoints"],
                        "out_of_scope_endpoints": c["out_of_scope_endpoints"],
                        "active_legacy_endpoints": c["active_endpoints"], "v1_requests": v1n,
                        "legacy_requests": legacy, "legacy_tokens": c["legacy_tokens"],
                        "legacy_throttled": c["throttled"], "v2_requests": v2, "v3_requests": v3,
                        "v3_requesters": _int(u.get("v3_requesters")),
                        "v3_share": round(v3 / (v3 + legacy), 3) if (v3 + legacy) else None,
                        "wave": wave, "hint": hint})
    ws_rows.sort(key=lambda r: (-r["legacy_requests"], -r["custom_legacy_endpoints"], r["workspace_id"]))

    # External model / PT endpoint names that repeat across workspaces would collide in one target schema.
    by_name = defaultdict(set)
    for e in endpoints.values():
        if e["kinds"] & CUSTOM_KINDS:
            by_name[e["endpoint_name"]].add(e["workspace_id"])
    collisions = [{"endpoint_name": n, "workspaces": sorted(w), "count": len(w)} for n, w in by_name.items() if len(w) > 1]
    collisions.sort(key=lambda c: -c["count"])
    return {"endpoints": rows, "workspaces": ws_rows, "collisions": collisions, "days": days}


def summary_md(result: dict) -> str:
    ws, eps, days = result["workspaces"], result["endpoints"], result["days"]
    in_scope = [e for e in eps if set(e["kind"].split("+")) - {"out_of_scope"}]
    kinds = Counter(e["kind"] for e in eps)
    waves = Counter(w["wave"] for w in ws)
    v1_total = sum(w["v1_requests"] for w in ws)
    v2_total = sum(w["v2_requests"] for w in ws)
    v3_total = sum(w["v3_requests"] for w in ws)
    total = v1_total + v2_total + v3_total
    lines = ["# Unity Gateway migration: account view (prototype, read-only)", "",
             f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}, traffic window {days} days, "
             f"by ug-migration-toolkit {planner.__version__}", "", f"> {planner.DISCLAIMER}", "",
             f"- Workspaces with legacy endpoints or Unity Gateway traffic: **{len(ws)}**",
             f"- Legacy model endpoints in scope (live): **{len(in_scope)}** "
             f"(plus {len(eps) - len(in_scope)} custom ML / feature serving endpoints, not affected)",
             f"- Requests: legacy v1 **{v1_total:,}**, legacy v2 **{v2_total:,}**, Unity Gateway **{v3_total:,}**"
             + (f" ({v3_total / total:.0%} of model traffic on Unity Gateway)" if total else ""),
             "", "## Endpoints by kind", "", "| Kind | Count |", "|---|---|",
             *[f"| {_md(k)} | {v} |" for k, v in kinds.most_common()], "",
             "## Waves", "", "| Wave | Workspaces |", "|---|---|",
             *[f"| {_md(k)} | {v} |" for k, v in sorted(waves.items())], "",
             "## Workspaces (busiest first)", "",
             "| Workspace | Legacy endpoints (external/PT) | Active | v1 requests | v2 requests | Throttled | "
             "Unity Gateway requests | Share on UG | Wave |",
             "|---|---|---|---|---|---|---|---|---|"]
    for w in ws[:40]:
        share = f"{w['v3_share']:.0%}" if w["v3_share"] is not None else "-"
        lines.append(f"| {_md(w['workspace_name'] or w['workspace_id'])} ({w['workspace_id']}) | {w['legacy_endpoints']} "
                     f"({w['custom_legacy_endpoints']}) | {w['active_legacy_endpoints']} | {w['v1_requests']:,} | "
                     f"{w['v2_requests']:,} | {w['legacy_throttled']:,} | {w['v3_requests']:,} | {share} | {_md(w['wave'])} |")
    if len(ws) > 40:
        lines.append(f"\n{len(ws) - 40} more in account_workspaces.csv")
    top = sorted((e for e in in_scope if e["requests"]), key=lambda e: -e["requests"])[:20]
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
              "leg of Unity Gateway calls; validate busy endpoints with the per-workspace deep scan.",
              "- v2 counts come from `system.ai_gateway.usage` rows without a Unity Gateway service type.",
              "- Wave 0 workspaces still need the per-workspace readiness check (AI Search, apps, code) before "
              "enforcing."]
    if result.get("errors"):
        lines += ["", "## Query errors", "", *[f"- {_md(e)}" for e in result["errors"]],
                  "", "Results above are incomplete; no snapshot was written."]
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


def connect(url: str, parent: WorkspaceClient | None = None) -> WorkspaceClient:
    """Connect to a workspace: same host as the account client, a matching CLI profile, a service
    principal from the environment, or a CLI login for the host, in that order."""
    if parent is not None and _norm(parent.config.host) == _norm(url):
        return parent
    attempts = [{"profile": p} for p in _profiles_for(url)]
    attempts += [{"host": url}, {"host": url, "auth_type": "databricks-cli"}]
    errors = []
    for kwargs in attempts:
        try:
            c = WorkspaceClient(**kwargs)
            c.current_user.me()
            return c
        except Exception as e:
            errors.append(f"{kwargs}: {str(e).splitlines()[0][:120]}")
    raise RuntimeError("can't authenticate (" + "; ".join(errors) + "). Use a service principal assigned to the "
                       f"workspace (DATABRICKS_CLIENT_ID/SECRET) or run: databricks auth login --host {url}")


def deep_scan(result: dict, out_dir: str, count: int | None, ids: list[str] | None, target_catalog: str,
              target_schema: str, days: int, warehouse_id: str | None,
              parent: WorkspaceClient | None = None) -> list[dict]:
    """Run the per-workspace planner on selected workspaces."""
    candidates = [w for w in result["workspaces"] if w.get("workspace_url") and w.get("status") in (None, "RUNNING")]
    chosen = [w for w in candidates if w["workspace_id"] in ids] if ids else \
        [w for w in candidates if w["legacy_requests"] or w["custom_legacy_endpoints"]][:count or 0]
    out = []
    for w in chosen:
        url = w["workspace_url"] if w["workspace_url"].startswith("http") else f"https://{w['workspace_url']}"
        ws_out = os.path.join(out_dir, "workspaces", w["workspace_id"])
        planner._log(f"Deep scan {w['workspace_name']} ({url})")
        try:
            client = connect(url, parent)
            # This process's Spark session belongs to another workspace: only a warehouse in the scanned
            # workspace may run its system-table and UC queries.
            res = planner.run(client, ws_out, warehouse_id=warehouse_id, days=days, target_catalog=target_catalog,
                              target_schema=f"{target_schema}_{w['workspace_id']}", workspace_id=w["workspace_id"],
                              allow_spark=False)
            out.append({"workspace_id": w["workspace_id"], "status": "ok", **res})
        except Exception as e:
            out.append({"workspace_id": w["workspace_id"], "status": "error", "error": str(e)[:300]})
    return out


SNAPSHOT_COLUMNS = {
    "workspaces": ["workspace_id", "workspace_name", "legacy_endpoints", "custom_legacy_endpoints",
                   "active_legacy_endpoints", "v1_requests", "legacy_requests", "legacy_tokens", "legacy_throttled",
                   "v2_requests", "v3_requests", "v3_share", "wave"],
    "endpoints": ["workspace_id", "workspace_name", "endpoint_name", "kind", "providers", "requests",
                  "requesters", "throttled", "tokens", "last_request"],
}
NUMERIC = {"legacy_endpoints", "custom_legacy_endpoints", "active_legacy_endpoints", "legacy_requests", "v1_requests",
           "legacy_tokens", "legacy_throttled", "v2_requests", "v3_requests", "requests", "requesters",
           "throttled", "tokens"}


def write_snapshot(w: WorkspaceClient, warehouse_id: str | None, prefix: str, result: dict, snapshot_time: str) -> None:
    """Append this run to <prefix>_workspaces and <prefix>_endpoints (opt-in; the only write in this tool).

    One row per workspace / endpoint per run, so progress can be charted over time.
    """
    if not re.fullmatch(r"[A-Za-z0-9_]+(\.[A-Za-z0-9_]+){2}", prefix or ""):
        raise ValueError("snapshot table prefix must look like catalog.schema.name (letters, digits, underscores)")

    def lit(col, v):
        if v is None:
            return "NULL"
        if col in NUMERIC:
            return str(int(v))
        if col == "v3_share":
            return str(float(v))
        return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"

    for kind, cols in SNAPSHOT_COLUMNS.items():
        table = f"{prefix}_{kind}"
        ddl = ", ".join(f"{c} {'BIGINT' if c in NUMERIC else 'DOUBLE' if c == 'v3_share' else 'STRING'}" for c in cols)
        planner._sql(w, warehouse_id, f"CREATE TABLE IF NOT EXISTS {table} (snapshot_time TIMESTAMP, {ddl}) "
                                      "COMMENT 'Unity Gateway migration snapshots (prototype)'")
        try:  # tables from older versions: add new columns
            have = {r["col_name"] for r in planner._sql(w, warehouse_id, f"DESCRIBE TABLE {table}")}
            for c in cols:
                if c not in have:
                    typ = "BIGINT" if c in NUMERIC else "DOUBLE" if c == "v3_share" else "STRING"
                    planner._sql(w, warehouse_id, f"ALTER TABLE {table} ADD COLUMNS ({c} {typ})")
        except Exception as e:
            planner._log(f"  could not check columns of {table}: {e}")
        rows = result[kind]
        for i in range(0, len(rows), 200):
            values = ",\n".join("(TIMESTAMP '" + snapshot_time + "', " + ", ".join(lit(c, r.get(c)) for c in cols) + ")"
                                for r in rows[i:i + 200])
            if values:
                planner._sql(w, warehouse_id, f"INSERT INTO {table} (snapshot_time, {', '.join(cols)}) VALUES {values}")
        planner._log(f"  wrote {len(rows)} rows to {table}")


def run(w: WorkspaceClient, warehouse_id: str | None, out_dir: str, days: int = 30, deep: int | None = None,
        deep_ids: list[str] | None = None, target_catalog: str = "ai_gateway", target_schema: str = "migrated",
        deep_warehouse_id: str | None = None, snapshot_prefix: str | None = None) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    planner._log("Account inventory from system tables")
    inventory = planner._sql(w, warehouse_id, INVENTORY_SQL)
    v1 = planner._sql(w, warehouse_id, V1_TRAFFIC_SQL.format(days=int(days)))
    errors = []
    try:
        ug = planner._sql(w, warehouse_id, UG_TRAFFIC_SQL.format(days=int(days)))
    except Exception as e:
        planner._log(f"  system.ai_gateway.usage unavailable: {e}")
        errors.append(f"system.ai_gateway.usage: {str(e)[:200]}")
        ug = []
    try:
        workspaces = planner._sql(w, warehouse_id, WORKSPACES_SQL)
    except Exception as e:
        planner._log(f"  system.access.workspaces_latest unavailable: {e}")
        errors.append(f"system.access.workspaces_latest: {str(e)[:200]}")
        workspaces = []
    planner._log(f"  {len(inventory)} served entities, {len(v1)} endpoints with traffic, {len(workspaces)} workspaces")
    result = build(inventory, v1, ug, workspaces, days)
    result["errors"] = errors
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
        write_snapshot(w, warehouse_id, snapshot_prefix, result,
                       datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
    scans = []
    if deep or deep_ids:
        scans = deep_scan(result, out_dir, deep, deep_ids, target_catalog, target_schema, days, deep_warehouse_id, w)
        with open(os.path.join(out_dir, "deep_scans.json"), "w") as f:
            json.dump(scans, f, indent=1)
    planner._log(f"Done. Results in {out_dir}")
    return {"version": planner.__version__, "workspaces": len(result["workspaces"]), "endpoints": len(result["endpoints"]),
            "collisions": len(result["collisions"]), "deep_scans": scans}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--profile", help='Databricks CLI profile (default: the CLI default)')
    p.add_argument("--warehouse-id", help="SQL warehouse for the account queries")
    p.add_argument("--out", default="./ug_account_out", help='Output folder (default ./ug_account_out)')
    p.add_argument("--days", type=int, default=30, help='Traffic window in days (default 30)')
    p.add_argument("--deep-scan", type=int, help="Deep-scan the N busiest workspaces")
    p.add_argument("--workspace", action="append", help="Deep-scan this workspace ID (repeatable)")
    p.add_argument("--deep-warehouse-id", help="Warehouse to use inside deep-scanned workspaces (without it, their traffic and Unity Catalog queries are reported as not confirmed)")
    p.add_argument("--target-catalog", default="ai_gateway", help='Catalog the plan targets for new model services (default ai_gateway)')
    p.add_argument("--target-schema", default="migrated", help='Schema the plan targets for new model services (default migrated)')
    p.add_argument("--snapshot-table", help="Append results to <catalog.schema.prefix>_workspaces/_endpoints (opt-in write)")
    a = p.parse_args(argv)
    w = WorkspaceClient(profile=a.profile) if a.profile else WorkspaceClient()
    res = run(w, a.warehouse_id, a.out, a.days, a.deep_scan, a.workspace, a.target_catalog, a.target_schema,
              a.deep_warehouse_id, a.snapshot_table)
    print(json.dumps(res, default=str)[:2000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
