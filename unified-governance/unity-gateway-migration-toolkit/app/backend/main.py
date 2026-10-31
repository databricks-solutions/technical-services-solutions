"""Unity Gateway Migration app: FastAPI backend.

- Reads results from Delta through a SQL warehouse as the signed-in user (user authorization,
  `sql` scope), so Unity Catalog permissions on the results schema apply.
- Starts the account snapshot, workspace scan and apply jobs as the app's service principal,
  which has CAN_MANAGE_RUN on those jobs only. Only the users listed in OPERATORS can start jobs;
  everyone else with access to the app can only view results.
- Execute and rollback requests must carry an explicit confirmation word.

Prototype from Databricks Shared Technical Services, provided as is.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import DatabricksError, NotFound, PermissionDenied
from databricks.sdk.service.sql import StatementParameterListItem, StatementState
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
RESULTS_SCHEMA = os.environ.get("RESULTS_SCHEMA", "")
SNAPSHOT_PREFIX = os.environ.get("SNAPSHOT_PREFIX", "ug_migration")
JOBS = {"snapshot": os.environ.get("SNAPSHOT_JOB_ID", ""), "scan": os.environ.get("SCAN_JOB_ID", ""),
        "apply": os.environ.get("APPLY_JOB_ID", "")}
OPERATORS = {e.strip().lower() for e in os.environ.get("OPERATORS", "").split(",") if e.strip()}
IN_APP = bool(os.environ.get("DATABRICKS_APP_NAME"))  # set by Databricks Apps; unset when running locally
NAME_RE = re.compile(r"[A-Za-z0-9_\-]+")
ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
SECRET_KEY_RE = re.compile(r"[^/\s{}]+/[^/\s{}]+")
TERMINAL = ("SUCCEEDED", "NEEDS_ATTENTION", "FAILED")

app = FastAPI(title="Unity Gateway Migration")
_sp: WorkspaceClient | None = None


def sp() -> WorkspaceClient:
    """The app's own identity (service principal in Databricks Apps; CLI profile locally)."""
    global _sp
    if _sp is None:
        _sp = WorkspaceClient()
    return _sp


def user_client(request: Request) -> WorkspaceClient:
    """The signed-in user (forwarded token); falls back to the app identity when running locally."""
    token = request.headers.get("x-forwarded-access-token")
    if token:
        return WorkspaceClient(host=sp().config.host, token=token, auth_type="pat")
    if IN_APP:
        raise HTTPException(401, "No user token: enable user authorization (sql scope) for this app")
    return sp()


def is_name(v: str) -> bool:
    return bool(v) and bool(NAME_RE.fullmatch(v))


def check_id(v: str, what: str) -> str:
    if not ID_RE.fullmatch(v or ""):
        raise HTTPException(400, f"bad {what}")
    return v


def require_operator(request: Request) -> None:
    if not IN_APP:
        return
    if who(request).lower() not in OPERATORS:
        raise HTTPException(403, "Only the app's operators can start scans, snapshots and apply runs. "
                                 "Ask the person who installed the app to add you to the operators list.")


def table(name: str) -> str:
    if not RESULTS_SCHEMA:
        raise HTTPException(500, "RESULTS_SCHEMA isn't configured")
    return ".".join(f"`{part}`" for part in (*RESULTS_SCHEMA.split("."), name))


def query(request: Request, sql: str, params: dict | None = None) -> list[dict]:
    w = user_client(request)
    resp = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID, statement=sql, wait_timeout="50s",
        parameters=[StatementParameterListItem(name=k, value=str(v)) for k, v in (params or {}).items()])
    deadline = time.time() + 120
    while resp.status.state in (StatementState.PENDING, StatementState.RUNNING) and time.time() < deadline:
        time.sleep(2)
        resp = w.statement_execution.get_statement(resp.statement_id)
    if resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
        w.statement_execution.cancel_execution(resp.statement_id)
        raise HTTPException(504, "Query timed out; the SQL warehouse may be starting, try again")
    if resp.status.state != StatementState.SUCCEEDED:
        msg = resp.status.error.message if resp.status.error else str(resp.status.state)
        if "TABLE_OR_VIEW_NOT_FOUND" in msg:
            return []
        raise HTTPException(502, f"Query failed: {msg[:400]}")
    cols = [c.name for c in resp.manifest.schema.columns]
    if resp.result is None:
        return []
    rows = [dict(zip(cols, r)) for r in (resp.result.data_array or [])]
    chunk = resp.result.next_chunk_index
    while chunk:
        part = w.statement_execution.get_statement_result_chunk_n(resp.statement_id, chunk)
        rows += [dict(zip(cols, r)) for r in (part.data_array or [])]
        chunk = part.next_chunk_index
    return rows


