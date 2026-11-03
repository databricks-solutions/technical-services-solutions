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
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import DatabricksError, NotFound, PermissionDenied
from databricks.sdk.service.sql import StatementParameterListItem, StatementState
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# The toolkit modules (ug_migration_*.py) hold the rules the jobs use; the app imports them so both sides use one
# copy. A release puts them next to this file (app/backend); in a source checkout they're in the repository root.
_HERE = Path(__file__).resolve().parent
for _dir in (_HERE, _HERE.parent.parent):
    if (_dir / "ug_migration_store.py").exists():
        if str(_dir) not in sys.path:
            sys.path.insert(0, str(_dir))
        break
import ug_migration_apply as apply_rules  # noqa: E402
import ug_migration_planner as planner  # noqa: E402
import ug_migration_store as store  # noqa: E402

WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
RESULTS_SCHEMA = os.environ.get("RESULTS_SCHEMA", "")
SNAPSHOT_PREFIX = os.environ.get("SNAPSHOT_PREFIX", "ug_migration")
JOBS = {"snapshot": os.environ.get("SNAPSHOT_JOB_ID", ""), "scan": os.environ.get("SCAN_JOB_ID", ""),
        "apply": os.environ.get("APPLY_JOB_ID", "")}
OPERATORS = {e.strip().lower() for e in os.environ.get("OPERATORS", "").split(",") if e.strip()}
IN_APP = bool(os.environ.get("DATABRICKS_APP_NAME"))  # set by Databricks Apps; unset when running locally
APP_NAME = os.environ.get("DATABRICKS_APP_NAME", "")
DEFAULT_APP_NAME = "ug-migration-toolkit"  # the installer's default; any other name is a second or test install
# Local development only: UGMIG_LOCAL_DEV=1 runs as the CLI profile's user with no operator check. Ignored inside
# Databricks Apps. Without it, every request needs a verified user from the forwarded token, and operators are required.
LOCAL_DEV = os.environ.get("UGMIG_LOCAL_DEV") == "1" and not IN_APP
# Unity Catalog schemas (catalog.schema) that apply may reference for secrets; set by the installer, not by requests.
SECRET_SCHEMAS = {s.strip().lower() for s in os.environ.get("UGMIG_SECRET_SCHEMAS", "").split(",") if s.strip()}
ALLOW_SECRET_READ = os.environ.get("UGMIG_ALLOW_SECRET_READ", "").strip().lower() in ("1", "true", "yes")
# Central mode (optional): other workspaces the scan job may scan. Changes (apply, cut over) stay in this hub.
try:
    CENTRAL_WORKSPACES: list[str] = planner.parse_workspace_ids(os.environ.get("UGMIG_CENTRAL_WORKSPACES", ""))
except ValueError:
    CENTRAL_WORKSPACES = []
_HUB_ID: dict[str, str] = {"id": os.environ.get("UGMIG_HUB_WORKSPACE_ID", "").strip()}
NOT_ALLOWLISTED = ("Workspace {ws} isn't in this app's central-mode allowlist. Re-run the installer with it in "
                   "Advanced: Central mode: workspaces to manage.")
MAX_SCAN_AGE_DAYS = int(os.environ.get("UGMIG_MAX_SCAN_AGE_DAYS") or 14)
EXPORT_ROW_LIMIT = 200_000
IDENTITY_TTL_S = 300
NAME_RE = re.compile(r"[A-Za-z0-9_\-]+")
ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
SECRET_KEY_RE = re.compile(r"[^/\s{}]+/[^/\s{}]+")
SECRET_REF_RE = re.compile(r"secrets/([A-Za-z0-9_\-]+)\.([A-Za-z0-9_\-]+)\.([A-Za-z0-9_\-]+)")
TERMINAL = ("SUCCEEDED", "NEEDS_ATTENTION", "FAILED")
# The job-side rules, used as they are (see the imports above).
FINGERPRINT_KEYS = store.FINGERPRINT_KEYS  # options that decide what an apply run does; an execute must match its dry run
PROBLEM_ACTIONS = apply_rules.PROBLEM_ACTIONS
# An execute must follow a successful dry run of the same settings started at most this many hours ago.
DRY_RUN_TTL_HOURS = apply_rules.DRY_RUN_TTL_HOURS
JOB_ENDED_STATES = ("TERMINATED", "INTERNAL_ERROR", "SKIPPED")
APPLY_RUNS = "(operation IS NULL OR operation = 'apply')"  # apply runs; rows from before cut-over ops have NULL
CUTOVER_RUNS = "(operation IS NOT NULL AND operation <> 'apply')"
STARTING_WINDOW_S = 3600  # an id the app started without a result row is "still starting" for this long at most

# One legacy deadline for every legacy endpoint (v1 and v2). Override with UGMIG_DEADLINE (YYYY-MM-DD); the installer
# sets it. The same value as ug_migration_planner.LEGACY_DEADLINE (test_app.py checks).
DEADLINE_AS_OF = "2026-11-01"


