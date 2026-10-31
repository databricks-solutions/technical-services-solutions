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
import hashlib
import io
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import DatabricksError, NotFound, PermissionDenied
from databricks.sdk.service.sql import StatementParameterListItem, StatementState
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
RESULTS_SCHEMA = os.environ.get("RESULTS_SCHEMA", "")
SNAPSHOT_PREFIX = os.environ.get("SNAPSHOT_PREFIX", "ug_migration")
JOBS = {"snapshot": os.environ.get("SNAPSHOT_JOB_ID", ""), "scan": os.environ.get("SCAN_JOB_ID", ""),
        "apply": os.environ.get("APPLY_JOB_ID", "")}
OPERATORS = {e.strip().lower() for e in os.environ.get("OPERATORS", "").split(",") if e.strip()}
IN_APP = bool(os.environ.get("DATABRICKS_APP_NAME"))  # set by Databricks Apps; unset when running locally
# Local development only: UGMIG_LOCAL_DEV=1 runs as the CLI profile's user with no operator check. Ignored inside
# Databricks Apps. Without it, every request needs a verified user from the forwarded token, and operators are required.
LOCAL_DEV = os.environ.get("UGMIG_LOCAL_DEV") == "1" and not IN_APP
# Unity Catalog schemas (catalog.schema) that apply may reference for secrets; set by the installer, not by requests.
SECRET_SCHEMAS = {s.strip().lower() for s in os.environ.get("UGMIG_SECRET_SCHEMAS", "").split(",") if s.strip()}
ALLOW_SECRET_READ = os.environ.get("UGMIG_ALLOW_SECRET_READ", "").strip().lower() in ("1", "true", "yes")
MAX_SCAN_AGE_DAYS = int(os.environ.get("UGMIG_MAX_SCAN_AGE_DAYS") or 14)
EXPORT_ROW_LIMIT = 200_000
IDENTITY_TTL_S = 300
NAME_RE = re.compile(r"[A-Za-z0-9_\-]+")
ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
SECRET_KEY_RE = re.compile(r"[^/\s{}]+/[^/\s{}]+")
SECRET_REF_RE = re.compile(r"secrets/([A-Za-z0-9_\-]+)\.([A-Za-z0-9_\-]+)\.([A-Za-z0-9_\-]+)")
TERMINAL = ("SUCCEEDED", "NEEDS_ATTENTION", "FAILED")
# Options that decide what an apply run does; an execute must match the dry run it follows on all of them.
FINGERPRINT_KEYS = ("scan_run_id", "endpoints", "target_catalog", "target_schema", "uc_secret_map",
                    "allow_secret_read", "grants", "ack_guardrails")

app = FastAPI(title="Unity Gateway Migration")
_sp: WorkspaceClient | None = None
_identities: dict[str, tuple[float, str]] = {}  # sha256(token) -> (expires at, user name)
_owners: dict[str, str] = {}  # job run id -> who started it, for runs this process started


@app.middleware("http")
async def csrf_guard(request: Request, call_next):
    """Cross-site form posts can't send JSON, and browsers mark cross-site requests, so POSTs must be JSON and not cross-site."""
    if request.method == "POST":
        if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
            return JSONResponse({"detail": "Requests from other sites are blocked"}, status_code=403)
        if not request.headers.get("content-type", "").lower().startswith("application/json"):
            return JSONResponse({"detail": "Send POST requests as application/json"}, status_code=415)
    return await call_next(request)


def sp() -> WorkspaceClient:
    """The app's own identity (service principal in Databricks Apps; CLI profile locally)."""
    global _sp
    if _sp is None:
        _sp = WorkspaceClient()
    return _sp


def user_client(request: Request) -> WorkspaceClient:
    """The signed-in user (forwarded token). Without a token only local development falls back to the CLI profile."""
    token = request.headers.get("x-forwarded-access-token")
    if token:
        return WorkspaceClient(host=sp().config.host, token=token, auth_type="pat")
    if LOCAL_DEV:
        return sp()
    raise HTTPException(401, "No user token: enable user authorization (sql scope) for this app")