def run_job(kind: str, params: dict[str, str]) -> str:
    job_id = JOBS.get(kind)
    if not job_id:
        raise HTTPException(500, f"The {kind} job isn't configured")
    try:
        run = sp().jobs.run_now(job_id=int(job_id), job_parameters={k: str(v) for k, v in params.items()})
    except DatabricksError as e:
        raise HTTPException(502, f"Couldn't start the {kind} job: {str(e)[:300]}")
    return str(run.run_id)


def active_runs(kind: str) -> int:
    try:
        return sum(1 for _ in sp().jobs.list_runs(job_id=int(JOBS[kind]), active_only=True))
    except (DatabricksError, ValueError, KeyError):
        return 0


def reconcile(rows: list[dict]) -> list[dict]:
    """A job that was killed can leave its row at RUNNING; show it as FAILED once the job run has ended."""
    for r in rows:
        if r.get("status") == "FAILED" and not r.get("finished_at"):
            r["finished_at"] = "(job ended)"
        if r.get("status") == "RUNNING" and re.fullmatch(r"[0-9]{1,18}", str(r.get("job_run_id") or "")):
            try:
                st = sp().jobs.get_run(int(r["job_run_id"])).state
            except DatabricksError:
                continue
            if st and st.life_cycle_state and st.life_cycle_state.value in ("TERMINATED", "INTERNAL_ERROR", "SKIPPED"):
                r["status"] = "FAILED"
                r["finished_at"] = r.get("finished_at") or "(job ended)"
                r["error"] = r.get("error") or f"The job run ended ({st.result_state.value if st.result_state else st.life_cycle_state.value}) without recording a result."
    return rows


def who(request: Request) -> str:
    return request.headers.get("x-forwarded-email") or request.headers.get("x-forwarded-preferred-username") or "local"


# ---------------------------------------------------------------------------
# Identity and config
# ---------------------------------------------------------------------------


@app.get("/api/whoami")
def whoami(request: Request) -> dict:
    email = who(request)
    return {"email": email, "user_authorization": bool(request.headers.get("x-forwarded-access-token")),
            "operator": (not IN_APP) or email.lower() in OPERATORS, "workspace": sp().config.host}


@app.get("/api/config")
def config() -> dict:
    return {"results_schema": RESULTS_SCHEMA, "warehouse_id": WAREHOUSE_ID,
            "jobs": {k: bool(v) for k, v in JOBS.items()}}


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


@app.get("/api/jobs/{job_run_id}")
def job_status(job_run_id: str) -> dict:
    if not re.fullmatch(r"[0-9]{1,18}", job_run_id):
        raise HTTPException(400, "bad run id")
    try:
        r = sp().jobs.get_run(int(job_run_id))
    except NotFound:
        raise HTTPException(404, "job run not found")
    except PermissionDenied:
        raise HTTPException(403, "the app can't see this job run")
    except DatabricksError as e:
        raise HTTPException(502, str(e)[:300])
    if str(r.job_id) not in {v for v in JOBS.values() if v}:
        raise HTTPException(404, "job run not found")
    st = r.state
    return {"job_run_id": job_run_id, "life_cycle": st.life_cycle_state.value if st and st.life_cycle_state else None,
            "result": st.result_state.value if st and st.result_state else None,
            "message": st.state_message if st else None, "url": r.run_page_url,
            "start_time": r.start_time, "end_time": r.end_time}