def _validate_deadline(value: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise ValueError(f"UGMIG_DEADLINE must be an ISO date (YYYY-MM-DD), not {value!r}")
    return value


LEGACY_DEADLINE = _validate_deadline(os.environ.get("UGMIG_DEADLINE") or "2027-03-30")
# Old wave names still found in snapshots, shown under the current names. A copy of ug_migration_account's (the app
# doesn't ship that module); test_app.py checks they agree.
LEGACY_WAVE_NAMES = {"v2 first": "v2 traffic", "0: enforce candidate": "0: no legacy traffic"}

app = FastAPI(title="Unity Gateway Migration")
_sp: WorkspaceClient | None = None
_identities: dict[str, tuple[float, str]] = {}  # sha256(token) -> (expires at, user name)
_admins: dict[str, tuple[float, bool]] = {}  # sha256(token) -> (expires at, in the workspace admins group)
_job_identities: dict[str, tuple[float, str]] = {}  # job kind -> (expires at, who its runs run as)
_owners: dict[str, str] = {}  # job run id -> who started it, for runs this process started
_started: dict[str, dict] = {}  # scan run id / apply id -> {"job_run_id", "at"}, for runs started but not yet stored


class RunActive(Exception):
    """Another run of the same job is active: answered as 409 with the run's job id and link (for the UI)."""

    def __init__(self, what: str, run: dict):
        self.detail = f"{what} is already running (job run {run['job_run_id']}). Wait for it to finish, or open it in Databricks."
        self.run = run


@app.exception_handler(RunActive)
def _run_active(request: Request, exc: RunActive) -> JSONResponse:
    return JSONResponse({"detail": exc.detail, "job_run_id": exc.run["job_run_id"], "url": exc.run.get("url")},
                        status_code=409)


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


def is_workspace_admin(request: Request) -> bool:
    """The signed-in user is in the workspace admins group (asked of Databricks with their token, cached per token)."""
    token = request.headers.get("x-forwarded-access-token")
    if not token:
        return False
    key = hashlib.sha256(token.encode()).hexdigest()
    hit = _admins.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    try:
        me = WorkspaceClient(host=sp().config.host, token=token, auth_type="pat").current_user.me()
        admin = any((g.display or "") == "admins" for g in (getattr(me, "groups", None) or []))
    except Exception:  # fail closed
        admin = False
    if len(_admins) > 1000:
        _admins.clear()
    _admins[key] = (time.time() + IDENTITY_TTL_S, admin)
    return admin


def require_run_access(request: Request, requested_by: Any) -> None:
    """A run's details and exports (results, request ids, replies, errors) are for the person who started it, the
    app's operators and workspace admins. Lists and the overview stay readable by everyone with access to the app."""
    user = who(request)
    if LOCAL_DEV or user in OPERATORS or user == str(requested_by or "").strip().lower() or is_workspace_admin(request):
        return
    raise HTTPException(403, "Only the person who started this run, the app's operators and workspace admins can "
                             "see its details and exports.")


def _run_owner(request: Request, kind: str, run_id: str) -> str:
    """requested_by of a scan or apply run (404 when there is no such run)."""
    tbl, key = ("ug_migration_scans", "run_id") if kind == "scan" else ("ug_migration_applies", "apply_id")
    rows = query(request, f"SELECT requested_by FROM {table(tbl)} WHERE {key} = :k", {"k": run_id})
    if not rows:
        raise HTTPException(404, "not found")
    return str(rows[0].get("requested_by") or "")


def is_name(v: str) -> bool:
    return bool(v) and bool(NAME_RE.fullmatch(v))


def check_id(v: str, what: str) -> str:
    if not ID_RE.fullmatch(v or ""):
        raise HTTPException(400, f"That {what} isn't a valid id")
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


class TableMissing(HTTPException):
    """A table a check reads doesn't exist, or the signed-in user can't see it (both read as TABLE_OR_VIEW_NOT_FOUND)."""

    def __init__(self, message: str):
        super().__init__(409, message)


def query(request: Request, sql: str, params: dict | None = None, missing_ok: bool = True) -> list[dict]:
    """Rows of one SQL statement, run as the signed-in user. A missing table gives no rows (the toolkit's own tables
    before the first run). Checks on system tables pass missing_ok=False: they raise TableMissing instead, so a
    table the user can't see never reads as "no traffic"."""
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
            if missing_ok:
                return []
            raise TableMissing(f"Couldn't read a system table this check needs: {msg[:300]} It doesn't exist or you "
                               "can't see it. Ask an admin to grant you SELECT on the system.serving and "
                               "system.ai_gateway system tables, then check again.")
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


def run_job(kind: str, params: dict[str, str], item_id: str | None = None) -> str:
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
    if item_id:
        if len(_started) > 5000:
            _started.clear()
        _started[item_id] = {"job_run_id": str(run.run_id), "at": time.time()}
    return str(run.run_id)


def active_run(kind: str, what: str) -> dict | None:
    """The active run of a job (job run id and link), or None. If Databricks can't say, refuse to start another run."""
    job_id = JOBS.get(kind)
    if not job_id:
        raise HTTPException(500, f"The {kind} job isn't configured")
    try:
        for r in sp().jobs.list_runs(job_id=int(job_id), active_only=True):
            return {"job_run_id": str(r.run_id), "url": r.run_page_url}
    except Exception:
        raise HTTPException(503, f"Couldn't check whether {what} is already running, so nothing was started. "
                                 "Try again in a minute.")
    return None


def _ended_state(job_run_id) -> Any:
    """The state of a job run that has ended, else None (the same rule as store.effective_status)."""
    if not re.fullmatch(r"[0-9]{1,18}", str(job_run_id or "")):
        return None
    try:
        st = sp().jobs.get_run(int(job_run_id)).state
    except Exception:
        return None
    return st if st and st.life_cycle_state and st.life_cycle_state.value in JOB_ENDED_STATES else None


def reconcile(rows: list[dict]) -> list[dict]:
    """A job that was killed can leave its row at RUNNING; show it as FAILED once the job run has ended."""
    for r in rows:
        if r.get("status") == "FAILED" and not r.get("finished_at"):
            r["finished_at"] = "(job ended)"
        if r.get("status") == "RUNNING":
            st = _ended_state(r.get("job_run_id"))
            if st:
                r["status"] = "FAILED"
                r["finished_at"] = r.get("finished_at") or "(job ended)"
                r["error"] = r.get("error") or (f"The job run ended ({st.result_state.value if st.result_state else st.life_cycle_state.value}) "
                                                "without recording a result.")
    return rows


def who(request: Request) -> str:
    """The verified signed-in user (lower case). Raises 401 when the request has no verified user."""
    user = verified_user(request)
    if not user:
        raise HTTPException(401, "No signed-in user: enable user authorization (sql scope) for this app")
    return user


def starting_job(item_id: str) -> str | None:
    """Job run id of a scan or apply this app started whose result row isn't written yet (the job is still going).

    None means the id is unknown, or its job ended without writing a row: the caller answers 404 "not found"."""
    hit = _started.get(item_id)
    if not hit:
        return None
    if _ended_state(hit["job_run_id"]) or time.time() - hit["at"] > STARTING_WINDOW_S:
        _started.pop(item_id, None)
        return None
    return hit["job_run_id"]


def starting_response(kind: str, item_id: str, job_run_id: str) -> JSONResponse:
    """202 for a run that has started but has no row yet. The body's meta.status is STARTING."""
    return JSONResponse({"detail": "still starting", "status": "STARTING", "job_run_id": job_run_id,
                         "meta": {kind: item_id, "status": "STARTING", "job_run_id": job_run_id}}, status_code=202)


# ---------------------------------------------------------------------------
# Identity and config
# ---------------------------------------------------------------------------


@app.get("/api/whoami")
def whoami(request: Request) -> dict:
    user = verified_user(request)
    return {"email": user or "", "user_authorization": bool(request.headers.get("x-forwarded-access-token")),
            "operator": bool(LOCAL_DEV or (user is not None and user in OPERATORS)), "workspace": sp().config.host}


def hub_workspace_id() -> str:
    """The workspace this app (and its jobs) runs in: from the installer, else asked once."""
    if not _HUB_ID["id"]:
        try:
            _HUB_ID["id"] = str(planner.workspace_id_of(sp()))
        except Exception:
            return ""
    return _HUB_ID["id"]


def norm_workspace(ws: Any) -> str:
    """A run's target workspace as the jobs fingerprint it: blank for the hub (or unknown), else its ID."""
    ws = str(ws or "").strip()
    if not CENTRAL_WORKSPACES:
        return ""  # without central mode every run is the hub's, as before
    hub = hub_workspace_id()
    if not hub:  # fail closed: without the hub's ID a remote workspace could pass for the hub
        raise HTTPException(503, "Couldn't tell which workspace this app runs in, so central-mode changes are off. "
                                 "Try again in a minute; if it persists, run the installer again.")
    return "" if (not ws or ws == hub) else ws


def allowed_workspace(ws: Any) -> str:
    """norm_workspace, refusing a workspace other than the hub that isn't on the central-mode allowlist (409)."""
    target = norm_workspace(ws)
    if target and target not in CENTRAL_WORKSPACES:
        raise HTTPException(409, NOT_ALLOWLISTED.format(ws=target))
    return target


def scan_workspace(request: Request, scan_run_id: str) -> str:
    """The workspace a scan covered, as a change target: blank for the hub. Changes act on the scan's workspace."""
    if not scan_run_id:
        return ""
    rows = query(request, f"SELECT workspace_id FROM {table('ug_migration_scans')} WHERE run_id = :r", {"r": scan_run_id})
    ws = str((rows[0].get("workspace_id") if rows else "") or "").strip()
    if CENTRAL_WORKSPACES and not ws:  # fail closed: an unknown workspace is never taken to be the hub
        raise HTTPException(409, "That scan doesn't record which workspace it covered, so it can't drive a change in "
                                 "central mode. Scan the workspace again.")
    return allowed_workspace(ws)


def run_workspace(request: Request, apply_id: str) -> str:
    """The workspace an earlier apply or cut-over run acted on (rollback and resume act there, never elsewhere)."""
    rows = query(request, f"SELECT workspace_id FROM {table('ug_migration_applies')} WHERE apply_id = :a", {"a": apply_id})
    return allowed_workspace((rows[0].get("workspace_id") if rows else "") or "")


@app.get("/api/workspaces")
def workspaces(request: Request) -> dict:
    """Central mode: the hub and the allowlisted workspaces, with names and URLs from system.access.workspaces_latest
    (read as the signed-in user; without access, only the IDs). Off: just the hub."""
    hub = hub_workspace_id()
    ids = [hub] + [i for i in CENTRAL_WORKSPACES if i != hub] if hub else list(CENTRAL_WORKSPACES)
    names: dict[str, dict] = {}
    if CENTRAL_WORKSPACES and ids:
        try:
            marks = ", ".join(f":w{i}" for i in range(len(ids)))
            for r in query(request, "SELECT CAST(workspace_id AS STRING) AS workspace_id, workspace_name, workspace_url "
                                    f"FROM system.access.workspaces_latest WHERE CAST(workspace_id AS STRING) IN ({marks})",
                           {f"w{i}": v for i, v in enumerate(ids)}, missing_ok=False):
                names[str(r["workspace_id"])] = r
        except Exception:
            names = {}
    return {"central": bool(CENTRAL_WORKSPACES), "hub_workspace_id": hub,
            "workspaces": [{"workspace_id": i, "hub": i == hub, "name": (names.get(i) or {}).get("workspace_name"),
                            "url": (names.get(i) or {}).get("workspace_url")} for i in ids]}


@app.get("/api/config")
def config() -> dict:
    try:
        host = sp().config.host or ""
    except Exception:
        host = ""
    return {"results_schema": RESULTS_SCHEMA, "warehouse_id": WAREHOUSE_ID,
            "jobs": {k: bool(v) for k, v in JOBS.items()},
            "secret_schemas": sorted(SECRET_SCHEMAS), "allow_secret_read": ALLOW_SECRET_READ,
            "max_scan_age_days": MAX_SCAN_AGE_DAYS, "export_row_limit": EXPORT_ROW_LIMIT,
            "deadline": LEGACY_DEADLINE, "deadline_as_of": DEADLINE_AS_OF,
            # The app's name, so a second install (any name but the default) is labelled in the header.
            "app_name": APP_NAME, "default_app_name": DEFAULT_APP_NAME,
            # Scans, apply and the test call run as the jobs' identity, not as the signed-in user.
            "jobs_run_as": job_identity("apply") or None,
            # Scans read the workspace the app's jobs run in, and only that one (unless central mode is on).
            "workspace_url": host, "scan_scope": (
                f"This app scans {host} and {len(CENTRAL_WORKSPACES)} more allowlisted workspaces (central mode)."
                if CENTRAL_WORKSPACES else f"This app scans only {host}." if host else
                "This app scans only the workspace it runs in."),
            "central": {"enabled": bool(CENTRAL_WORKSPACES), "workspaces": CENTRAL_WORKSPACES,
                        "hub_workspace_id": hub_workspace_id() if CENTRAL_WORKSPACES else None}}


@app.get("/api/target-schema")
def target_schema(request: Request, catalog: str = "", schema: str = "") -> dict:
    """Whether the target schema for new model services exists, as the signed-in user sees it.

    Checked with SQL through the warehouse: the user's token only carries the sql scope, so Unity Catalog REST calls
    with it fail. can_create_service stays null: apply runs as the installer's identity, whose grants (often through
    groups) can't be read reliably here, so the apply job checks them itself."""
    if not is_name(catalog) or not is_name(schema):
        raise HTTPException(400, "catalog and schema names may only contain letters, digits, _ and -")
    full = f"{catalog}.{schema}"
    try:
        rows = query(request, f"SELECT 1 AS found FROM `{catalog}`.information_schema.schemata "
                              "WHERE schema_name = :s LIMIT 1", {"s": schema})
    except HTTPException as e:
        if e.status_code in (401, 403):
            raise
        return {"exists": False, "can_create_service": None, "error": f"Couldn't read {full}: {str(e.detail)[:200]}"}
    except Exception as e:
        return {"exists": False, "can_create_service": None, "error": f"Couldn't read {full}: {str(e)[:200]}"}
    return {"exists": bool(rows), "can_create_service": None, "error": None}


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
        raise HTTPException(400, "That job run id isn't valid")
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


OVERVIEW_PASSING_SCANS = ("READY", "READY_WITH_WARNINGS")
OVERVIEW_WAVE_ORDER = ["v2 traffic", "2: high volume", "1: small", "1: cleanup", "0: traffic unknown",
                       "0: no legacy traffic", "no legacy endpoints (custom ML only)", "no endpoint data",
                       "not running", "unknown"]


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
    # Snapshots keep the wave names they were written with; LEGACY_WAVE_NAMES shows them under the current names.
    w_ = str(r.get("wave") or "")
    return LEGACY_WAVE_NAMES.get(w_, w_)


def _deadline() -> dict:
    """The one legacy deadline (LEGACY_DEADLINE), with the days left from today."""
    today = datetime.now(timezone.utc).date()
    return {"date": LEGACY_DEADLINE, "days_left": (date.fromisoformat(LEGACY_DEADLINE) - today).days,
            "as_of": DEADLINE_AS_OF,
            "what": "Legacy serving endpoints (v1 and v2) stop serving. Custom model and feature serving aren't affected; "
                    "Government cloud workspaces can have different dates: ask your account team."}


def _sum_known(values) -> int | None:
    """Sum of the values that are known; None when none is (snapshots from before the caller columns)."""
    known = [v for v in values if v is not None]
    return sum(known) if known else None


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
    v3_share = r.get("v3_share")
    return {"workspace_id": r.get("workspace_id"), "workspace_name": r.get("workspace_name"),
            "status": r.get("status"), "wave": wave, "readiness": readiness, "ready": ready,
            "scan_readiness": scan.get("readiness") if scan else None, "scan_run_id": scan.get("run_id") if scan else None,
            "legacy_endpoints": _num(r.get("legacy_endpoints")), "custom_legacy_endpoints": _num(r.get("custom_legacy_endpoints")),
            "active_legacy_endpoints": _num(r.get("active_legacy_endpoints")),
            "unknown_traffic_endpoints": _num(r.get("unknown_traffic_endpoints")),
            "v1_requests": _num(r.get("v1_requests")), "v2_requests": _num(r.get("v2_requests")),
            "v2_failed": _num(r.get("v2_failed")), "v2_failing": v2_mostly_failing(_num(r.get("v2_requests")) or 0,
                                                                                 _num(r.get("v2_failed")) or 0),
            "legacy_requests": _num(r.get("legacy_requests")), "legacy_throttled": _num(r.get("legacy_throttled")),
            "legacy_tokens": _num(r.get("legacy_tokens")),
            "deleted_endpoint_requests": _num(r.get("deleted_endpoint_requests")),
            "v3_requests": _num(r.get("v3_requests")), "v3_share": float(v3_share) if v3_share not in (None, "") else None,
            "last_seen": r.get("last_seen"),
            "config_signals": [s for s in str(r.get("config_signals") or "").split(",") if s],
            "customer_requests": _num(r.get("customer_requests")), "platform_requests": _num(r.get("platform_requests")),
            "coding_agent_requests": _num(r.get("coding_agent_requests"))}


def _endpoint_view(r: dict) -> dict:
    kind = str(r.get("kind") or "")
    return {"workspace_id": r.get("workspace_id"), "workspace_name": r.get("workspace_name"),
            "endpoint_name": r.get("endpoint_name"), "kind": kind, "live": "deleted_or_unknown" not in kind,
            "requests": _num(r.get("requests")) or 0, "requesters": _num(r.get("requesters")) or 0,
            "throttled": _num(r.get("throttled")) or 0, "last_request": r.get("last_request"),
            "last_seen": r.get("last_seen"), "traffic_status": r.get("traffic_status"),
            "legacy_tokens": _num(r.get("legacy_tokens")),
            "customer_requests": _num(r.get("customer_requests")), "platform_requests": _num(r.get("platform_requests")),
            "coding_agent_requests": _num(r.get("coding_agent_requests"))}


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
           "trend": [], "views": [], "endpoints": [], "kpis": {}, "waves": [], "deadline": _deadline()}
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
                 "legacy_tokens": _sum_known(v["legacy_tokens"] for v in running),
                 "v2_failing_workspaces": sum(1 for v in running if v["v2_failing"]),
                 "v3_share": round(v3 / (v3 + legacy), 3) if (v3 + legacy) else None,
                 "active_legacy_endpoints": sum(v["active_legacy_endpoints"] or 0 for v in running),
                 "live_legacy_endpoints": sum(v["legacy_endpoints"] or 0 for v in running),
                 "deleted_endpoint_requests": sum(v["deleted_endpoint_requests"] or 0 for v in running),
                 "customer_requests": _sum_known(v["customer_requests"] for v in running),
                 "platform_requests": _sum_known(v["platform_requests"] for v in running),
                 "coding_agent_requests": _sum_known(v["coding_agent_requests"] for v in running)}})
    return out


