# Databricks notebook source
# MAGIC %md
# MAGIC # Unity Gateway migration: apply / rollback / cut-over (app job)
# MAGIC Runs one operation for the endpoints or services chosen in the app and stores every result in
# MAGIC `<results_schema>.ug_migration_applies` and `ug_migration_apply_items`.
# MAGIC
# MAGIC `operation` (default `apply`) and `mode`:
# MAGIC
# MAGIC - `apply`, `mode = dry_run`: shows what would be created; changes nothing (default).
# MAGIC - `apply`, `mode = execute`: creates provider services, model services and grants.
# MAGIC - `apply`, `mode = rollback_dry_run`: lists what a rollback of the execute run `rollback_of` would delete; changes
# MAGIC   nothing.
# MAGIC - `apply`, `mode = rollback`: deletes the objects an earlier execute run created (`rollback_of`). Needs `dry_run_id`:
# MAGIC   a finished `rollback_dry_run` of the same execute run, by the same `requested_by`, in the last 24 hours, used once.
# MAGIC - `test_call`, `mode = dry_run | execute`: one small request per Model Service in `services` (`api_type`,
# MAGIC   `prompt`). Dry run only validates the services; execute sends one billable request to each.
# MAGIC - `guardrail_check`, `mode = dry_run | execute`: for each `legacy=catalog.schema.service` pair in `endpoints`,
# MAGIC   sends the same harmless probes (a no-PII control, a fake email) to both and says whether protection was lost.
# MAGIC - `pause_legacy`, `mode = dry_run | execute`: sets the endpoint rate limit of the legacy endpoints in
# MAGIC   `endpoints` to 0 calls a minute, re-sending their other AI Gateway settings unchanged.
# MAGIC - `enable_tracking`, `mode = dry_run | execute`: turns on usage tracking for `endpoints` (blank = every
# MAGIC   non-custom endpoint).
# MAGIC - `resume_legacy`, `mode = dry_run | execute | rollback`: restores what the pause run `rollback_of` changed.
# MAGIC   `mode = rollback` on a pause run does the same.
# MAGIC
# MAGIC Every execute except a resume needs `dry_run_id`: the apply_id of a successful dry run
# MAGIC of the same operation and settings, by the same `requested_by`, started in the last 24 hours. The job checks
# MAGIC this itself, so starting it directly can't skip the dry run. A pause also refuses an endpoint with legacy
# MAGIC requests in the last 24 hours unless `force` is `true` (the person confirms those callers will get errors).
# MAGIC
# MAGIC Job-level settings the installer sets on the job definition (the app must not pass them):
# MAGIC `secret_schemas` (comma list of catalog.schema allowed for UC secrets) and `allow_secret_read_enabled`,
# MAGIC and for central mode `central_workspaces`, `central_client_id` and `central_secret`.
# MAGIC
# MAGIC Central mode: `target_workspace_id` names the workspace the run acts on (blank = this one). It must be in
# MAGIC `central_workspaces`; the job signs in to it as the service principal (OAuth secret in `central_secret`) and
# MAGIC every change, read and test request goes to that workspace. An apply must use a scan of that workspace. A
# MAGIC rollback or resume acts on the workspace of the run it undoes, whatever the request says.
# MAGIC
# MAGIC Prototype from Databricks Shared Technical Services, provided as is.

# COMMAND ----------

# MAGIC %pip install --quiet "databricks-sdk==0.158.0"
# MAGIC %restart_python

# COMMAND ----------

for name, default in (("apply_id", ""), ("job_run_id", ""), ("results_schema", ""), ("mode", "dry_run"), ("endpoints", ""),
                      ("target_catalog", ""), ("target_schema", ""), ("uc_secret_map", ""),
                      ("allow_secret_read", "false"), ("create_uc_secrets", "false"), ("grants", "false"), ("rollback_of", ""),
                      ("scan_run_id", ""), ("requested_by", ""), ("ack_guardrails", "false"), ("smoke_test", "false"),
                      ("force", "false"), ("secret_schemas", ""), ("allow_secret_read_enabled", "false"),
                      ("operation", "apply"), ("api_type", ""), ("prompt", "Reply with: ok"), ("services", ""),
                      ("dry_run_id", ""), ("target_workspace_id", ""), ("central_workspaces", ""),
                      ("central_client_id", ""), ("central_secret", "")):
    dbutils.widgets.text(name, default)