# ---------------------------------------------------------------------------
# Account overview (snapshot tables)
# ---------------------------------------------------------------------------


@app.get("/api/overview")
def overview(request: Request) -> dict:
    ws_t, ep_t = table(f"{SNAPSHOT_PREFIX}_workspaces"), table(f"{SNAPSHOT_PREFIX}_endpoints")
    trend = query(request, f"""
        SELECT CAST(snapshot_time AS STRING) AS snapshot_time, sum(legacy_requests) AS legacy_requests,
               sum(v3_requests) AS v3_requests, sum(active_legacy_endpoints) AS active_legacy_endpoints,
               count_if(wave LIKE '0%') AS enforce_candidates, count(*) AS workspaces
        FROM {ws_t} GROUP BY snapshot_time ORDER BY snapshot_time""")
    if not trend:
        return {"snapshot_time": None, "trend": [], "workspaces": [], "waves": [], "endpoints": []}
    latest = trend[-1]["snapshot_time"]
    workspaces = query(request, f"""
        SELECT workspace_id, workspace_name, wave, legacy_endpoints, custom_legacy_endpoints, active_legacy_endpoints,
               v1_requests, legacy_requests, legacy_throttled, v2_requests, v3_requests, v3_share
        FROM {ws_t} WHERE snapshot_time = CAST(:t AS TIMESTAMP)
        ORDER BY legacy_requests DESC, custom_legacy_endpoints DESC""", {"t": latest})
    endpoints = query(request, f"""
        SELECT workspace_name, endpoint_name, kind, requests, requesters, throttled, last_request
        FROM {ep_t} WHERE snapshot_time = CAST(:t AS TIMESTAMP)
          AND requests > 0 AND kind <> 'out_of_scope' ORDER BY requests DESC LIMIT 100""", {"t": latest})
    waves: dict[str, int] = {}
    for w_ in workspaces:
        waves[w_["wave"]] = waves.get(w_["wave"], 0) + 1
    order = ["v2 first", "0: enforce candidate", "1: cleanup", "1: small", "2: high volume"]
    order += sorted(k for k in waves if k not in order)
    return {"snapshot_time": latest, "trend": trend, "workspaces": workspaces, "endpoints": endpoints,
            "endpoints_limit": 100, "waves": [{"wave": k, "workspaces": waves.get(k, 0)} for k in order if k in waves]}


@app.post("/api/account/snapshot")
def refresh_snapshot(request: Request) -> dict:
    require_operator(request)
    if active_runs("snapshot"):
        raise HTTPException(409, "A snapshot is already running")
    return {"job_run_id": run_job("snapshot", {"requested_by": who(request)})}


# ---------------------------------------------------------------------------
# Workspace scans
# ---------------------------------------------------------------------------


class ScanRequest(BaseModel):
    days: int = Field(30, ge=1, le=365)
    scan_roots: str = Field("", max_length=2000)
    target_catalog: str = "ai_gateway"
    target_schema: str = "migrated"


@app.get("/api/scans")
def list_scans(request: Request) -> list[dict]:
    return reconcile(query(request, f"""
        SELECT run_id, job_run_id, requested_by, workspace_url, status, readiness, endpoints, client_references,
               traffic_status, days, target_catalog, target_schema, toolkit_version, error,
               CAST(started_at AS STRING) AS started_at, CAST(finished_at AS STRING) AS finished_at
        FROM {table('ug_migration_scans')} ORDER BY started_at DESC LIMIT 50"""))


@app.post("/api/scans")
def start_scan(body: ScanRequest, request: Request) -> dict:
    require_operator(request)
    for v in (body.target_catalog, body.target_schema):
        if not is_name(v):
            raise HTTPException(400, "catalog and schema names may only contain letters, digits, _ and -")
    if active_runs("scan"):
        raise HTTPException(409, "A scan is already running; wait for it to finish")
    roots = [r.strip() for r in body.scan_roots.split(",") if r.strip()]
    for r in roots:
        if r == "/" or not re.fullmatch(r"/[^\s,'\"]*", r) or ".." in r:
            raise HTTPException(400, f"folders must be workspace paths such as /Users or /Repos/team, not {r!r}")
    run_id = str(uuid.uuid4())
    job_run_id = run_job("scan", {"run_id": run_id, "results_schema": RESULTS_SCHEMA, "days": body.days,
                                  "scan_roots": ",".join(roots), "target_catalog": body.target_catalog,
                                  "target_schema": body.target_schema, "requested_by": who(request)})
    return {"run_id": run_id, "job_run_id": job_run_id}