@app.get("/api/overview")
def overview(request: Request) -> dict:
    snap = _load_snapshot(request)
    top = [e for e in snap["endpoints"] if e["requests"] or e["last_seen"]][:100]
    return {"snapshot_time": snap["snapshot_time"], "window_days": snap["window_days"],
            "window_assumed": snap["window_assumed"], "run_id": snap["run_id"],
            "running_snapshot": _running_snapshot(), "trend": snap["trend"], "kpis": snap["kpis"],
            "deadline": snap["deadline"], "waves": snap["waves"], "workspaces": snap["views"],
            "endpoints": top, "endpoints_limit": 100, "endpoints_total": len(snap["endpoints"])}


@app.post("/api/account/snapshot")
def refresh_snapshot(request: Request) -> dict:
    require_operator(request)
    run = active_run("snapshot", "a snapshot")
    if run:
        raise RunActive("A snapshot", run)
    return {"job_run_id": run_job("snapshot", {"requested_by": who(request)})}


# ---------------------------------------------------------------------------
# Workspace scans
# ---------------------------------------------------------------------------


class ScanRequest(BaseModel):
    days: int = Field(30, ge=1, le=365)
    scan_roots: str = Field("", max_length=2000)
    target_catalog: str = "ai_gateway"
    target_schema: str = "migrated"
    target_workspace_id: str = Field("", max_length=20)  # central mode: an allowlisted workspace; blank = this one


@app.get("/api/scans")
def list_scans(request: Request, workspace_id: str = "") -> list[dict]:
    """Recent scans. workspace_id (central mode) keeps one workspace's scans; the hub's include older rows
    that didn't record a workspace."""
    where, params = "", {}
    if workspace_id:
        if not planner.WORKSPACE_ID_RE.fullmatch(workspace_id):
            raise HTTPException(400, "workspace_id is a number")
        where = "WHERE workspace_id = :ws" + (" OR workspace_id IS NULL" if workspace_id == hub_workspace_id() else "")
        params = {"ws": workspace_id}
    return reconcile(query(request, f"""
        SELECT run_id, job_run_id, requested_by, workspace_url, workspace_id, status, readiness, endpoints,
               client_references, traffic_status, days, target_catalog, target_schema, toolkit_version, error,
               CAST(started_at AS STRING) AS started_at, CAST(finished_at AS STRING) AS finished_at
        FROM {table('ug_migration_scans')} {where} ORDER BY started_at DESC LIMIT 50""", params))


@app.post("/api/scans")
def start_scan(body: ScanRequest, request: Request) -> dict:
    require_operator(request)
    for v in (body.target_catalog, body.target_schema):
        if not is_name(v):
            raise HTTPException(400, "catalog and schema names may only contain letters, digits, _ and -")
    run = active_run("scan", "a scan")
    if run:
        raise RunActive("A scan", run)
    roots = [r.strip() for r in body.scan_roots.split(",") if r.strip()]
    for r in roots:
        if r == "/" or not re.fullmatch(r"/[^\s,'\"]*", r) or ".." in r:
            raise HTTPException(400, f"Folders must be workspace paths such as /Users or /Repos/team, not {r!r}")
    target = (body.target_workspace_id or "").strip()
    if target and target != hub_workspace_id():
        # Central mode: only an allowlisted workspace; the job checks the allowlist again and resolves the URL itself.
        if target not in CENTRAL_WORKSPACES:
            raise HTTPException(400, f"Workspace {target} isn't one this app may scan. The installer's Central mode "
                                     "setting lists the workspaces it manages.")
    else:
        target = ""
    run_id = str(uuid.uuid4())
    params = {"run_id": run_id, "results_schema": RESULTS_SCHEMA, "days": body.days, "scan_roots": ",".join(roots),
              "target_catalog": body.target_catalog, "target_schema": body.target_schema, "requested_by": who(request)}
    if target:
        params["target_workspace_id"] = target
    job_run_id = run_job("scan", params, item_id=run_id)
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
               "note", "detail", "item", "name", "user_agent", "caller_class", "requester_name"}


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
def scan_detail(run_id: str, request: Request):
    """Scan detail. 200 with the scan; 202 (meta.status STARTING) while the job has started but hasn't stored
    its row; 404 "not found" for an unknown scan."""
    check_id(run_id, "scan id")
    meta = query(request, f"""
        SELECT run_id, job_run_id, requested_by, workspace_url, workspace_id, status, readiness, endpoints,
               client_references, traffic_status, days, target_catalog, target_schema, scan_roots, toolkit_version,
               error, CAST(started_at AS STRING) AS started_at, CAST(finished_at AS STRING) AS finished_at
        FROM {table('ug_migration_scans')} WHERE run_id = :r""", {"r": run_id})
    if not meta:
        job_run_id = starting_job(run_id)
        if job_run_id:
            return starting_response("run_id", run_id, job_run_id)
        raise HTTPException(404, "not found")
    require_run_access(request, meta[0].get("requested_by"))
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
    require_run_access(request, _run_owner(request, "scan", run_id))
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
    create_uc_secrets: bool = False  # the job creates the Unity Catalog secrets in uc_secret_map from the workspace secrets
    grants: bool = False
    ack_guardrails: bool = False  # execute: acknowledges that legacy guardrails are not migrated
    dry_run_id: str = ""  # execute: the successful dry run of this same selection and options
    allow_stale: bool = False  # apply to a scan older than UGMIG_MAX_SCAN_AGE_DAYS
    smoke_test: bool | None = None  # execute: GET each created service afterwards (no inference); default on for execute
    rollback_of: str = ""
    confirm: str = ""
    # There is no force field: rollback of changed objects is a command-line decision (USER_GUIDE.md, "Apply from the command line").


