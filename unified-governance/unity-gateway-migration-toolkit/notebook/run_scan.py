# Databricks notebook source
# MAGIC %md
# MAGIC # Unity Gateway migration: workspace scan (app job)
# MAGIC Runs the read-only planner on this workspace and stores the results for the app in
# MAGIC `<results_schema>.ug_migration_scans` and `ug_migration_scan_items`.
# MAGIC Prototype from Databricks Shared Technical Services, provided as is.

# COMMAND ----------

# MAGIC %pip install --quiet "databricks-sdk>=0.158.0"
# MAGIC %restart_python

# COMMAND ----------

dbutils.widgets.text("run_id", "")
dbutils.widgets.text("job_run_id", "")
dbutils.widgets.text("results_schema", "")
dbutils.widgets.text("days", "30")
dbutils.widgets.text("scan_roots", "")
dbutils.widgets.text("target_catalog", "ai_gateway")
dbutils.widgets.text("target_schema", "migrated")
dbutils.widgets.text("requested_by", "")

# COMMAND ----------

import json
import os
import sys
import tempfile
import uuid

from databricks.sdk import WorkspaceClient

ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
here = os.path.dirname(ctx.notebookPath().get())
sys.path.insert(0, "/Workspace" + here.rsplit("/notebook", 1)[0])
import ug_migration_planner as planner
import ug_migration_store as store

schema = dbutils.widgets.get("results_schema")
run_id = dbutils.widgets.get("run_id") or str(uuid.uuid4())
job_run_id = dbutils.widgets.get("job_run_id")  # filled by the job with {{job.run_id}}
roots = [r.strip() for r in dbutils.widgets.get("scan_roots").split(",") if r.strip()] or None
meta = {"run_id": run_id, "job_run_id": str(job_run_id), "requested_by": dbutils.widgets.get("requested_by"),
        "days": dbutils.widgets.get("days"), "target_catalog": dbutils.widgets.get("target_catalog"),
        "target_schema": dbutils.widgets.get("target_schema"), "scan_roots": ",".join(roots or []),
        "toolkit_version": planner.__version__, "status": "RUNNING", "started_at": store.now()}
import re
NAME = r"[A-Za-z0-9_\-]+"
if not re.fullmatch(rf"{NAME}\.{NAME}", schema) or not re.fullmatch(NAME, meta["target_catalog"]) \
        or not re.fullmatch(NAME, meta["target_schema"]) or not re.fullmatch(r"[0-9]{1,3}", meta["days"]):
    raise ValueError("bad results_schema, target catalog/schema or days")
if any(r == "/" or ".." in r or not r.startswith("/") for r in roots or []):
    raise ValueError("scan_roots must be workspace folders such as /Shared/team (not /)")
store.ensure_tables(spark, schema)
if store.run_exists(spark, schema, "ug_migration_scans", "run_id", run_id):
    raise ValueError(f"run_id {run_id} already exists; each scan needs a new id")

# COMMAND ----------

w = WorkspaceClient()
out_dir = tempfile.mkdtemp(prefix="ug_scan_")
try:
    store.upsert(spark, schema, "ug_migration_scans", store.SCAN_COLUMNS, "run_id", meta)
    res = planner.run(w, out_dir, warehouse_id=None, days=int(meta["days"]), target_catalog=meta["target_catalog"],
                      target_schema=meta["target_schema"], scan_roots=roots)
    ready = store.write_scan_items(spark, schema, run_id, out_dir)
    store.upsert(spark, schema, "ug_migration_scans", store.SCAN_COLUMNS, "run_id", {
        "run_id": run_id, "status": "SUCCEEDED", "readiness": res["readiness"], "endpoints": res["endpoints"],
        "client_references": res["client_references"], "traffic_status": ready.get("traffic_status"),
        "workspace_url": w.config.host, "workspace_id": ready.get("workspace_id"), "error": None,
        "finished_at": store.now()})
except BaseException as e:  # includes job cancellation
    try:
        store.upsert(spark, schema, "ug_migration_scans", store.SCAN_COLUMNS, "run_id",
                     {**meta, "status": "FAILED", "error": (str(e) or type(e).__name__)[:2000], "finished_at": store.now()})
    finally:
        raise e

dbutils.notebook.exit(json.dumps({"run_id": run_id, **res}))