def _items(request: Request, run_id: str) -> dict[str, list]:
    # Code references can run into the tens of thousands, so they're paged separately (/refs), and the markdown
    # documents aren't shown in the app; both stay out of the detail payload.
    rows = query(request, f"SELECT item_type, seq, payload FROM {table('ug_migration_scan_items')} "
                          "WHERE run_id = :r AND item_type <> 'ref' AND item_type NOT LIKE 'doc:%' "
                          "ORDER BY item_type, seq", {"r": run_id})
    out: dict[str, list] = {}
    for r in rows:
        out.setdefault(r["item_type"], []).append(_load(r["payload"]))
    return out


def _load(payload: Any) -> dict:
    try:
        v = json.loads(payload or "{}")
        return v if isinstance(v, dict) else {"value": v}
    except ValueError:
        return {"unreadable_payload": str(payload)[:200]}


TEXT_FIELDS = {"line_text", "fixed_line", "match", "suggestion", "asset", "pattern", "legacy_endpoint", "reason",
               "note", "detail", "item", "name"}


def _parse_row(row: dict) -> dict:
    """Decode JSON-encoded list/dict columns from CSV payloads; free-text columns stay strings."""
    return {k: (v if k in TEXT_FIELDS else _parse(v)) for k, v in row.items()}


def _parse(v: Any):
    if isinstance(v, str) and v[:1] in "[{":
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


@app.get("/api/scans/{run_id}")
def scan_detail(run_id: str, request: Request) -> dict:
    check_id(run_id, "scan id")
    meta = query(request, f"""
        SELECT run_id, job_run_id, requested_by, workspace_url, workspace_id, status, readiness, endpoints,
               client_references, traffic_status, days, target_catalog, target_schema, scan_roots, toolkit_version,
               error, CAST(started_at AS STRING) AS started_at, CAST(finished_at AS STRING) AS finished_at
        FROM {table('ug_migration_scans')} WHERE run_id = :r""", {"r": run_id})
    if not meta:
        raise HTTPException(404, "scan not found (it may still be starting)")
    items = _items(request, run_id)
    plan = [_parse_row(p) for p in items.get("plan", [])]
    counts = query(request, f"""
        SELECT count(*) AS refs, count_if({FIX_COND}) AS fixes FROM {table('ug_migration_scan_items')}
        WHERE run_id = :r AND item_type = 'ref'""", {"r": run_id})
    callers = [_parse_row(c) for c in items.get("caller", [])]
    providers = [_parse_row(c) for c in items.get("provider", [])]
    readiness = (items.get("readiness") or [{}])[0]
    for k in ("blockers", "warnings", "rate_limit_zero_candidates"):
        readiness[k] = _parse(readiness.get(k)) if isinstance(readiness.get(k), str) else (readiness.get(k) or [])
    if not isinstance(readiness.get("coverage_gaps"), dict):
        readiness["coverage_gaps"] = {}
    c = counts[0] if counts else {}
    return {"meta": reconcile(meta)[0], "readiness": readiness, "plan": plan, "callers": callers,
            "providers": providers, "ref_counts": {"all": int(c.get("refs") or 0), "fixes": int(c.get("fixes") or 0)}}


FIX_COND = ("coalesce(get_json_object(payload, '$.fixed_line'), '') <> '' AND "
            "get_json_object(payload, '$.fixed_line') <> coalesce(get_json_object(payload, '$.line_text'), '')")