def _age_days(ts) -> float | None:
    """Days since a time from the results tables: epoch seconds (unix_timestamp, independent of the warehouse's
    session time zone) or a UTC string; None if it can't be read."""
    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
        return (datetime.now(timezone.utc).timestamp() - ts) / 86400
    if isinstance(ts, str) and re.fullmatch(r"-?[0-9]+", ts.strip()):
        return (datetime.now(timezone.utc).timestamp() - int(ts)) / 86400
    try:
        t = datetime.fromisoformat(str(ts).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 86400


def _check_scan(request: Request, scan_run_id: str, allow_stale: bool) -> None:
    rows = query(request, f"SELECT status, unix_timestamp(coalesce(finished_at, started_at)) AS ts "
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


def _epoch(v):
    """unix_timestamp() comes back from the SQL API as a string of digits; dry_run_expired reads int epochs as UTC."""
    if isinstance(v, str) and re.fullmatch(r"-?[0-9]+", v.strip()):
        return int(v)
    return v


def _check_dry_run_age(row: dict) -> None:
    """An execute follows a dry run started at most DRY_RUN_TTL_HOURS ago (the job checks the same). started_at is
    read as epoch seconds (unix_timestamp), so the warehouse's session time zone doesn't shift the window."""
    if apply_rules.dry_run_expired(_epoch(row.get("started_at"))):
        raise HTTPException(409, f"That dry run is more than {DRY_RUN_TTL_HOURS} hours old, or its start time can't be "
                                 "read. Things may have changed since: run a dry run again.")


DRY_RUN_USED = "That dry run was already used by an execute. Run a new dry run, then execute."


def _check_dry_run_unused(request: Request, dry_run_id: str) -> None:
    """A dry run unlocks one execute: refuse when an execute already recorded this dry_run_id (the job checks the
    same). Results tables from before the dry_run_id column read as unused (no column, nothing recorded)."""
    try:
        sql, params = store.dry_run_used(RESULTS_SCHEMA, dry_run_id)
        used = query(request, sql, params)
    except HTTPException as e:
        if "dry_run_id" in str(e.detail) and ("UNRESOLVED_COLUMN" in str(e.detail) or "cannot be resolved" in str(e.detail)):
            return
        raise
    if used:
        raise HTTPException(409, DRY_RUN_USED)


def _verify_dry_run(request: Request, dry_run_id: str, scan_run_id: str, params: dict[str, Any]) -> None:
    """Execute only follows a successful dry run of the same scan, with the same endpoints and options.

    The dry run stored its selection fingerprint on its row (computed from the parameters the job received), so
    the comparison doesn't depend on the job's stored parameter values. Dry runs from before that column existed
    fall back to the job run's parameters."""
    if not dry_run_id:
        raise HTTPException(400, "Run a dry run with this selection first")
    check_id(dry_run_id, "dry run id")
    rows = reconcile(query(request, f"SELECT mode, status, job_run_id, scan_run_id, fingerprint, operation, "
                                    f"unix_timestamp(started_at) AS started_at "
                                    f"FROM {table('ug_migration_applies')} WHERE apply_id = :a", {"a": dry_run_id}))
    if not rows or rows[0]["mode"] != "dry_run" or (rows[0].get("operation") or "apply") != "apply":
        raise HTTPException(400, "dry_run_id must be a dry run")
    _check_dry_run_unused(request, dry_run_id)
    if rows[0]["status"] != "SUCCEEDED" or rows[0]["scan_run_id"] != scan_run_id:
        raise HTTPException(409, "That dry run didn't succeed for this scan; run a dry run with this selection first")
    _check_dry_run_age(rows[0])
    if rows[0].get("fingerprint"):
        if rows[0]["fingerprint"] != store.selection_fingerprint(params):
            raise HTTPException(409, "The endpoints or options changed since that dry run; run a dry run with these settings")
        return
    job_run_id = str(rows[0].get("job_run_id") or "")
    if not re.fullmatch(r"[0-9]{1,18}", job_run_id):
        raise HTTPException(409, "Couldn't find the job run of that dry run; run a dry run again")
    try:
        job = sp().jobs.get_run(int(job_run_id))
    except DatabricksError as e:
        raise HTTPException(502, f"Couldn't read the dry run's settings: {str(e)[:200]}")
    dry = {p.name: (p.value if p.value is not None else p.default) for p in (job.job_parameters or [])}
    if store.selection_fingerprint(dry) != store.selection_fingerprint(params):
        raise HTTPException(409, "The endpoints or options changed since that dry run; run a dry run with these settings")


def _rollback_rows(request: Request, rollback_of: str | None = None) -> list[dict]:
    """Rollback rows (optionally for one execute run) with what the rolled-back rule needs."""
    where = "mode = 'rollback'" + (" AND rollback_of = :a" if rollback_of else "")
    return query(request, f"SELECT apply_id, rollback_of, status, job_run_id, CAST(summary AS STRING) AS summary "
                          f"FROM {table('ug_migration_applies')} WHERE {where} ORDER BY started_at DESC",
                 {"a": rollback_of} if rollback_of else None)


@app.get("/api/applies")
def list_applies(request: Request, workspace_id: str = "") -> list[dict]:
    """Recent apply runs. rolled_back is true for an execute run whose rollback is done (see _rollback_done).
    workspace_id (central mode): only runs that acted on that workspace (rows without one are the hub's)."""
    rows = reconcile(query(request, f"""
        SELECT apply_id, job_run_id, requested_by, scan_run_id, mode, endpoints, target_catalog, target_schema,
               workspace_id,
               rollback_of, status, summary, error, CAST(started_at AS STRING) AS started_at,
               CAST(finished_at AS STRING) AS finished_at
        FROM {table('ug_migration_applies')} WHERE {APPLY_RUNS} ORDER BY started_at DESC LIMIT 50"""))
    done = {r["rollback_of"] for r in _rollback_rows(request) if store.rollback_done(r.get("status"), r.get("summary"))}
    for r in rows:
        r["rolled_back"] = r.get("mode") == "execute" and r.get("apply_id") in done
    return _for_workspace(rows, workspace_id)


def _for_workspace(rows: list[dict], workspace_id: str) -> list[dict]:
    """Run rows of one workspace (blank: every row). Each row gets workspace_id filled in (the hub's when blank)."""
    hub = hub_workspace_id()
    for r in rows:
        r["workspace_id"] = str(r.get("workspace_id") or "") or hub or None
    if not str(workspace_id or "").strip():
        return rows
    want = norm_workspace(workspace_id)
    return [r for r in rows if norm_workspace(r.get("workspace_id")) == want]


@app.get("/api/applies/{apply_id}")
def apply_detail(apply_id: str, request: Request):
    """Apply run detail. 200 with the run; 202 (meta.status STARTING) while the job has started but hasn't stored
    its row; 404 "not found" for an unknown run."""
    check_id(apply_id, "apply id")
    meta = query(request, f"""
        SELECT apply_id, job_run_id, requested_by, scan_run_id, mode, endpoints, target_catalog, target_schema,
               rollback_of, status, summary, error, CAST(started_at AS STRING) AS started_at,
               CAST(finished_at AS STRING) AS finished_at, workspace_id, workspace_url
        FROM {table('ug_migration_applies')} WHERE apply_id = :a AND {APPLY_RUNS}""", {"a": apply_id})
    if not meta:
        job_run_id = starting_job(apply_id)
        if job_run_id:
            return starting_response("apply_id", apply_id, job_run_id)
        raise HTTPException(404, "not found")
    require_run_access(request, meta[0].get("requested_by"))
    items = query(request, f"SELECT seq, payload FROM {table('ug_migration_apply_items')} "
                           "WHERE apply_id = :a ORDER BY seq", {"a": apply_id})
    rollbacks = _rollback_rows(request, apply_id)
    out = reconcile(meta)[0]
    out["rolled_back"] = out.get("mode") == "execute" and any(store.rollback_done(r.get("status"), r.get("summary"))
                                                              for r in rollbacks)
    return {"meta": out, "items": [_load(i["payload"]) for i in items],
            "rollbacks": [{"apply_id": r["apply_id"], "status": r["status"]} for r in rollbacks]}


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
        src = reconcile(query(request, f"SELECT mode, status, job_run_id, operation FROM {table('ug_migration_applies')} "
                                       "WHERE apply_id = :a", {"a": body.rollback_of}))
        if not src or src[0]["mode"] != "execute":
            raise HTTPException(400, "rollback_of must be an execute run")
        if (src[0].get("operation") or "apply") != "apply":
            raise HTTPException(400, "rollback_of must be an apply execute run. A pause run is resumed from "
                                     "Verify & cut over.")
        if src[0]["status"] not in TERMINAL:
            raise HTTPException(409, "That execute run hasn't finished yet")
        if store.rollback_blocks(_rollback_rows(request, body.rollback_of), sp()):
            raise HTTPException(409, "That execute run has already been rolled back, or a rollback of it is running")
        body.endpoints, body.target_catalog, body.target_schema, body.uc_secret_map = [], "", "", {}
        body.allow_secret_read = body.create_uc_secrets = False
        target_ws = run_workspace(request, body.rollback_of)
    else:
        if not body.scan_run_id:
            raise HTTPException(400, "choose a scan: apply uses its plan")
        check_id(body.scan_run_id, "scan id")
        target_ws = scan_workspace(request, body.scan_run_id)  # changes act on the workspace the scan covered
        if not body.endpoints:
            raise HTTPException(400, "choose at least one endpoint")
        for v in body.endpoints:
            if not is_name(v):
                raise HTTPException(400, f"That endpoint name isn't valid: {v!r}")
        for v in (body.target_catalog, body.target_schema):
            if not is_name(v):
                raise HTTPException(400, "target catalog and schema are required")
        if body.allow_secret_read and not ALLOW_SECRET_READ:
            raise HTTPException(400, "Copying secret values into provider services isn't enabled for this app. "
                                     "Use Unity Catalog secrets instead.")
        if body.create_uc_secrets:
            if body.allow_secret_read:
                raise HTTPException(400, "Choose one way to handle API keys: create Unity Catalog secrets, or copy the "
                                         "values into the provider services.")
            if not SECRET_SCHEMAS:
                raise HTTPException(400, "Creating Unity Catalog secrets needs an allowed secret schema. Re-run the "
                                         "installer with Advanced: Allowed secret schemas set.")
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
                if p.get("legacy_endpoint") in chosen and any(str(n).removeprefix("BLOCKS APPLY: ").startswith("guardrails")
                                                               for n in needs):
                    raise HTTPException(400, "Some endpoints have guardrails that aren't migrated. Read the notes in the "
                                             "plan and tick the guardrails acknowledgement to execute.")
    # smoke_test and force are job parameters the bundle declares. The app sends smoke_test; force never comes from
    # the app (it is a command-line decision, USER_GUIDE.md, "Apply from the command line").
    smoke = body.smoke_test if body.smoke_test is not None else body.mode == "execute"
    params: dict[str, Any] = {
        "results_schema": RESULTS_SCHEMA, "mode": body.mode, "scan_run_id": body.scan_run_id,
        "endpoints": ",".join(sorted(body.endpoints)), "target_catalog": body.target_catalog,
        "target_schema": body.target_schema,
        "uc_secret_map": json.dumps(body.uc_secret_map, sort_keys=True) if body.uc_secret_map else "",
        "allow_secret_read": str(body.allow_secret_read).lower(), "grants": str(body.grants).lower(),
        "ack_guardrails": str(body.ack_guardrails).lower(), "rollback_of": body.rollback_of,
        "create_uc_secrets": str(body.create_uc_secrets).lower(),
        "smoke_test": str(body.mode == "execute" and bool(smoke)).lower(),
        "target_workspace_id": target_ws,
    }
    if body.mode == "execute":
        _verify_dry_run(request, body.dry_run_id, body.scan_run_id, params)
    run = active_run("apply", "an apply run")
    if run:
        raise RunActive("An apply run", run)
    apply_id = str(uuid.uuid4())
    # The job checks the dry run again itself (same fingerprint, same requester, not expired), so it needs its id.
    gate = {"dry_run_id": body.dry_run_id} if body.mode == "execute" else {}
    job_run_id = run_job("apply", {"apply_id": apply_id, **params, **gate, "requested_by": who(request)},
                         item_id=apply_id)
    return {"apply_id": apply_id, "job_run_id": job_run_id}


# ---------------------------------------------------------------------------
# Verify and cut over (runs of the apply job with an operation other than apply)
# ---------------------------------------------------------------------------

# Options of the apply job (ug_migration_apply.py); the verify SQL and fingerprints come from ug_migration_store.py.
OPERATIONS = apply_rules.OPERATIONS
WRITE_LEGACY_OPERATIONS = apply_rules.WRITE_LEGACY_OPERATIONS
CUTOVER_OPERATIONS = tuple(o for o in OPERATIONS if o != "apply")
API_TYPES = apply_rules.API_TYPES
DEFAULT_API_TYPE = apply_rules.DEFAULT_API_TYPE
DEFAULT_PROMPT = apply_rules.DEFAULT_PROMPT
MAX_PROMPT_CHARS = apply_rules.MAX_PROMPT_CHARS
MAX_TEST_SERVICES = apply_rules.MAX_TEST_SERVICES  # each service gets one billable request
SERVICE_NAME_RE = apply_rules.SERVICE_NAME_RE
# Traffic windows the cut-over page offers (the scan's own window is "scan").
TRAFFIC_WINDOWS = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}
# Plan kinds that aren't legacy endpoints for the traffic check, and kinds the pause and tracking lists don't offer.
NOT_LEGACY_KINDS = ("custom_model", "agent")
# Kinds the cut-over steps never act on. databricks-* pay-per-token endpoints (system_ppt) can be paused (README
# step 5, the main Enforce case) but not tracked: Databricks sets their usage tracking.
# Custom model endpoints are listed only so usage tracking can be turned on (a custom agent's callers are missing from
# usage without it); they are never paused, since they don't retire.
NOT_OPERABLE_KINDS = ("agent", "v2_workspace_endpoint", "unknown", "out_of_scope", "deleted_or_unknown")
NOT_TRACKABLE_KINDS = ("system_ppt",)
# Kinds the pause step doesn't offer or accept (the job refuses them too): a PT endpoint's model service routes through it.
NOT_PAUSABLE_KINDS = ("provisioned_throughput", "custom_model")
CUSTOM_PAUSE_REFUSAL = "custom model endpoints aren't retired by Unity Gateway, so the toolkit doesn't pause them"
USAGE_COLUMNS = ["service_name", "workspace_id", "requester", "api_type", "destination_model", "requests",
                 "invocations", "total_tokens", "average_latency_ms", "p95_latency_ms", "error_invocations",
                 "last_request"]

# v2 calls already failing (v2 is off for the workspace): the planner's rule, on the traffic counts.
V2_FAILING_MIN_REQUESTS = planner.V2_FAILING_MIN_REQUESTS
V2_FAILING_SHARE_PERCENT = planner.V2_FAILING_SHARE_PERCENT


def v2_mostly_failing(v2_requests: int, v2_failed: int) -> bool:
    """At least V2_FAILING_MIN_REQUESTS v2 requests, and at least V2_FAILING_SHARE_PERCENT of them failed."""
    return v2_requests >= V2_FAILING_MIN_REQUESTS and 100 * v2_failed >= V2_FAILING_SHARE_PERCENT * v2_requests


def _unique(names) -> list[str]:
    out: list[str] = []
    for n in names:
        n = str(n).strip()
        if n and n not in out:
            out.append(n)
    return out


def _confirm_word(operation: str, endpoints: str) -> str:
    """The typed confirmation an execute needs (the same words the page asks for)."""
    if operation == "test_call":
        return "TEST"
    if operation == "guardrail_check":
        return "CHECK"
    if operation == "enable_tracking":
        return "ENABLE"
    if operation == "pause_legacy":
        return "PAUSE"  # the dialog names the endpoint; "PAUSE <endpoint>" (earlier versions) is still accepted
    return "RESUME"


def _window_since(span: timedelta) -> str:
    return (datetime.now(timezone.utc) - span).strftime("%Y-%m-%d %H:%M:%S")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _scan_meta(request: Request, scan_run_id: str = "") -> dict | None:
    """The scan the cut-over page reads: the given one, else the latest finished one (its workspace and window)."""
    cols = "run_id, workspace_id, status, readiness, days, CAST(finished_at AS STRING) AS finished_at"
    if scan_run_id:
        check_id(scan_run_id, "scan id")
        rows = query(request, f"SELECT {cols} FROM {table('ug_migration_scans')} WHERE run_id = :r", {"r": scan_run_id})
    else:
        rows = query(request, f"SELECT {cols} FROM {table('ug_migration_scans')} WHERE status = 'SUCCEEDED' "
                              "ORDER BY finished_at DESC LIMIT 1")
    return rows[0] if rows else None


def _scan_items(request: Request, scan: dict) -> tuple[list[dict], list[dict]]:
    """The plan rows and caller rows of a scan (decoded)."""
    items = _items(request, scan["run_id"])
    return [_parse_row(p) for p in items.get("plan", [])], [_parse_row(c) for c in items.get("caller", [])]


class CutoverRequest(BaseModel):
    operation: str = ""  # test_call | pause_legacy | enable_tracking | resume_legacy
    mode: str = "dry_run"  # dry_run | execute (resume runs as execute)
    endpoints: list[str] = Field([], max_length=500)
    services: list[str] = Field([], max_length=50)
    api_type: str = Field("", max_length=100)
    prompt: str = Field("", max_length=500)
    scan_run_id: str = ""
    rollback_of: str = ""  # resume: the pause run
    dry_run_id: str = ""  # execute: the successful dry run of this same selection
    confirm: str = ""
    traffic_window: str = "24h"  # pause: the window the traffic check covers (24h, 7d, 30d or scan)
    ack_traffic: bool = False  # pause: the endpoint had requests in that window, and callers will get errors


def _cutover_params(body: CutoverRequest) -> dict[str, str]:
    """Job parameters for a verify or cut-over run, checked the way the job checks them. Blank options take their defaults."""
    op = body.operation
    if op == "test_call":
        services = sorted(_unique(body.services))
        if not services:
            raise HTTPException(400, "Choose at least one Unity Gateway service to test")
        if len(services) > MAX_TEST_SERVICES:
            raise HTTPException(400, f"Test at most {MAX_TEST_SERVICES} services at a time (each gets one billable request)")
        bad = [s for s in services if not SERVICE_NAME_RE.fullmatch(s)]
        if bad:
            raise HTTPException(400, f"Service names look like catalog.schema.name, not {bad[0]!r}")
        api_type = (body.api_type or "").strip() or DEFAULT_API_TYPE
        if api_type not in apply_rules.TEST_API_TYPES:
            raise HTTPException(400, f"API type must be one of {', '.join(apply_rules.TEST_API_TYPES)}")
        prompt = (body.prompt or "").strip() or DEFAULT_PROMPT
        if len(prompt) > MAX_PROMPT_CHARS:
            raise HTTPException(400, f"The prompt is {len(prompt)} characters; the limit is {MAX_PROMPT_CHARS}")
        if any(ord(c) < 32 or ord(c) == 127 for c in prompt):
            raise HTTPException(400, "The prompt can't contain line breaks or tabs")
        return {"operation": op, "endpoints": "", "services": ",".join(services), "api_type": api_type,
                "prompt": prompt, "rollback_of": "", "force": "false"}
    if op == "guardrail_check":
        # Pairs "legacy_endpoint=catalog.schema.service", checked the way the job checks them.
        try:
            pairs = apply_rules.parse_guardrail_pairs(",".join(_unique(body.endpoints)))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"operation": op, "endpoints": ",".join(f"{l}={s}" for l, s in pairs), "services": "",
                "api_type": "", "prompt": "", "rollback_of": "", "force": "false"}
    endpoints = sorted(_unique(body.endpoints))
    bad = [e for e in endpoints if not NAME_RE.fullmatch(e)]
    if bad:
        raise HTTPException(400, f"That endpoint name isn't valid: {bad[0]!r}")
    if op == "pause_legacy" and len(endpoints) != 1:
        raise HTTPException(400, "Pause one endpoint per run")
    if op == "enable_tracking" and not endpoints:
        raise HTTPException(400, "Choose at least one endpoint to turn usage tracking on for")
    # Pause: the job refuses an endpoint with legacy requests in the last 24 hours unless force is set. The operator's
    # traffic acknowledgement is that override, sent on the dry run and the execute alike (force is in the fingerprint).
    force = op == "pause_legacy" and body.ack_traffic
    return {"operation": op, "endpoints": ",".join(endpoints), "services": "", "api_type": "", "prompt": "",
            "rollback_of": "", "force": str(force).lower()}