# COMMAND ----------

import json
import os
import re
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

from databricks.sdk import WorkspaceClient

ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
here = os.path.dirname(ctx.notebookPath().get())
root = "/Workspace" + here.rsplit("/notebook", 1)[0]
sys.path.insert(0, root)
LOG_DIR = os.path.join(os.path.dirname(root), "apply_logs")  # next to the bundle files, survives redeploys
import ug_migration_apply as apply_mod
import ug_migration_planner as planner
import ug_migration_store as store

g = dbutils.widgets.get


def flag(name: str) -> bool:
    v = g(name).strip().lower()
    if v not in ("true", "false"):
        raise ValueError(f"{name} must be true or false, not {v!r}")
    return v == "true"


schema, mode = g("results_schema"), g("mode")
operation = g("operation").strip() or "apply"
if operation not in apply_mod.OPERATIONS:
    raise ValueError(f"operation must be one of {', '.join(apply_mod.OPERATIONS)}, not {operation!r}")
if mode not in ("dry_run", "execute", "rollback", "rollback_dry_run"):
    raise ValueError(f"mode must be dry_run, execute, rollback or rollback_dry_run, not {mode!r}")
if operation not in ("apply", "resume_legacy") and mode == "rollback":
    raise ValueError(f"{operation} runs as dry_run or execute; rollback is for apply runs and pause runs")
if operation != "apply" and mode == "rollback_dry_run":
    raise ValueError("rollback_dry_run is for apply runs; a pause is resumed with its own dry run")
ROLLING_BACK = mode in ("rollback", "rollback_dry_run")
apply_id = g("apply_id") or str(uuid.uuid4())
ID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
for v in (apply_id, g("rollback_of"), g("scan_run_id"), g("dry_run_id")):
    if v and not re.fullmatch(ID_RE, v):
        raise ValueError(f"bad run id {v!r}")
endpoints = [e.strip() for e in g("endpoints").split(",") if e.strip()]
NAME = r"[A-Za-z0-9_\-]+"
# The app validates all of this too; the job re-checks so a direct run can't do more than the app allows.
if not re.fullmatch(rf"{NAME}\.{NAME}", schema):
    raise ValueError("results_schema must be catalog.schema")
services, api_type, prompt = [], "", ""
if operation == "apply":
    if not ROLLING_BACK:
        bad = [e for e in endpoints if not re.fullmatch(NAME, e)]
        if bad or not re.fullmatch(NAME, g("target_catalog")) or not re.fullmatch(NAME, g("target_schema")):
            raise ValueError(f"bad endpoint, target catalog or target schema name {bad}")
elif operation == "guardrail_check":
    pairs = apply_mod.parse_guardrail_pairs(g("endpoints"))
    endpoints = [f"{l}={s}" for l, s in pairs]
elif operation == "test_call":
    services = apply_mod.parse_services(g("services"))
    api_type = apply_mod.resolve_api_type(g("api_type"))
    prompt = apply_mod.resolve_prompt(g("prompt"))
else:
    endpoints = apply_mod.parse_endpoints(g("endpoints"))
    if operation == "pause_legacy" and not endpoints:
        raise ValueError("pause_legacy needs at least one endpoint in endpoints (it never pauses everything)")
job_run_id = dbutils.widgets.get("job_run_id")  # filled by the job with {{job.run_id}}
hub_client = WorkspaceClient()  # the hub: job status, locks and the results tables stay here
_hub = {}


def hub_id() -> str:
    if "id" not in _hub:
        _hub["id"] = str(planner.workspace_id_of(hub_client))  # only asked when a target workspace is named
    return _hub["id"]


def norm_ws(v) -> str:
    """A target workspace as runs store it in fingerprints: blank for the hub, else its ID."""
    v = str(v or "").strip()
    if v and not re.fullmatch(r"[0-9]{1,20}", v):
        raise ValueError(f"bad workspace id {v!r}")
    return "" if (not v or v == hub_id()) else v