@app.get("/api/scans/{run_id}/refs")
def scan_refs(run_id: str, request: Request, kind: str = "all", q: str = Query("", max_length=200),
              offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)) -> dict:
    """One page of a scan's code references (kind=all) or proposed code fixes (kind=fixes), with a text filter."""
    check_id(run_id, "scan id")
    if kind not in ("all", "fixes"):
        raise HTTPException(400, "kind must be all or fixes")
    where = "run_id = :r AND item_type = 'ref'"
    params: dict = {"r": run_id}
    if kind == "fixes":
        where += f" AND {FIX_COND}"
    if q:
        col = "get_json_object(payload, '$.asset')" if kind == "fixes" else "payload"
        where += f" AND lower({col}) LIKE :q"
        params["q"] = "%" + q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    t = table("ug_migration_scan_items")
    total = query(request, f"SELECT count(*) AS n FROM {t} WHERE {where}", params)
    order = ("get_json_object(payload, '$.asset'), CAST(get_json_object(payload, '$.line') AS INT), seq"
             if kind == "fixes" else "seq")
    rows = query(request, f"SELECT payload FROM {t} WHERE {where} ORDER BY {order} LIMIT {limit} OFFSET {offset}", params)
    return {"total": int(total[0]["n"]) if total else 0, "offset": offset, "limit": limit,
            "rows": [_parse_row(_load(r["payload"])) for r in rows]}


# ---------------------------------------------------------------------------
# Apply, dry run and rollback
# ---------------------------------------------------------------------------


class ApplyRequest(BaseModel):
    mode: str = "dry_run"  # dry_run | execute | rollback
    scan_run_id: str = ""
    endpoints: list[str] = Field([], max_length=500)
    target_catalog: str = ""
    target_schema: str = ""
    uc_secret_map: dict[str, str] = Field({}, max_length=500)
    allow_secret_read: bool = False
    grants: bool = True
    rollback_of: str = ""
    confirm: str = ""


@app.get("/api/applies")
def list_applies(request: Request) -> list[dict]:
    return reconcile(query(request, f"""
        SELECT apply_id, job_run_id, requested_by, scan_run_id, mode, endpoints, target_catalog, target_schema,
               rollback_of, status, summary, error, CAST(started_at AS STRING) AS started_at,
               CAST(finished_at AS STRING) AS finished_at
        FROM {table('ug_migration_applies')} ORDER BY started_at DESC LIMIT 50"""))


@app.get("/api/applies/{apply_id}")
def apply_detail(apply_id: str, request: Request) -> dict:
    check_id(apply_id, "apply id")
    meta = query(request, f"""
        SELECT apply_id, job_run_id, requested_by, scan_run_id, mode, endpoints, target_catalog, target_schema,
               rollback_of, status, summary, error, CAST(started_at AS STRING) AS started_at,
               CAST(finished_at AS STRING) AS finished_at
        FROM {table('ug_migration_applies')} WHERE apply_id = :a""", {"a": apply_id})
    if not meta:
        raise HTTPException(404, "apply run not found (it may still be starting)")
    items = query(request, f"SELECT seq, payload FROM {table('ug_migration_apply_items')} "
                           "WHERE apply_id = :a ORDER BY seq", {"a": apply_id})
    rolled_back = query(request, f"""
        SELECT apply_id, status FROM {table('ug_migration_applies')}
        WHERE mode = 'rollback' AND rollback_of = :a ORDER BY started_at DESC""", {"a": apply_id})
    return {"meta": reconcile(meta)[0], "items": [_load(i["payload"]) for i in items], "rollbacks": rolled_back}