def _verify_cutover_dry_run(request: Request, dry_run_id: str, params: dict) -> None:
    """Execute follows a successful dry run of the same operation and settings (their legacy fingerprint)."""
    if not dry_run_id:
        raise HTTPException(400, "Run a dry run with these settings first")
    check_id(dry_run_id, "dry run id")
    rows = reconcile(query(request, f"SELECT mode, status, job_run_id, fingerprint, operation, "
                                    f"unix_timestamp(started_at) AS started_at "
                                    f"FROM {table('ug_migration_applies')} WHERE apply_id = :a", {"a": dry_run_id}))
    if not rows or rows[0]["mode"] != "dry_run" or (rows[0].get("operation") or "apply") != params["operation"]:
        raise HTTPException(400, "dry_run_id must be a dry run of this operation")
    _check_dry_run_unused(request, dry_run_id)
    if rows[0]["status"] != "SUCCEEDED":
        raise HTTPException(409, "That dry run didn't succeed. Run a dry run with these settings again.")
    _check_dry_run_age(rows[0])
    if not rows[0].get("fingerprint"):
        raise HTTPException(409, "Couldn't find the settings of that dry run. Run a dry run again.")
    if rows[0]["fingerprint"] != store.legacy_fingerprint(params):
        raise HTTPException(409, "The endpoints or options changed since that dry run; run a dry run with these settings")