def _token_identity(token: str) -> str:
    """The user a forwarded token belongs to, asked of Databricks (current-user) and cached per token for a few minutes."""
    key = hashlib.sha256(token.encode()).hexdigest()
    hit = _identities.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    try:
        name = (WorkspaceClient(host=sp().config.host, token=token, auth_type="pat").current_user.me().user_name or "")
    except Exception:  # fail closed: any failure means the caller isn't verified
        raise HTTPException(401, "Couldn't verify your identity from your session; reload the page")
    name = name.strip().lower()
    if not name:
        raise HTTPException(401, "Couldn't verify your identity from your session; reload the page")
    if len(_identities) > 1000:
        _identities.clear()
    _identities[key] = (time.time() + IDENTITY_TTL_S, name)
    return name


def verified_user(request: Request) -> str | None:
    """The signed-in user, verified from the forwarded user token; None when there is no token (user authorization
    is off) and this isn't local development. The email header is only compared with the token, never trusted alone."""
    token = request.headers.get("x-forwarded-access-token")
    if token:
        name = _token_identity(token)
        claimed = (request.headers.get("x-forwarded-email") or "").strip().lower()
        if claimed and claimed != name:
            raise HTTPException(403, "Your request doesn't match your session; reload the page")
        return name
    if LOCAL_DEV:
        return (request.headers.get("x-forwarded-email") or "local").strip().lower()
    return None


def is_name(v: str) -> bool:
    return bool(v) and bool(NAME_RE.fullmatch(v))


def check_id(v: str, what: str) -> str:
    if not ID_RE.fullmatch(v or ""):
        raise HTTPException(400, f"bad {what}")
    return v


def require_operator(request: Request) -> None:
    if LOCAL_DEV:
        return
    if who(request) not in OPERATORS:
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
    if params.get("requested_by"):
        if len(_owners) > 5000:
            _owners.clear()
        _owners[str(run.run_id)] = str(params["requested_by"]).lower()
    return str(run.run_id)


def active_runs(kind: str) -> int:
    """Number of active runs of a job. If Databricks can't say, refuse to start another run (fail closed)."""
    job_id = JOBS.get(kind)
    if not job_id:
        raise HTTPException(500, f"The {kind} job isn't configured")
    try:
        return sum(1 for _ in sp().jobs.list_runs(job_id=int(job_id), active_only=True))
    except Exception:
        raise HTTPException(503, f"Couldn't check whether a {kind} run is already active, so nothing was started. "
                                 "Try again in a minute.")


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
    """The verified signed-in user (lower case). Raises 401 when the request has no verified user."""
    user = verified_user(request)
    if not user:
        raise HTTPException(401, "No signed-in user: enable user authorization (sql scope) for this app")
    return user


# ---------------------------------------------------------------------------
# Identity and config
# ---------------------------------------------------------------------------


@app.get("/api/whoami")
def whoami(request: Request) -> dict:
    user = verified_user(request)
    return {"email": user or "", "user_authorization": bool(request.headers.get("x-forwarded-access-token")),
            "operator": bool(LOCAL_DEV or (user is not None and user in OPERATORS)), "workspace": sp().config.host}


@app.get("/api/config")
def config() -> dict:
    return {"results_schema": RESULTS_SCHEMA, "warehouse_id": WAREHOUSE_ID,
            "jobs": {k: bool(v) for k, v in JOBS.items()},
            "secret_schemas": sorted(SECRET_SCHEMAS), "allow_secret_read": ALLOW_SECRET_READ,
            "max_scan_age_days": MAX_SCAN_AGE_DAYS, "export_row_limit": EXPORT_ROW_LIMIT}


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


def _may_see_run(request: Request, job_run_id: str) -> bool:
    """Operators see every run's message and link; anyone else only for runs they started."""
    user = verified_user(request)
    if user is None:
        return False
    if LOCAL_DEV or user in OPERATORS or _owners.get(job_run_id) == user:
        return True
    try:
        rows = query(request, f"SELECT requested_by FROM {table('ug_migration_scans')} WHERE job_run_id = :j "
                              f"UNION ALL SELECT requested_by FROM {table('ug_migration_applies')} WHERE job_run_id = :j",
                     {"j": job_run_id})
    except Exception:  # fail closed
        return False
    return any(str(r.get("requested_by") or "").lower() == user for r in rows)