@app.post("/api/applies")
def start_apply(body: ApplyRequest, request: Request) -> dict:
    require_operator(request)
    if body.mode not in ("dry_run", "execute", "rollback"):
        raise HTTPException(400, "mode must be dry_run, execute or rollback")
    if body.mode == "execute" and body.confirm != "EXECUTE":
        raise HTTPException(400, "type EXECUTE to confirm creating objects")
    if body.mode == "rollback":
        if body.confirm != "ROLLBACK" or not body.rollback_of:
            raise HTTPException(400, "type ROLLBACK and choose the execute run to roll back")
        check_id(body.rollback_of, "rollback_of")
        src = reconcile(query(request, f"SELECT mode, status, job_run_id FROM {table('ug_migration_applies')} "
                                       "WHERE apply_id = :a", {"a": body.rollback_of}))
        if not src or src[0]["mode"] != "execute":
            raise HTTPException(400, "rollback_of must be an execute run")
        if src[0]["status"] not in TERMINAL:
            raise HTTPException(409, "that execute run hasn't finished yet")
        done = reconcile(query(request, f"SELECT status, job_run_id FROM {table('ug_migration_applies')} "
                                        "WHERE mode = 'rollback' AND rollback_of = :a "
                                        "AND status IN ('RUNNING', 'SUCCEEDED')", {"a": body.rollback_of}))
        if any(r["status"] in ("RUNNING", "SUCCEEDED") for r in done):
            raise HTTPException(409, "that execute run has already been rolled back (or a rollback is running)")
        body.endpoints, body.target_catalog, body.target_schema, body.uc_secret_map = [], "", "", {}
        body.allow_secret_read = False
    else:
        if body.scan_run_id:
            check_id(body.scan_run_id, "scan id")
        if not body.endpoints:
            raise HTTPException(400, "choose at least one endpoint")
        for v in body.endpoints:
            if not is_name(v):
                raise HTTPException(400, f"bad endpoint name {v!r}")
        for v in (body.target_catalog, body.target_schema):
            if not is_name(v):
                raise HTTPException(400, "target catalog and schema are required")
        for k, v in body.uc_secret_map.items():
            if not SECRET_KEY_RE.fullmatch(k) or not re.fullmatch(r"secrets/[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+", str(v)):
                raise HTTPException(400, f'secret map entries must look like "scope/key": "secrets/catalog.schema.name" '
                                         f"(bad entry {k!r})")
    if active_runs("apply"):
        raise HTTPException(409, "Another apply run is in progress; wait for it to finish")
    apply_id = str(uuid.uuid4())
    job_run_id = run_job("apply", {
        "apply_id": apply_id, "results_schema": RESULTS_SCHEMA, "mode": body.mode,
        "scan_run_id": body.scan_run_id, "endpoints": ",".join(body.endpoints),
        "target_catalog": body.target_catalog, "target_schema": body.target_schema,
        "uc_secret_map": json.dumps(body.uc_secret_map) if body.uc_secret_map else "",
        "allow_secret_read": str(body.allow_secret_read).lower(), "grants": str(body.grants).lower(),
        "rollback_of": body.rollback_of, "requested_by": who(request)})
    return {"apply_id": apply_id, "job_run_id": job_run_id}


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

DIST = Path(__file__).resolve().parent.parent / "frontend" / "static"
if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


# ---------------------------------------------------------------------------
# Exports (CSV / Markdown downloads of what the pages show, read as the signed-in user)
# ---------------------------------------------------------------------------

EXPORT_ROW_LIMIT = 200_000


def _cell(v: Any) -> str:
    """CSV cell: lists and dicts as JSON; values that a spreadsheet would run as a formula are prefixed."""
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        v = json.dumps(v, default=str)
    v = str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def _csv_response(rows: list[dict], filename: str, columns: list[str] | None = None) -> Response:
    cols = columns or list(dict.fromkeys(k for r in rows for k in r))
    buf = io.StringIO()
    out = csv.writer(buf)
    out.writerow(cols)
    for r in rows:
        out.writerow([_cell(r.get(c)) for c in cols])
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _stamp(t: Any) -> str:
    return re.sub(r"[^0-9]", "", str(t or ""))[:12] or "latest"


