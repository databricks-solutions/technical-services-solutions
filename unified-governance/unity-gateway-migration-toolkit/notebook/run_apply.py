# Databricks notebook source
# MAGIC %md
# MAGIC # Unity Gateway migration: apply / rollback (app job)
# MAGIC Runs `ug_migration_apply` for the endpoints chosen in the app and stores every result in
# MAGIC `<results_schema>.ug_migration_applies` and `ug_migration_apply_items`.
# MAGIC
# MAGIC - `mode = dry_run`: shows what would be created; changes nothing (default).
# MAGIC - `mode = execute`: creates provider services, model services and grants.
# MAGIC - `mode = rollback`: deletes the objects an earlier execute run created (`rollback_of`).
# MAGIC
# MAGIC Job-level settings the installer sets on the job definition (the app must not pass them):
# MAGIC `secret_schemas` (comma list of catalog.schema allowed for UC secrets) and `allow_secret_read_enabled`.
# MAGIC
# MAGIC Prototype from Databricks Shared Technical Services, provided as is.

# COMMAND ----------

# MAGIC %pip install --quiet "databricks-sdk==0.158.0"
# MAGIC %restart_python

# COMMAND ----------

for name, default in (("apply_id", ""), ("job_run_id", ""), ("results_schema", ""), ("mode", "dry_run"), ("endpoints", ""),
                      ("target_catalog", ""), ("target_schema", ""), ("uc_secret_map", ""),
                      ("allow_secret_read", "false"), ("grants", "true"), ("rollback_of", ""),
                      ("scan_run_id", ""), ("requested_by", ""), ("ack_guardrails", "false"), ("smoke_test", "false"),
                      ("force", "false"), ("secret_schemas", ""), ("allow_secret_read_enabled", "false")):
    dbutils.widgets.text(name, default)

# COMMAND ----------

import json
import os
import re
import sys
import tempfile
import uuid

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
if mode not in ("dry_run", "execute", "rollback"):
    raise ValueError(f"mode must be dry_run, execute or rollback, not {mode!r}")
apply_id = g("apply_id") or str(uuid.uuid4())
ID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
for v in (apply_id, g("rollback_of"), g("scan_run_id")):
    if v and not re.fullmatch(ID_RE, v):
        raise ValueError(f"bad run id {v!r}")
endpoints = [e.strip() for e in g("endpoints").split(",") if e.strip()]
NAME = r"[A-Za-z0-9_\-]+"
# The app validates all of this too; the job re-checks so a direct run can't do more than the app allows.
if not re.fullmatch(rf"{NAME}\.{NAME}", schema):
    raise ValueError("results_schema must be catalog.schema")
if mode != "rollback":
    bad = [e for e in endpoints if not re.fullmatch(NAME, e)]
    if bad or not re.fullmatch(NAME, g("target_catalog")) or not re.fullmatch(NAME, g("target_schema")):
        raise ValueError(f"bad endpoint, target catalog or target schema name {bad}")
job_run_id = dbutils.widgets.get("job_run_id")  # filled by the job with {{job.run_id}}
store.ensure_tables(spark, schema)
if store.run_exists(spark, schema, "ug_migration_applies", "apply_id", apply_id):
    raise ValueError(f"apply_id {apply_id} already exists; each run needs a new id")
store.upsert(spark, schema, "ug_migration_applies", store.APPLY_COLUMNS, "apply_id", {
    "apply_id": apply_id, "job_run_id": str(job_run_id), "requested_by": g("requested_by"),
    "scan_run_id": g("scan_run_id"), "mode": mode, "endpoints": ",".join(endpoints),
    "target_catalog": g("target_catalog"), "target_schema": g("target_schema"), "rollback_of": g("rollback_of"),
    "toolkit_version": planner.__version__, "status": "RUNNING", "started_at": store.now()})

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


try:
    w = WorkspaceClient()
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        open(os.path.join(LOG_DIR, "ug_migration_toolkit.marker"), "w").write("Unity Gateway migration toolkit logs\n")
        durable = os.path.join(LOG_DIR, f"{apply_id}.jsonl")
    except OSError:
        durable = None  # fall back to a temp file; results are still stored at the end
    log_path = durable or os.path.join(tempfile.mkdtemp(prefix="ug_apply_"), "apply_log.jsonl")

    if mode == "rollback":
        src_id = g("rollback_of")
        if not src_id:
            raise ValueError("rollback needs rollback_of (the apply_id of an execute run)")
        src = store.apply_run(spark, schema, src_id)
        if not src or src["mode"] != "execute":
            raise ValueError("rollback_of must be the apply_id of an execute run")
        if store.effective_status(w, src["status"], src["job_run_id"]) == "RUNNING":
            raise ValueError("that execute run hasn't finished yet")
        if store.already_rolled_back(spark, schema, src_id, w, exclude=apply_id):
            raise ValueError("that execute run has already been rolled back")
        work = os.path.join(tempfile.mkdtemp(prefix="ug_rb_"), "apply_log.jsonl")
        n = store.apply_log_from_items(spark, schema, src_id, work, os.path.join(LOG_DIR, f"{src_id}.jsonl"))
        if n:
            protect, released = apply_mod.protection_from_runs(store.protection_runs(spark, schema), src_id)
            results = apply_mod.rollback(w, work, execute=True, protect=protect, released=released,
                                         apply_id=src_id, force=flag("force"), audit_path=log_path)
        else:
            results = [{"type": "log", "name": src_id, "action": "manual",
                        "reason": "no created objects found for that run; check the workspace by hand"}]
    else:
        if not endpoints:
            raise ValueError("choose at least one endpoint")
        uc_map = json.loads(g("uc_secret_map")) if g("uc_secret_map").strip() else None
        execute = mode == "execute"
        allowed = [s.strip() for s in g("secret_schemas").split(",") if s.strip()]
        secrets = apply_mod.Secrets(w, uc_map, flag("allow_secret_read"), dry_run=not execute,
                                    allowed_schemas=allowed, read_enabled=flag("allow_secret_read_enabled"))
        if execute:
            # Best-effort lock: this row is RUNNING now, so two runs starting together see each other and both stop.
            busy = store.running_applies(spark, w, schema, g("target_catalog"), g("target_schema"), apply_id)
            if busy:
                raise ValueError(f"another execute run is RUNNING for {g('target_catalog')}.{g('target_schema')}: {busy}")
        results = apply_mod.apply(w, endpoints, g("target_catalog"), g("target_schema"), execute, secrets,
                                  log_path, grants=flag("grants"), ack_guardrails=flag("ack_guardrails"),
                                  smoke=flag("smoke_test"), apply_id=apply_id)
    results = [apply_mod._mask(r) for r in results]
    store.write_apply_items(spark, schema, apply_id, results)
    problems = sum(1 for r in results if r.get("action") in
                   ("error", "manual", "mismatch", "kept", "needs_attention", "smoke_failed"))
    summary = {}
    for r in results:
        summary[r.get("action")] = summary.get(r.get("action"), 0) + 1
    store.upsert(spark, schema, "ug_migration_applies", store.APPLY_COLUMNS, "apply_id", {
        "apply_id": apply_id, "status": "NEEDS_ATTENTION" if problems else "SUCCEEDED",
        "summary": json.dumps(summary), "finished_at": store.now()})
except BaseException as e:  # includes job cancellation
    _record_failure(e)
    raise

dbutils.notebook.exit(json.dumps({"apply_id": apply_id, "results": len(results)}))