@app.get("/api/jobs/{job_run_id}")
def job_status(job_run_id: str, request: Request) -> dict:
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
    out = {"job_run_id": job_run_id, "life_cycle": st.life_cycle_state.value if st and st.life_cycle_state else None,
           "result": st.result_state.value if st and st.result_state else None,
           "start_time": r.start_time, "end_time": r.end_time}
    if _may_see_run(request, job_run_id):  # messages can name tables and paths, so they stay with owners and operators
        out.update(message=st.state_message if st else None, url=r.run_page_url)
    return out


# ---------------------------------------------------------------------------
# Account overview (snapshot tables)
# ---------------------------------------------------------------------------


# Retirement dates as of October 30, 2026. Confirm with your account team: the overview says so next to them.
OVERVIEW_V2_STOP = "2026-11-30"  # v2 endpoints stop serving
OVERVIEW_V1_STOP = "2027-03-30"  # v1 (legacy) serving retires
OVERVIEW_PASSING_SCANS = ("READY", "READY_WITH_WARNINGS")
OVERVIEW_WAVE_ORDER = ["v2 first", "2: high volume", "1: small", "1: cleanup", "0: traffic unknown",
                       "0: no legacy traffic", "no endpoint data", "not running", "unknown"]


def _num(v):
    """Snapshot numbers come back as strings (or None for columns that older snapshots don't have)."""
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _is_complete(v) -> bool:
    """Snapshot rows written before the complete marker are NULL and count as complete."""
    return v is None or str(v).lower() == "true"


def _iso(epoch) -> str | None:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(epoch))) if epoch is not None else None


def _wave(r: dict) -> str:
    # 0.8.0 snapshots called wave 0 "enforce candidate"; that wording suggested readiness, so it's shown as no traffic.
    w_ = str(r.get("wave") or "")
    return "0: no legacy traffic" if w_ == "0: enforce candidate" else w_


def _deadlines() -> dict:
    from datetime import date, datetime, timezone

    today = datetime.now(timezone.utc).date()
    v2, v1 = date.fromisoformat(OVERVIEW_V2_STOP), date.fromisoformat(OVERVIEW_V1_STOP)
    return {"v2": {"date": OVERVIEW_V2_STOP, "days_left": (v2 - today).days, "what": "v2 endpoints stop serving"},
            "v1": {"date": OVERVIEW_V1_STOP, "days_left": (v1 - today).days, "what": "v1 (legacy) serving retires"},
            "note": "Dates as of October 30, 2026. Confirm with your account team."}


def _running_snapshot() -> dict | None:
    """The snapshot job's active run (manual or scheduled), so the page can resume polling after a reload."""
    job_id = JOBS.get("snapshot") or ""
    if not job_id.isdigit():
        return None
    try:
        for r in sp().jobs.list_runs(job_id=int(job_id), active_only=True):
            return {"job_run_id": str(r.run_id), "started_at": _iso(r.start_time / 1000) if r.start_time else None}
    except (DatabricksError, ValueError):
        return None
    return None


def _latest_scans(request: Request) -> dict[str, dict]:
    """Latest successful workspace scan per workspace ID (readiness decides whether wave 0 is ready)."""
    rows = query(request, f"""
        SELECT workspace_id, readiness, run_id, unix_timestamp(finished_at) AS finished_epoch FROM (
          SELECT workspace_id, readiness, run_id, finished_at,
                 row_number() OVER (PARTITION BY workspace_id ORDER BY finished_at DESC) AS rn
          FROM {table('ug_migration_scans')}
          WHERE status = 'SUCCEEDED' AND workspace_id IS NOT NULL)
        WHERE rn = 1""")
    return {str(r["workspace_id"]): r for r in rows}