target_req = norm_ws(g("target_workspace_id"))

# COMMAND ----------

store.ensure_tables(spark, schema)
if store.run_exists(spark, schema, "ug_migration_applies", "apply_id", apply_id):
    raise ValueError(f"apply_id {apply_id} already exists; each run needs a new id")
if ROLLING_BACK and operation == "apply":
    # A rollback of a pause run is a resume (rollback of a pause = resume).
    src_for_kind = store.apply_run(spark, schema, g("rollback_of")) if g("rollback_of") else None
    if src_for_kind and src_for_kind["operation"] == "pause_legacy":
        if mode == "rollback_dry_run":
            raise ValueError("that is a pause run: resume it from Verify & cut over")
        operation = "resume_legacy"
if operation == "resume_legacy" or (operation == "apply" and ROLLING_BACK):
    # Undo acts on the workspace the original run changed, never on one the request names.
    undo_src = store.apply_run(spark, schema, g("rollback_of")) if g("rollback_of") else None
    src_ws = norm_ws((undo_src or {}).get("workspace_id"))
    if g("target_workspace_id").strip() and target_req != src_ws:
        raise ValueError("target_workspace_id doesn't match the workspace of the run being undone")
    target_req = src_ws
elif g("scan_run_id"):  # every operation driven by a scan acts on that scan's workspace
    found_scan = spark.sql(f"SELECT workspace_id FROM {store.q(schema)}.ug_migration_scans "
                           f"WHERE run_id = '{g('scan_run_id')}'").collect()  # scan_run_id matched ID_RE above
    raw_ws = str((found_scan[0]["workspace_id"] if found_scan else "") or "").strip()
    if g("central_workspaces").strip() and not raw_ws:  # fail closed: unknown is never taken to be the hub
        raise ValueError(f"scan {g('scan_run_id')} doesn't record its workspace (or wasn't found), so it can't drive "
                         "a change in central mode: scan the workspace again")
    scan_ws = norm_ws(raw_ws)
    if scan_ws != target_req:
        raise ValueError(f"scan {g('scan_run_id')} is of workspace {scan_ws or 'the hub'}, not "
                         f"{target_req or 'the hub'}: use a scan of the workspace it changes")
if operation == "enable_tracking":  # only trackable endpoints of the scan's plan (the app checks this too)
    if not g("scan_run_id"):
        raise ValueError("usage tracking needs the scan whose plan lists the endpoints")
    _untrackable = apply_mod.untrackable_endpoints(endpoints, store.plan_kinds(spark, schema, g("scan_run_id")))
    if _untrackable:
        raise ValueError(apply_mod.UNTRACKABLE.format(names=", ".join(_untrackable)))
if operation == "test_call":  # only services the toolkit planned or created, or system.ai (the app checks this too)
    _targets, _created = store.test_call_candidates(spark, schema, g("scan_run_id"))
    _bad = apply_mod.untestable_services(services, _targets,
                                         [n for n, ws in _created.items() if norm_ws(ws) == target_req])
    if _bad:
        raise ValueError(apply_mod.UNTESTABLE.format(names=", ".join(_bad)))
# The selection and options as this run received them. A dry run keeps this on its row; an execute compares it
# with the dry run's row (the app does), so the check doesn't depend on the job's stored parameter values.
# Apply rollbacks have no fingerprint, as before.
fingerprint = None if (operation == "apply" and ROLLING_BACK) else store.run_fingerprint({
    "operation": operation, "scan_run_id": g("scan_run_id"), "endpoints": g("endpoints"),
    "target_catalog": g("target_catalog"), "target_schema": g("target_schema"), "uc_secret_map": g("uc_secret_map"),
    "allow_secret_read": g("allow_secret_read"), "grants": g("grants"), "ack_guardrails": g("ack_guardrails"),
    "create_uc_secrets": g("create_uc_secrets"), "services": g("services"), "api_type": g("api_type"), "prompt": g("prompt"), "rollback_of": g("rollback_of"),
    "force": g("force"), "target_workspace_id": target_req})