def _start_resume(body: CutoverRequest, request: Request) -> dict:
    """Resume (rollback of a pause run): restores what the pause changed. Runs as execute; there is no dry run."""
    if body.mode != "execute":
        raise HTTPException(400, "Resume runs as execute. There is no dry run for a resume.")
    if body.confirm != "RESUME":
        raise HTTPException(400, "type RESUME to confirm")
    check_id(body.rollback_of, "pause run id")
    src = reconcile(query(request, f"SELECT mode, status, job_run_id, operation FROM {table('ug_migration_applies')} "
                                   "WHERE apply_id = :a", {"a": body.rollback_of}))
    if not src or src[0].get("operation") != "pause_legacy" or src[0]["mode"] != "execute":
        raise HTTPException(400, "Resume needs a pause run that was executed")
    if src[0]["status"] not in TERMINAL:
        raise HTTPException(409, "That pause run hasn't finished yet")
    if store.rollback_blocks(_rollback_rows(request, body.rollback_of), sp()):
        raise HTTPException(409, "That pause run has already been resumed, or a resume of it is running")
    params = {"operation": "resume_legacy", "endpoints": "", "services": "", "api_type": "", "prompt": "",
              "rollback_of": body.rollback_of, "force": "false",
              "target_workspace_id": run_workspace(request, body.rollback_of)}
    return _launch_cutover(request, "execute", params, scan_run_id="")


def _launch_cutover(request: Request, mode: str, params: dict, scan_run_id: str, dry_run_id: str = "") -> dict:
    run = active_run("apply", "a verify or cut-over run")
    if run:
        raise RunActive("A verify or cut-over run", run)
    apply_id = str(uuid.uuid4())
    gate = {"dry_run_id": dry_run_id} if dry_run_id else {}  # the job checks the dry run again itself
    job_run_id = run_job("apply", {"apply_id": apply_id, "results_schema": RESULTS_SCHEMA, "mode": mode,
                                   **params, **gate, "scan_run_id": scan_run_id, "requested_by": who(request)},
                         item_id=apply_id)
    return {"apply_id": apply_id, "job_run_id": job_run_id, "operation": params["operation"], "mode": mode}


@app.post("/api/cutover")
def start_cutover(body: CutoverRequest, request: Request) -> dict:
    """Start a verify or cut-over run: test call, pause a legacy endpoint, enable usage tracking, or resume a pause.

    Operators only. Dry run first; execute needs the typed word and a successful dry run of the same settings.
    Another verify or cut-over run (or apply run) running gives 409 with the job link."""
    require_operator(request)
    op = body.operation
    if op not in CUTOVER_OPERATIONS:
        raise HTTPException(400, "operation must be test_call, guardrail_check, pause_legacy, enable_tracking or "
                                 "resume_legacy")
    if body.scan_run_id:
        check_id(body.scan_run_id, "scan id")
    if op == "resume_legacy":
        return _start_resume(body, request)
    if body.mode not in ("dry_run", "execute"):
        raise HTTPException(400, "mode must be dry_run or execute")
    if body.scan_run_id:
        check_id(body.scan_run_id, "scan id")
    params = _cutover_params(body)
    params["target_workspace_id"] = scan_workspace(request, body.scan_run_id)  # the scan's workspace
    if op == "test_call":  # the job checks this too
        listed = [x["name"] for x in cutover_services(request, body.scan_run_id).get("services", [])]
        bad = apply_rules.untestable_services(params["services"].split(","), listed, [])
        if bad:
            raise HTTPException(400, apply_rules.UNTESTABLE.format(names=", ".join(bad)) + ".")
    if body.mode == "execute":
        word = _confirm_word(op, params["endpoints"])
        accepted = {word} | ({f"PAUSE {params['endpoints']}"} if op == "pause_legacy" else set())
        if body.confirm.strip() not in accepted:
            raise HTTPException(400, f"type {word} to confirm")
    if body.mode == "execute":
        _verify_cutover_dry_run(request, body.dry_run_id, params)
    if op == "pause_legacy":
        _pause_traffic_gate(request, body, params["endpoints"])
    out = _launch_cutover(request, body.mode, params, scan_run_id=body.scan_run_id,
                          dry_run_id=body.dry_run_id if body.mode == "execute" else "")
    if op in ("test_call", "guardrail_check"):
        out["runs_as"] = job_identity("apply")
    return out