def _workspace_view(r: dict, scans: dict[str, dict], window: int, now: float) -> dict:
    """One workspace row for the page: numbers, wave, readiness (scan-based) and the retirement date that applies."""
    from datetime import date, datetime, timezone

    wave = _wave(r)
    scan = scans.get(str(r.get("workspace_id")))
    scan_epoch = _num(scan.get("finished_epoch")) if scan else None
    passing = bool(scan) and scan.get("readiness") in OVERVIEW_PASSING_SCANS and bool(scan_epoch) \
        and scan_epoch >= now - window * 86400
    if not wave.startswith("0"):
        readiness, ready = None, False
    elif passing:
        readiness, ready = "Ready to enforce (scan passed)", True
    elif wave == "0: traffic unknown":
        readiness, ready = "Traffic unknown; scan required", False
    elif scan and scan.get("readiness") in OVERVIEW_PASSING_SCANS:
        readiness, ready = "No recent traffic; scan required (last pass is older than the window)", False
    elif scan:
        readiness, ready = f"Scan {str(scan.get('readiness')).lower().replace('_', ' ')}; not ready", False
    else:
        readiness, ready = "No recent traffic; scan required", False
    v2 = _num(r.get("v2_requests")) or 0
    v1 = _num(r.get("v1_requests")) or _num(r.get("legacy_endpoints")) or 0
    due_for, due = ("v2", OVERVIEW_V2_STOP) if v2 else ("v1", OVERVIEW_V1_STOP) if v1 else (None, None)
    days_left = (date.fromisoformat(due) - datetime.now(timezone.utc).date()).days if due else None
    v3_share = r.get("v3_share")
    return {"workspace_id": r.get("workspace_id"), "workspace_name": r.get("workspace_name"),
            "status": r.get("status"), "wave": wave, "readiness": readiness, "ready": ready,
            "scan_readiness": scan.get("readiness") if scan else None, "scan_run_id": scan.get("run_id") if scan else None,
            "legacy_endpoints": _num(r.get("legacy_endpoints")), "custom_legacy_endpoints": _num(r.get("custom_legacy_endpoints")),
            "active_legacy_endpoints": _num(r.get("active_legacy_endpoints")),
            "unknown_traffic_endpoints": _num(r.get("unknown_traffic_endpoints")),
            "v1_requests": _num(r.get("v1_requests")), "v2_requests": _num(r.get("v2_requests")),
            "legacy_requests": _num(r.get("legacy_requests")), "legacy_throttled": _num(r.get("legacy_throttled")),
            "deleted_endpoint_requests": _num(r.get("deleted_endpoint_requests")),
            "v3_requests": _num(r.get("v3_requests")), "v3_share": float(v3_share) if v3_share not in (None, "") else None,
            "last_seen": r.get("last_seen"),
            "config_signals": [s for s in str(r.get("config_signals") or "").split(",") if s],
            "due_for": due_for, "due_date": due, "due_days_left": days_left}


def _endpoint_view(r: dict) -> dict:
    kind = str(r.get("kind") or "")
    return {"workspace_id": r.get("workspace_id"), "workspace_name": r.get("workspace_name"),
            "endpoint_name": r.get("endpoint_name"), "kind": kind, "live": "deleted_or_unknown" not in kind,
            "requests": _num(r.get("requests")) or 0, "requesters": _num(r.get("requesters")) or 0,
            "throttled": _num(r.get("throttled")) or 0, "last_request": r.get("last_request"),
            "last_seen": r.get("last_seen"), "traffic_status": r.get("traffic_status")}