def dry_run_row(columns: str) -> dict | None:
    """The dry run's row in the applies table. The id is a bound parameter, not text in the SQL, so the check on
    the id above isn't the only thing between a widget value and the query. columns is a fixed list from this file;
    started_at comes as epoch seconds, so the session time zone doesn't matter."""
    found = spark.sql(f"SELECT {columns}, unix_timestamp(started_at) AS started_at "
                      f"FROM {store.q(schema)}.ug_migration_applies WHERE apply_id = :id",
                      args={"id": g("dry_run_id")}).collect()
    return found[0].asDict() if found else None


# Execute follows a successful, recent dry run of the same settings (the app checks this too; the job doesn't rely
# on it). Checked before this run's row is written, so a refused execute leaves no RUNNING row behind.
if mode == "execute" and operation in apply_mod.DRY_RUN_GATED:
    dry = None
    if g("dry_run_id"):
        dry = dry_run_row("mode, operation, status, fingerprint, scan_run_id, requested_by")
    used_by = None
    if dry is not None:
        used_sql, used_args = store.dry_run_used(schema, g("dry_run_id"))
        used = spark.sql(used_sql, args=used_args).collect()
        used_by = used[0].asDict().get("apply_id") if used else None
    problem = apply_mod.dry_run_gate_error(dry, operation, fingerprint, g("scan_run_id"), g("requested_by"),
                                           used_by=used_by)
    if problem:
        raise ValueError(f"execute refused: {problem}")
# A rollback of an apply run, and its dry run, say who is rolling back. The check below compares the dry run's
# requester with the rollback's, which only means something when both are set. requested_by is a job parameter, so
# this is a consistency check, not an authorization control: who may start the job is the job's permissions.
if ROLLING_BACK and operation == "apply" and not g("requested_by").strip():
    raise ValueError("a rollback and its dry run need requested_by (who is rolling back): the app and the "
                     "installer set it")
# An apply rollback follows a finished, recent rollback dry run of the same execute run (the app checks this too).
if mode == "rollback" and operation == "apply":
    rb_dry, rb_used = None, None
    if g("dry_run_id"):
        rb_dry = dry_run_row("mode, operation, status, summary, rollback_of, requested_by")
        if rb_dry is not None:
            used_sql, used_args = store.dry_run_used(schema, g("dry_run_id"))
            used = spark.sql(used_sql, args=used_args).collect()
            rb_used = used[0].asDict().get("apply_id") if used else None
    problem = apply_mod.rollback_gate_error(rb_dry, g("rollback_of"), g("requested_by"), used_by=rb_used)
    if problem:
        raise ValueError(f"rollback refused: {problem}")
# A resume that executes is stored as a rollback row, so the rollback rules (already rolled back, protection) apply.
stored_mode = "rollback" if (operation == "resume_legacy" and mode == "execute") else mode
store.upsert(spark, schema, "ug_migration_applies", store.APPLY_COLUMNS, "apply_id", {
    "apply_id": apply_id, "job_run_id": str(job_run_id), "requested_by": g("requested_by"),
    "scan_run_id": g("scan_run_id"), "mode": stored_mode, "operation": operation,
    "endpoints": ",".join(endpoints), "services": ",".join(services), "api_type": api_type,
    "target_catalog": g("target_catalog"), "target_schema": g("target_schema"), "rollback_of": g("rollback_of"),
    "dry_run_id": g("dry_run_id") if mode in ("execute", "rollback") else "", "workspace_id": target_req,
    "toolkit_version": planner.__version__, "fingerprint": fingerprint, "status": "RUNNING",
    "started_at": store.now()})

# COMMAND ----------

# Everything from here on runs inside one guarded block: any failure (bad widget, parse error, cancellation)
# marks this row FAILED and keeps whatever results were already written to the durable log.
results: list[dict] = []
durable = None
log_path = None


def _read_partial(path):
    out = []
    if path and os.path.exists(path):
        for line in open(path):
            try:
                if line.strip():
                    out.append(json.loads(line))
            except ValueError:
                continue  # a torn last line from a killed run
    return out