def _pause_traffic_gate(request: Request, body: CutoverRequest, endpoint: str) -> None:
    """Pause only after the traffic check, on the server too (the page has the same gate). The endpoint's legacy
    requests in the chosen window must be zero, or the operator confirms (ack_traffic) that callers will get errors.
    Traffic that can't be read (missing table, no access, query error) refuses the pause: unknown isn't zero."""
    if body.traffic_window != "scan" and body.traffic_window not in TRAFFIC_WINDOWS:
        raise HTTPException(400, "traffic_window must be 24h, 7d, 30d or scan")
    scan = _scan_meta(request, body.scan_run_id)
    if not scan:
        raise HTTPException(409, "Pause checks the endpoint's traffic against a finished scan. Run a scan first.")
    plan, _ = _scan_items(request, scan)
    kind = next((p.get("kind") for p in plan if p.get("legacy_endpoint") == endpoint
                 and p.get("kind") in NOT_PAUSABLE_KINDS), None)
    if kind:
        why = CUSTOM_PAUSE_REFUSAL if kind == "custom_model" else apply_rules.PT_PAUSE_REFUSAL
        raise HTTPException(409, f"{endpoint} can't be paused: {why}.")
    try:
        traffic = _endpoint_traffic(request, scan, body.traffic_window, only=[endpoint])
    except HTTPException as e:
        raise HTTPException(409, f"Couldn't check {endpoint}'s legacy traffic, so it wasn't paused. {e.detail}")
    e = next((t for t in traffic["endpoints"] if t["endpoint_name"] == endpoint), None)
    if e is None:
        raise HTTPException(409, f"{endpoint} isn't a legacy endpoint in that scan's plan. Scan again.")
    if e["requests"] and not body.ack_traffic:
        raise HTTPException(409, f"{endpoint} had {e['requests']} legacy requests since {traffic['since']} UTC. Callers "
                                 "still on it get errors once it's paused. Move them first, or confirm that you "
                                 "accept this.")
    unmatched = next((t["requests"] for t in traffic["endpoints"] if t["endpoint_name"] == store.UNATTRIBUTED), 0)
    if unmatched and not body.ack_traffic:
        raise HTTPException(409, f"{unmatched} legacy requests since {traffic['since']} UTC couldn't be matched to an "
                                 f"endpoint, so some could be calling {endpoint}. Check them first, or confirm that "
                                 "callers may get errors.")


def job_identity(kind: str) -> str:
    """Who a job's runs run as: its run_as user or service principal, else its owner. Cached for a few minutes."""
    hit = _job_identities.get(kind)
    if hit and hit[0] > time.time():
        return hit[1]
    name = ""
    job_id = JOBS.get(kind)
    if job_id:
        try:
            job = sp().jobs.get(int(job_id))
            run_as = getattr(job.settings, "run_as", None) if job.settings else None
            name = (getattr(run_as, "service_principal_name", None) or getattr(run_as, "user_name", None)
                    or getattr(job, "run_as_user_name", None) or getattr(job, "creator_user_name", None) or "")
        except Exception:
            name = ""
    name = str(name) if isinstance(name, str) else ""
    _job_identities[kind] = (time.time() + IDENTITY_TTL_S, name)
    return name


@app.get("/api/cutover/runs")
def list_cutover(request: Request, workspace_id: str = "") -> list[dict]:
    """Recent verify and cut-over runs (every operation except apply). resumed: a pause run that a resume has undone.
    workspace_id (central mode): only runs that acted on that workspace."""
    rows = reconcile(query(request, f"""
        SELECT apply_id, job_run_id, requested_by, operation, mode, endpoints, services, api_type, rollback_of, status,
               workspace_id,
               summary, error, CAST(started_at AS STRING) AS started_at, CAST(finished_at AS STRING) AS finished_at
        FROM {table('ug_migration_applies')} WHERE {CUTOVER_RUNS} ORDER BY started_at DESC LIMIT 50"""))
    done = {r["rollback_of"] for r in _rollback_rows(request) if store.rollback_done(r.get("status"), r.get("summary"))}
    for r in rows:
        r["resumed"] = r.get("operation") == "pause_legacy" and r.get("apply_id") in done
    return _for_workspace(rows, workspace_id)


def _tracking_status(request: Request) -> dict:
    """Usage tracking per endpoint from the latest successful enable-tracking dry run: its rows say whether it's on."""
    runs = query(request, f"SELECT apply_id, CAST(started_at AS STRING) AS started_at FROM {table('ug_migration_applies')} "
                          "WHERE operation = 'enable_tracking' AND mode = 'dry_run' AND status = 'SUCCEEDED' "
                          "ORDER BY started_at DESC LIMIT 1")
    if not runs:
        return {"states": {}, "checked_at": None}
    items = query(request, f"SELECT payload FROM {table('ug_migration_apply_items')} WHERE apply_id = :a ORDER BY seq",
                  {"a": runs[0]["apply_id"]})
    states: dict[str, str] = {}
    for i in items:
        row = _load(i["payload"])
        if row.get("type") != "serving_endpoint":
            continue
        if row.get("action") == "would_enable_tracking":
            states[str(row.get("name"))] = "off"
        elif row.get("action") == "already_enabled":
            states[str(row.get("name"))] = "on"
    return {"states": states, "checked_at": str(runs[0].get("started_at") or "")[:16]}


@app.get("/api/cutover/traffic")
def cutover_traffic(request: Request, window: str = "24h", scan_run_id: str = "") -> dict:
    """Legacy requests per endpoint since the window (runbook README step 4), with callers and caller class.

    Every legacy endpoint (v1 and v2) of the scan's plan is listed, including those with no requests. window is 24h,
    7d, 30d, or scan (the scan's own window). Reads as the signed-in user; the caller class comes from the scan."""
    if window != "scan" and window not in TRAFFIC_WINDOWS:
        raise HTTPException(400, "window must be 24h, 7d, 30d or scan")
    scan = _scan_meta(request, scan_run_id)
    if not scan:
        return {"scan_run_id": None, "window": window, "since": None, "total_requests": 0, "endpoints": []}
    try:
        return _endpoint_traffic(request, scan, window)
    except TableMissing as e:  # unknown, never "no requests": the page shows the reason and pause stays off
        return {"scan_run_id": scan["run_id"], "workspace_id": scan.get("workspace_id"), "window": window,
                "since": None, "checked_at": _utc_now(), "total_requests": None, "traffic_error": e.detail,
                "endpoints": []}


def _endpoint_traffic(request: Request, scan: dict, window: str, only: list[str] | None = None) -> dict:
    """Legacy requests per endpoint of the scan's plan since the window (all of them, or only those named)."""
    ws = str(scan.get("workspace_id") or "")
    if not ws:
        raise HTTPException(409, "That scan doesn't record its workspace. Scan again to check traffic.")
    span = TRAFFIC_WINDOWS[window] if window != "scan" else timedelta(days=_num(scan.get("days")) or 30)
    since = _window_since(span)
    plan, callers = _scan_items(request, scan)
    legacy = [p for p in plan if p.get("legacy_endpoint") and p.get("kind") not in NOT_LEGACY_KINDS
              and (only is None or p["legacy_endpoint"] in only)]
    names = sorted({p["legacy_endpoint"] for p in legacy})
    kinds = {p["legacy_endpoint"]: p.get("kind") for p in legacy}
    classes = {(c.get("endpoint_name"), c.get("requester")): c.get("caller_class") for c in callers}
    by = {n: {"endpoint_name": n, "kind": kinds[n], "requests": 0, "failed": 0, "tokens": 0, "v2_requests": 0,
              "v2_failed": 0, "v2_tokens": 0, "last_request": None, "callers": []} for n in names}
    if names:
        try:
            sql, params = store.legacy_traffic_since(names, since, ws)
        except ValueError as e:
            raise HTTPException(400, str(e))
        for r in query(request, sql, params, missing_ok=False):
            name = r.get("endpoint_name")
            if name == store.UNATTRIBUTED and name not in by:
                # v1 requests with no served_entities match: they could be any endpoint's, so they count as possible
                # traffic for each pause (fail closed), and show as their own row.
                by[name] = {"endpoint_name": name, "kind": "unattributed", "requests": 0, "failed": 0, "tokens": 0,
                            "v2_requests": 0, "v2_failed": 0, "v2_tokens": 0, "last_request": None, "callers": []}
            e = by.get(name)
            if e is None:
                continue
            req, failed, tokens = _num(r.get("requests")) or 0, _num(r.get("failed")) or 0, _num(r.get("tokens")) or 0
            e["requests"] += req
            e["failed"] += failed
            e["tokens"] += tokens
            if r.get("source") == "v2":
                e["v2_requests"] += req
                e["v2_failed"] += failed
                e["v2_tokens"] += tokens
            if r.get("last_request") and (not e["last_request"] or r["last_request"] > e["last_request"]):
                e["last_request"] = r["last_request"]
            e["callers"].append({"source": r.get("source"), "requester": r.get("requester"), "requests": req,
                                 "failed": failed, "tokens": tokens, "last_request": r.get("last_request"),
                                 "caller_class": classes.get((r.get("endpoint_name"), r.get("requester")))})
    endpoints = sorted(by.values(), key=lambda e: (-e["requests"], e["endpoint_name"]))
    for e in endpoints:
        e["callers"].sort(key=lambda c: -c["requests"])
        e["status"] = "requests" if e["requests"] else "no_requests"
        e["v2_failing"] = v2_mostly_failing(e["v2_requests"], e["v2_failed"])
    return {"scan_run_id": scan["run_id"], "workspace_id": ws, "window": window, "since": since,
            "checked_at": _utc_now(), "total_requests": sum(e["requests"] for e in endpoints), "endpoints": endpoints}