def _load_snapshot(request: Request) -> dict:
    """The latest COMPLETE account snapshot, with its trend, scan readiness and retirement dates joined in.

    Snapshot runs with an incomplete marker (a write that didn't finish) are skipped.
    """
    ws_t, ep_t = table(f"{SNAPSHOT_PREFIX}_workspaces"), table(f"{SNAPSHOT_PREFIX}_endpoints")
    now = time.time()
    raw = query(request, f"SELECT *, unix_timestamp(snapshot_time) AS snapshot_epoch FROM {ws_t}")
    runs: dict[int, list] = {}
    for r in raw:
        epoch = _num(r.get("snapshot_epoch"))
        if epoch is not None and _is_complete(r.get("complete")):
            runs.setdefault(epoch, []).append(r)
    out = {"epoch": None, "snapshot_time": None, "window_days": None, "window_assumed": False, "run_id": None,
           "trend": [], "views": [], "endpoints": [], "kpis": {}, "waves": [], "deadlines": _deadlines()}
    if not runs:
        return out
    epochs = sorted(runs)
    trend = []
    for e in epochs:
        rows = runs[e]
        running = [r for r in rows if r.get("status") in (None, "", "RUNNING")]
        window = next((_num(r.get("window_days")) for r in rows if _num(r.get("window_days"))), None)
        trend.append({"snapshot_time": _iso(e), "snapshot_epoch": e, "window_days": window or 30,
                      "workspaces": len(running),
                      "no_traffic": sum(1 for r in running if _wave(r) == "0: no legacy traffic"),
                      "legacy_requests": sum(_num(r.get("legacy_requests")) or 0 for r in rows),
                      "v3_requests": sum(_num(r.get("v3_requests")) or 0 for r in rows),
                      "active_legacy_endpoints": sum(_num(r.get("active_legacy_endpoints")) or 0 for r in rows)})
    latest = epochs[-1]
    rows = runs[latest]
    window = next((_num(r.get("window_days")) for r in rows if _num(r.get("window_days"))), None)
    scans = _latest_scans(request)
    views = [_workspace_view(r, scans, window or 30, now) for r in rows]
    views.sort(key=lambda v: (-(v["legacy_requests"] or 0), -(v["custom_legacy_endpoints"] or 0), str(v["workspace_id"])))
    eps = [_endpoint_view(r) for r in query(request, f"SELECT * FROM {ep_t} "
                                                    "WHERE snapshot_time = timestamp_seconds(CAST(:t AS BIGINT))",
                                            {"t": latest}) if _is_complete(r.get("complete"))]
    eps = [e for e in eps if "out_of_scope" not in e["kind"]]
    eps.sort(key=lambda e: str(e["last_seen"] or ""), reverse=True)
    eps.sort(key=lambda e: -e["requests"])
    running = [v for v in views if v["wave"] != "not running"]
    legacy = sum(v["legacy_requests"] or 0 for v in running)
    v3 = sum(v["v3_requests"] or 0 for v in running)
    counts: dict[str, int] = {}
    for v in running:
        counts[v["wave"]] = counts.get(v["wave"], 0) + 1
    order = OVERVIEW_WAVE_ORDER + sorted(k for k in counts if k not in OVERVIEW_WAVE_ORDER)
    out.update({
        "epoch": latest, "snapshot_time": _iso(latest), "window_days": window or 30, "window_assumed": not window,
        "run_id": rows[0].get("run_id"), "trend": trend, "views": views, "endpoints": eps,
        "waves": [{"wave": k, "workspaces": counts[k]} for k in order if counts.get(k)],
        "kpis": {"running_workspaces": len(running),
                 "no_traffic": counts.get("0: no legacy traffic", 0),
                 "traffic_unknown": counts.get("0: traffic unknown", 0),
                 "no_endpoint_data": counts.get("no endpoint data", 0),
                 "ready": sum(1 for v in running if v["ready"]),
                 "legacy_requests": legacy, "v3_requests": v3,
                 "v3_share": round(v3 / (v3 + legacy), 3) if (v3 + legacy) else None,
                 "active_legacy_endpoints": sum(v["active_legacy_endpoints"] or 0 for v in running),
                 "live_legacy_endpoints": sum(v["legacy_endpoints"] or 0 for v in running),
                 "deleted_endpoint_requests": sum(v["deleted_endpoint_requests"] or 0 for v in running)}})
    return out


@app.get("/api/overview")
def overview(request: Request) -> dict:
    snap = _load_snapshot(request)
    top = [e for e in snap["endpoints"] if e["requests"] or e["last_seen"]][:100]
    return {"snapshot_time": snap["snapshot_time"], "window_days": snap["window_days"],
            "window_assumed": snap["window_assumed"], "run_id": snap["run_id"],
            "running_snapshot": _running_snapshot(), "trend": snap["trend"], "kpis": snap["kpis"],
            "deadlines": snap["deadlines"], "waves": snap["waves"], "workspaces": snap["views"],
            "endpoints": top, "endpoints_limit": 100, "endpoints_total": len(snap["endpoints"])}


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
              offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)) -> dict:
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
    grants: bool = False
    ack_guardrails: bool = False  # execute: acknowledges that legacy guardrails are not migrated
    dry_run_id: str = ""  # execute: the successful dry run of this same selection and options
    allow_stale: bool = False  # apply to a scan older than UGMIG_MAX_SCAN_AGE_DAYS
    rollback_of: str = ""
    confirm: str = ""