def _record_failure(e: BaseException) -> None:
    partial = list(results) or _read_partial(log_path)
    try:
        if partial:
            store.write_apply_items(spark, schema, apply_id, [apply_mod._mask(r) for r in partial])
    except BaseException as werr:
        print(f"could not store partial results: {werr}")
    try:
        store.upsert(spark, schema, "ug_migration_applies", store.APPLY_COLUMNS, "apply_id",
                     {"apply_id": apply_id, "status": "FAILED", "error": (str(e) or type(e).__name__)[:2000],
                      "finished_at": store.now()})
    except BaseException as uerr:
        print(f"could not mark {apply_id} FAILED: {uerr}")


def _check_no_other_legacy_write(w) -> None:
    """Best-effort lock for pause, enable-tracking and resume runs: one of them at a time in this results schema."""
    busy = store.running_legacy(spark, hub_client, schema, apply_id)
    if busy:
        raise ValueError(f"another pause, resume or tracking run is RUNNING in this results schema: {busy}")


try:
    # Central mode: another workspace is checked (allowlist, secret, URL, identity) before it is contacted.
    w, target_id, remote = planner.central_target(spark, hub_client, target_req, g("central_workspaces"),
                                                  g("central_client_id"), g("central_secret"),
                                                  lambda scope, key: dbutils.secrets.get(scope, key))
    store.upsert(spark, schema, "ug_migration_applies", store.APPLY_COLUMNS, "apply_id",
                 {"apply_id": apply_id, "workspace_id": target_id, "workspace_url": w.config.host})
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        open(os.path.join(LOG_DIR, "ug_migration_toolkit.marker"), "w").write("Unity Gateway migration toolkit logs\n")
        durable = os.path.join(LOG_DIR, f"{apply_id}.jsonl")
    except OSError:
        durable = None  # fall back to a temp file; results are still stored at the end
    log_path = durable or os.path.join(tempfile.mkdtemp(prefix="ug_apply_"), "apply_log.jsonl")
    execute = mode in ("execute", "rollback")

    if operation == "resume_legacy":
        src_id = g("rollback_of")
        if not src_id:
            raise ValueError("resume needs rollback_of (the apply_id of a pause run)")
        src = store.apply_run(spark, schema, src_id)
        problem = apply_mod.resume_source_error(src)
        if problem:
            raise ValueError(problem)
        if store.effective_status(hub_client, src["status"], src["job_run_id"]) == "RUNNING":
            raise ValueError("that pause run hasn't finished yet")
        if execute:
            if store.already_rolled_back(spark, schema, src_id, hub_client, exclude=apply_id):
                raise ValueError("that pause run has already been resumed")
            _check_no_other_legacy_write(hub_client)
        entries = store.legacy_run_entries(spark, schema, src_id, os.path.join(LOG_DIR, f"{src_id}.jsonl"))
        results = apply_mod.resume_legacy(w, entries, endpoints or None, execute, log_path, apply_id, src_id,
                                          force=flag("force"))
    elif operation == "test_call":
        results = apply_mod.run_test_calls(w, services, api_type, prompt, execute, log_path, apply_id)
    elif operation == "guardrail_check":
        results = apply_mod.run_guardrail_checks(w, pairs, execute, log_path, apply_id)
    elif operation == "pause_legacy":
        if execute:
            _check_no_other_legacy_write(hub_client)
        recent = None  # None: traffic couldn't be checked, so pause refuses unless force is set (fail closed)
        if not flag("force"):
            try:
                since = (datetime.now(timezone.utc) - timedelta(hours=apply_mod.PAUSE_TRAFFIC_HOURS)
                         ).strftime("%Y-%m-%d %H:%M:%S")
                rows = store.run_built(spark, store.legacy_traffic_since(endpoints, since,
                                                                         target_id or w.get_workspace_id()))
                recent = {}
                for r in rows:
                    recent[r["endpoint_name"]] = recent.get(r["endpoint_name"], 0) + int(r["requests"] or 0)
            except Exception as terr:
                print(f"could not check recent traffic: {str(terr)[:300]}")
        results = apply_mod.pause_legacy(w, endpoints, execute, log_path, apply_id, recent_requests=recent,
                                         force=flag("force"))
    elif operation == "enable_tracking":
        if execute:
            _check_no_other_legacy_write(hub_client)
        results = apply_mod.enable_tracking(w, endpoints, execute, log_path, apply_id)
    elif ROLLING_BACK:  # rollback_dry_run shows what rollback would delete; rollback deletes it
        src_id = g("rollback_of")
        if not src_id:
            raise ValueError("rollback needs rollback_of (the apply_id of an execute run)")
        src = store.apply_run(spark, schema, src_id)
        if not src or src["mode"] != "execute":
            raise ValueError("rollback_of must be the apply_id of an execute run")
        if src["operation"] != "apply":
            # Only apply runs have objects to delete. Tracking and test-call runs have no rollback here.
            raise ValueError(f"rollback isn't available for a {src['operation']} run: only a pause can be undone (resume it)")
        if store.effective_status(hub_client, src["status"], src["job_run_id"]) == "RUNNING":
            raise ValueError("that execute run hasn't finished yet")
        if store.already_rolled_back(spark, schema, src_id, hub_client, exclude=apply_id):
            raise ValueError("that execute run has already been rolled back")
        work = os.path.join(tempfile.mkdtemp(prefix="ug_rb_"), "apply_log.jsonl")
        n = store.apply_log_from_items(spark, schema, src_id, work, os.path.join(LOG_DIR, f"{src_id}.jsonl"))
        if n:
            protect, released = apply_mod.protection_from_runs(store.protection_runs(spark, schema, LOG_DIR), src_id)
            # The rollback deletes only what its dry run listed (would_delete). It reads the workspace again, and up
            # to 24 hours can pass: another run may have been rolled back since, which releases objects the dry run
            # kept, and force makes changed objects deletable. Anything not listed is kept, and the result says so.
            only = store.rollback_dry_run_deletes(spark, schema, g("dry_run_id")) if mode == "rollback" else None
            results = apply_mod.rollback(w, work, execute=execute, protect=protect, released=released,
                                         apply_id=src_id, force=flag("force"), audit_path=log_path, only=only)
        else:
            results = [{"type": "log", "name": src_id, "action": "manual",
                        "reason": "no created objects found for that run; check the workspace by hand"}]
    else:
        if not endpoints:
            raise ValueError("choose at least one endpoint")
        uc_map = json.loads(g("uc_secret_map")) if g("uc_secret_map").strip() else None
        allowed = [s.strip() for s in g("secret_schemas").split(",") if s.strip()]
        secrets = apply_mod.Secrets(w, uc_map, flag("allow_secret_read"), dry_run=not execute,
                                    allowed_schemas=allowed, read_enabled=flag("allow_secret_read_enabled"),
                                    create_uc=flag("create_uc_secrets"))
        if execute:
            # Best-effort lock: this row is RUNNING now, so two runs starting together see each other and both stop.
            busy = store.running_applies(spark, hub_client, schema, g("target_catalog"), g("target_schema"), apply_id)
            if busy:
                raise ValueError(f"another execute run is RUNNING for {g('target_catalog')}.{g('target_schema')}: {busy}")
        results = apply_mod.apply(w, endpoints, g("target_catalog"), g("target_schema"), execute, secrets,
                                  log_path, grants=flag("grants"), ack_guardrails=flag("ack_guardrails"),
                                  smoke=flag("smoke_test"), apply_id=apply_id,
                                  is_active=lambda aid: store.is_run_active(spark, hub_client, schema, aid))
    results = [apply_mod._mask(r) for r in results]
    store.write_apply_items(spark, schema, apply_id, results)
    status, summary = apply_mod.run_outcome(results)  # acknowledged guardrails are not a problem
    store.upsert(spark, schema, "ug_migration_applies", store.APPLY_COLUMNS, "apply_id", {
        "apply_id": apply_id, "status": status, "summary": json.dumps(summary), "finished_at": store.now()})
except BaseException as e:  # includes job cancellation
    _record_failure(e)
    raise

dbutils.notebook.exit(json.dumps({"apply_id": apply_id, "results": len(results)}))