@app.get("/api/export/overview/{kind}")
def export_overview(kind: str, request: Request) -> Response:
    """Latest account snapshot: workspaces, all endpoints (not only the top 100 shown), or the trend."""
    ws_t, ep_t = table(f"{SNAPSHOT_PREFIX}_workspaces"), table(f"{SNAPSHOT_PREFIX}_endpoints")
    if kind == "trend":
        rows = query(request, f"""
            SELECT CAST(snapshot_time AS STRING) AS snapshot_time, count(*) AS workspaces,
                   count_if(wave LIKE '0%') AS enforce_candidates, sum(legacy_requests) AS legacy_requests,
                   sum(v1_requests) AS v1_requests, sum(v2_requests) AS v2_requests, sum(v3_requests) AS v3_requests,
                   sum(active_legacy_endpoints) AS active_legacy_endpoints
            FROM {ws_t} GROUP BY snapshot_time ORDER BY snapshot_time""")
        return _csv_response(rows, "ug_migration_trend.csv")
    if kind not in ("workspaces", "endpoints"):
        raise HTTPException(400, "kind must be workspaces, endpoints or trend")
    latest = query(request, f"SELECT CAST(max(snapshot_time) AS STRING) AS t FROM {ws_t}")
    t = latest[0]["t"] if latest else None
    if not t:
        raise HTTPException(404, "no snapshot yet")
    src = ws_t if kind == "workspaces" else ep_t
    rows = query(request, f"""SELECT * EXCEPT (snapshot_time), CAST(snapshot_time AS STRING) AS snapshot_time
                              FROM {src} WHERE snapshot_time = CAST(:t AS TIMESTAMP) LIMIT {EXPORT_ROW_LIMIT}""", {"t": t})
    return _csv_response(rows, f"ug_migration_{kind}_{_stamp(t)}.csv")


SCAN_EXPORTS = {"plan": "plan", "callers": "caller", "providers": "provider", "references": "ref"}
SCAN_DOCS = {"readiness": "READINESS.md", "code-fixes": "CODE_FIXES.md", "summary": "SUMMARY.md"}


@app.get("/api/scans/{run_id}/export/{kind}")
def export_scan(run_id: str, kind: str, request: Request) -> Response:
    """One scan's plan, callers, provider services or references as CSV, or its reports as Markdown."""
    check_id(run_id, "scan id")
    short = run_id[:8]
    if kind in SCAN_DOCS:
        rows = query(request, f"SELECT payload FROM {table('ug_migration_scan_items')} "
                              "WHERE run_id = :r AND item_type = :t", {"r": run_id, "t": "doc:" + SCAN_DOCS[kind]})
        if not rows:
            raise HTTPException(404, "this scan has no such report")
        text = _load(rows[0]["payload"]).get("markdown", "")
        name = SCAN_DOCS[kind].replace(".md", f"_{short}.md")
        return Response(text, media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})
    if kind not in SCAN_EXPORTS:
        raise HTTPException(400, f"kind must be one of {', '.join([*SCAN_EXPORTS, *SCAN_DOCS])}")
    rows = query(request, f"SELECT payload FROM {table('ug_migration_scan_items')} WHERE run_id = :r AND item_type = :t "
                          f"ORDER BY seq LIMIT {EXPORT_ROW_LIMIT}", {"r": run_id, "t": SCAN_EXPORTS[kind]})
    return _csv_response([_load(r["payload"]) for r in rows], f"ug_migration_{kind}_{short}.csv")


@app.get("/api/applies/{apply_id}/export")
def export_apply(apply_id: str, request: Request) -> Response:
    check_id(apply_id, "apply id")
    rows = query(request, f"SELECT payload FROM {table('ug_migration_apply_items')} WHERE apply_id = :a "
                          f"ORDER BY seq LIMIT {EXPORT_ROW_LIMIT}", {"a": apply_id})
    items = [_load(r["payload"]) for r in rows]
    return _csv_response(items, f"ug_migration_apply_{apply_id[:8]}.csv",
                         ["type", "name", "action", "reason", "issues", "grants", "time", "execute"]
                         + sorted({k for i in items for k in i} - {"type", "name", "action", "reason", "issues",
                                                                     "grants", "time", "execute", "body"}))


@app.get("/{path:path}")
def spa(path: str):
    if path == "api" or path.startswith("api/"):
        raise HTTPException(404, "not found")
    index = DIST / "index.html"
    if not index.exists():
        raise HTTPException(404, "frontend not built")
    return FileResponse(index)