def selection_fingerprint(params: dict[str, Any]) -> str:
    """Hash of the selection and options an apply run was started with. An execute must match its dry run's hash."""
    body = json.dumps({k: str(params.get(k, "")) for k in FINGERPRINT_KEYS}, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()


def _age_days(ts: str | None) -> float | None:
    """Days since a UTC timestamp string from the results tables; None if it can't be read."""
    try:
        t = datetime.fromisoformat(str(ts).strip())
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 86400


def _check_scan(request: Request, scan_run_id: str, allow_stale: bool) -> None:
    rows = query(request, f"SELECT status, CAST(coalesce(finished_at, started_at) AS STRING) AS ts "
                          f"FROM {table('ug_migration_scans')} WHERE run_id = :r", {"r": scan_run_id})
    if not rows:
        raise HTTPException(404, "scan not found")
    if rows[0]["status"] != "SUCCEEDED":
        raise HTTPException(409, "That scan didn't finish successfully; apply uses a finished scan")
    age = _age_days(rows[0].get("ts"))
    if not allow_stale and (age is None or age > MAX_SCAN_AGE_DAYS):
        shown = "of unknown age" if age is None else f"{int(age)} days old"
        raise HTTPException(409, f"That scan is {shown} (limit {MAX_SCAN_AGE_DAYS} days). Scan again, or apply "
                                 "anyway with allow_stale set.")


def _verify_dry_run(request: Request, dry_run_id: str, scan_run_id: str, params: dict[str, Any]) -> None:
    """Execute only follows a successful dry run of the same scan, with the same endpoints and options."""
    if not dry_run_id:
        raise HTTPException(400, "Run a dry run with this selection first")
    check_id(dry_run_id, "dry_run_id")
    rows = reconcile(query(request, f"SELECT mode, status, job_run_id, scan_run_id FROM {table('ug_migration_applies')} "
                                    "WHERE apply_id = :a", {"a": dry_run_id}))
    if not rows or rows[0]["mode"] != "dry_run":
        raise HTTPException(400, "dry_run_id must be a dry run")
    if rows[0]["status"] != "SUCCEEDED" or rows[0]["scan_run_id"] != scan_run_id:
        raise HTTPException(409, "That dry run didn't succeed for this scan; run a dry run with this selection first")
    job_run_id = str(rows[0].get("job_run_id") or "")
    if not re.fullmatch(r"[0-9]{1,18}", job_run_id):
        raise HTTPException(409, "Couldn't find the job run of that dry run; run a dry run again")
    try:
        job = sp().jobs.get_run(int(job_run_id))
    except DatabricksError as e:
        raise HTTPException(502, f"Couldn't read the dry run's settings: {str(e)[:200]}")
    dry = {p.name: (p.value if p.value is not None else p.default) for p in (job.job_parameters or [])}
    if selection_fingerprint(dry) != selection_fingerprint(params):
        raise HTTPException(409, "The endpoints or options changed since that dry run; run a dry run with these settings")


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
        if not body.scan_run_id:
            raise HTTPException(400, "choose a scan: apply uses its plan")
        check_id(body.scan_run_id, "scan id")
        if not body.endpoints:
            raise HTTPException(400, "choose at least one endpoint")
        for v in body.endpoints:
            if not is_name(v):
                raise HTTPException(400, f"bad endpoint name {v!r}")
        for v in (body.target_catalog, body.target_schema):
            if not is_name(v):
                raise HTTPException(400, "target catalog and schema are required")
        if body.allow_secret_read and not ALLOW_SECRET_READ:
            raise HTTPException(400, "Copying secret values into provider services isn't enabled for this app. "
                                     "Use Unity Catalog secrets instead.")
        for k, v in body.uc_secret_map.items():
            m = SECRET_REF_RE.fullmatch(str(v))
            if not SECRET_KEY_RE.fullmatch(k) or not m:
                raise HTTPException(400, f'secret map entries must look like "scope/key": "secrets/catalog.schema.name" '
                                         f"(bad entry {k!r})")
            if f"{m[1]}.{m[2]}".lower() not in SECRET_SCHEMAS:
                allowed = ", ".join(sorted(SECRET_SCHEMAS)) or "none (ask the person who installed the app)"
                raise HTTPException(400, f"secret {k!r} must be in an allowed Unity Catalog schema: {allowed}")
        _check_scan(request, body.scan_run_id, body.allow_stale)
        if body.mode == "execute" and not body.ack_guardrails:
            plan = query(request, f"SELECT payload FROM {table('ug_migration_scan_items')} "
                                  "WHERE run_id = :r AND item_type = 'plan'", {"r": body.scan_run_id})
            chosen = set(body.endpoints)
            for p in (_parse_row(_load(r["payload"])) for r in plan):
                needs = p.get("needs_human") or []
                if p.get("legacy_endpoint") in chosen and any("guardrails:" in str(n) for n in needs):
                    raise HTTPException(400, "Some endpoints have guardrails that aren't migrated. Read the notes in the "
                                             "plan and tick the guardrails acknowledgement to execute.")
    params: dict[str, Any] = {
        "results_schema": RESULTS_SCHEMA, "mode": body.mode, "scan_run_id": body.scan_run_id,
        "endpoints": ",".join(body.endpoints), "target_catalog": body.target_catalog,
        "target_schema": body.target_schema,
        "uc_secret_map": json.dumps(body.uc_secret_map, sort_keys=True) if body.uc_secret_map else "",
        "allow_secret_read": str(body.allow_secret_read).lower(), "grants": str(body.grants).lower(),
        "ack_guardrails": str(body.ack_guardrails).lower(), "rollback_of": body.rollback_of,
    }
    if body.mode == "execute":
        _verify_dry_run(request, body.dry_run_id, body.scan_run_id, params)
    if active_runs("apply"):
        raise HTTPException(409, "Another apply run is in progress; wait for it to finish")
    apply_id = str(uuid.uuid4())
    job_run_id = run_job("apply", {"apply_id": apply_id, **params, "requested_by": who(request)})
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

def _cell(v: Any) -> str:
    """CSV cell: lists and dicts as JSON; values that a spreadsheet would run as a formula are prefixed."""
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        v = json.dumps(v, default=str)
    v = str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def _csv_response(rows: list[dict], filename: str, columns: list[str] | None = None, truncated: bool = False) -> Response:
    cols = columns or list(dict.fromkeys(k for r in rows for k in r))
    buf = io.StringIO()
    out = csv.writer(buf)
    out.writerow(cols)
    for r in rows:
        out.writerow([_cell(r.get(c)) for c in cols])
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if truncated:  # the file stops at EXPORT_ROW_LIMIT rows
        headers["X-Truncated"] = "true"
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


def _stamp(t: Any) -> str:
    return re.sub(r"[^0-9]", "", str(t or ""))[:12] or "latest"


@app.get("/api/export/overview/{kind}")
def export_overview(kind: str, request: Request) -> Response:
    """Latest complete account snapshot: workspaces, all legacy endpoints (not only the top 100 shown), or the trend.

    A file that hits EXPORT_ROW_LIMIT is cut off and the response carries X-Truncated: true.
    """
    if kind not in ("workspaces", "endpoints", "trend"):
        raise HTTPException(400, "kind must be workspaces, endpoints or trend")
    snap = _load_snapshot(request)
    if snap["epoch"] is None:
        raise HTTPException(404, "no snapshot yet")
    if kind == "trend":
        return _csv_response(snap["trend"], "ug_migration_trend.csv")
    rows = snap["views"] if kind == "workspaces" else snap["endpoints"]
    resp = _csv_response(rows[:EXPORT_ROW_LIMIT], f"ug_migration_{kind}_{_stamp(snap['snapshot_time'])}.csv")
    if len(rows) > EXPORT_ROW_LIMIT:
        resp.headers["X-Truncated"] = "true"
    return resp


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
    return _csv_response([_load(r["payload"]) for r in rows], f"ug_migration_{kind}_{short}.csv",
                         truncated=len(rows) >= EXPORT_ROW_LIMIT)


@app.get("/api/applies/{apply_id}/export")
def export_apply(apply_id: str, request: Request) -> Response:
    check_id(apply_id, "apply id")
    rows = query(request, f"SELECT payload FROM {table('ug_migration_apply_items')} WHERE apply_id = :a "
                          f"ORDER BY seq LIMIT {EXPORT_ROW_LIMIT}", {"a": apply_id})
    items = [_load(r["payload"]) for r in rows]
    return _csv_response(items, f"ug_migration_apply_{apply_id[:8]}.csv",
                         ["type", "name", "action", "reason", "issues", "grants", "time", "execute"]
                         + sorted({k for i in items for k in i} - {"type", "name", "action", "reason", "issues",
                                                                     "grants", "time", "execute", "body"}),
                         truncated=len(items) >= EXPORT_ROW_LIMIT)


@app.get("/{path:path}")
def spa(path: str):
    if path == "api" or path.startswith("api/"):
        raise HTTPException(404, "not found")
    index = DIST / "index.html"
    if not index.exists():
        raise HTTPException(404, "frontend not built")
    return FileResponse(index)