@app.get("/api/cutover/endpoints")
def cutover_endpoints(request: Request, scan_run_id: str = "") -> dict:
    """Legacy endpoints the cut-over steps can act on (plan kinds that are v1 serving endpoints), with tracking state."""
    scan = _scan_meta(request, scan_run_id)
    if not scan:
        return {"scan_run_id": None, "endpoints": [], "tracking_checked": None}
    plan, _ = _scan_items(request, scan)
    tracking = _tracking_status(request)
    seen: dict[str, dict] = {}
    for p in plan:
        name = p.get("legacy_endpoint")
        if not name or p.get("kind") in NOT_OPERABLE_KINDS or name in seen:
            continue
        seen[name] = {"endpoint": name, "kind": p.get("kind"), "plan": p.get("action"),
                      "trackable": p.get("kind") not in NOT_TRACKABLE_KINDS,
                      "pausable": p.get("kind") not in NOT_PAUSABLE_KINDS,
                      "tracking": tracking["states"].get(name, "not checked")}
    return {"scan_run_id": scan["run_id"], "endpoints": sorted(seen.values(), key=lambda e: e["endpoint"]),
            "tracking_checked": tracking["checked_at"]}


@app.get("/api/cutover/services")
def cutover_services(request: Request, scan_run_id: str = "") -> dict:
    """Unity Gateway services the scan plans to create or use (their targets). The user's token can't list model
    services, so the choice comes from the scan; other three-part names can be typed in."""
    scan = _scan_meta(request, scan_run_id)
    if not scan:
        return {"scan_run_id": None, "source": "scan plan", "services": []}
    plan, _ = _scan_items(request, scan)
    created = _created_services(request, norm_workspace(scan.get("workspace_id")))
    seen: dict[str, dict] = {}
    for p in plan:
        t = str(p.get("target_service") or "")
        if t and SERVICE_NAME_RE.fullmatch(t) and t not in seen:
            seen[t] = {"name": t, "from": p.get("legacy_endpoint"), "plan": p.get("action"),
                       # system.ai services are provided by Databricks, so they exist whether or not the scan could check.
                       "exists": p.get("target_status") == "exists" or t.lower() in created
                                 or t.lower().startswith("system.ai.") or p.get("action") == "use_system_ai"}
    # Services an apply created under another target than the scan's (the target is chosen in Apply).
    for name, src in created.items():
        if not any(k.lower() == name for k in seen):
            seen[name] = {"name": name, "from": src, "plan": "create_model_service", "exists": True}
    return {"scan_run_id": scan["run_id"], "source": "scan plan and apply runs",
            "services": sorted(seen.values(), key=lambda s: (not s["exists"], s["name"]))}


@app.get("/api/cutover/guardrail-pairs")
def cutover_guardrail_pairs(request: Request, scan_run_id: str = "") -> dict:
    """Legacy endpoints whose plan says their guardrails aren't carried over, each with the Unity Gateway service it
    was migrated to (created by an apply run, in any target schema) when there is one."""
    scan = _scan_meta(request, scan_run_id)
    if not scan:
        return {"scan_run_id": None, "pairs": []}
    plan, _ = _scan_items(request, scan)
    created = _created_services(request, norm_workspace(scan.get("workspace_id")))
    out = []
    for p in plan:
        notes = [str(n).removeprefix(planner.BLOCKING_PREFIX) for n in (p.get("needs_human") or [])]
        g = next((n for n in notes if n.startswith("guardrails")), None)
        if not g:
            continue
        consequence = g.split(":", 1)[1].split(" Suggested:")[0].strip() if ":" in g else g
        target = str(p.get("target_service") or "")
        leaf = target.rsplit(".", 1)[-1].lower()
        made = sorted(n for n in created if n.rsplit(".", 1)[-1] == leaf)
        out.append({"legacy_endpoint": p.get("legacy_endpoint"), "service": made[0] if made else target,
                    "service_exists": bool(made), "consequence": consequence})
    return {"scan_run_id": scan["run_id"], "pairs": sorted(out, key=lambda x: str(x["legacy_endpoint"]))}


def _created_services(request: Request, workspace: str | None = None) -> dict[str, str | None]:
    """Model services that an apply execute created (or found existing) and no rollback deleted since, lower-cased
    name -> legacy endpoint. Read from the results tables, as of the last run that touched each service.
    workspace (central mode, as norm_workspace gives it): only runs that acted on that workspace."""
    rows = query(request, f"""
        SELECT a.mode, a.started_at, a.workspace_id, i.payload
        FROM {table('ug_migration_apply_items')} i JOIN {table('ug_migration_applies')} a ON a.apply_id = i.apply_id
        WHERE a.mode IN ('execute', 'rollback') AND (a.operation IS NULL OR a.operation = 'apply')
          AND get_json_object(i.payload, '$.type') = 'model_service'
          AND get_json_object(i.payload, '$.action') IN ('created', 'exists', 'deleted')
        ORDER BY a.started_at, i.seq""")
    state: dict[str, str | None] = {}
    for r in rows:
        if workspace is not None and norm_workspace(r.get("workspace_id")) != workspace:
            continue
        item = _load(r.get("payload"))
        name = str(item.get("name") or "").lower()
        if not name:
            continue
        if item.get("action") == "deleted":
            state.pop(name, None)
        else:
            state[name] = item.get("legacy_endpoint") or item.get("from")
    return state


def _usage_rows(request: Request, service: str, window: str) -> tuple[str, list[dict]]:
    if window not in TRAFFIC_WINDOWS:
        raise HTTPException(400, "window must be 24h, 7d or 30d")
    since = _window_since(TRAFFIC_WINDOWS[window])
    try:
        sql, params = store.ug_usage_summary(service, since)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return since, query(request, sql, params, missing_ok=False)


@app.get("/api/usage/summary")
def usage_summary(request: Request, window: str = "7d", service: str = "") -> dict:
    """Unity Gateway (Model Service) usage since the window, per service, workspace, requester, API type, destination."""
    since, rows = _usage_rows(request, service, window)
    return {"window": window, "since": since, "service": service or None, "rows": rows}


@app.get("/api/usage/summary/export")
def export_usage(request: Request, window: str = "7d", service: str = "") -> Response:
    _, rows = _usage_rows(request, service, window)
    return _csv_response(rows[:EXPORT_ROW_LIMIT], f"ug_usage_{window}.csv", USAGE_COLUMNS,
                         truncated=len(rows) > EXPORT_ROW_LIMIT)


@app.get("/api/usage/request")
def usage_request(request_id: str, request: Request) -> dict:
    """Usage rows for one request id (runbook cell 14). Usage takes 20 to 30 minutes to appear, so none yet is expected."""
    try:
        sql, params = store.ug_request_lookup(request_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"request_id": request_id, "rows": query(request, sql, params, missing_ok=False)}


@app.get("/api/cutover/{run_id}")
def cutover_detail(run_id: str, request: Request):
    """A verify or cut-over run: 200 with its results; 202 while it is starting; 404 for an unknown run."""
    check_id(run_id, "run id")
    meta = query(request, f"""
        SELECT apply_id, job_run_id, requested_by, operation, mode, endpoints, services, api_type, rollback_of, status,
               summary, error, CAST(started_at AS STRING) AS started_at, CAST(finished_at AS STRING) AS finished_at,
               workspace_id, workspace_url
        FROM {table('ug_migration_applies')} WHERE apply_id = :a AND {CUTOVER_RUNS}""", {"a": run_id})
    if not meta:
        job_run_id = starting_job(run_id)
        if job_run_id:
            return starting_response("run_id", run_id, job_run_id)
        raise HTTPException(404, "not found")
    require_run_access(request, meta[0].get("requested_by"))
    items = query(request, f"SELECT seq, payload FROM {table('ug_migration_apply_items')} "
                           "WHERE apply_id = :a ORDER BY seq", {"a": run_id})
    rollbacks = _rollback_rows(request, run_id)
    out = reconcile(meta)[0]
    out["resumed"] = out.get("operation") == "pause_legacy" and any(
        store.rollback_done(r.get("status"), r.get("summary")) for r in rollbacks)
    return {"meta": out, "items": [_load(i["payload"]) for i in items],
            "rollbacks": [{"apply_id": r["apply_id"], "status": r["status"]} for r in rollbacks]}


@app.get("/api/cutover/{run_id}/export")
def export_cutover(run_id: str, request: Request) -> Response:
    check_id(run_id, "run id")
    require_run_access(request, _run_owner(request, "apply", run_id))
    rows = query(request, f"SELECT payload FROM {table('ug_migration_apply_items')} WHERE apply_id = :a "
                          f"ORDER BY seq LIMIT {EXPORT_ROW_LIMIT}", {"a": run_id})
    items = [_load(r["payload"]) for r in rows]
    lead = ["type", "name", "action", "reason", "api_type", "path", "http_status", "request_id", "latency_ms",
            "reply_excerpt", "time", "execute"]
    cols = lead + sorted({k for i in items for k in i} - set(lead))
    return _csv_response(items, f"ug_migration_cutover_{run_id[:8]}.csv", cols, truncated=len(items) >= EXPORT_ROW_LIMIT)


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
    require_run_access(request, _run_owner(request, "scan", run_id))
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
    require_run_access(request, _run_owner(request, "apply", apply_id))
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
