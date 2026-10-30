# Databricks notebook source
# MAGIC %md
# MAGIC # Unity Gateway migration planner (read-only)
# MAGIC Runs `ug_migration_planner.py` from the same folder. It only reads: nothing is created or changed.
# MAGIC Traffic uses this notebook's Spark session (needs read access to `system.serving`).
# MAGIC Prototype from Databricks Shared Technical Services, provided as is.

# COMMAND ----------

# MAGIC %pip install --quiet "databricks-sdk>=0.158.0"
# MAGIC %restart_python

# COMMAND ----------

dbutils.widgets.text("out_dir", "", "Output folder (workspace or volume path)")
dbutils.widgets.text("days", "30", "Traffic window (days)")
dbutils.widgets.text("scan_root", "", "Scan root (blank = /Users, /Shared, /Repos)")

# COMMAND ----------

import os
import sys

from databricks.sdk import WorkspaceClient

here = os.path.dirname(dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get())
sys.path.insert(0, "/Workspace" + here.rsplit("/notebook", 1)[0])  # bundle layout: modules one level up
sys.path.insert(0, "/Workspace" + here)
import ug_migration_planner as planner

out_dir = dbutils.widgets.get("out_dir") or f"/Workspace{here}/ug_migration_out"
roots = [dbutils.widgets.get("scan_root")] if dbutils.widgets.get("scan_root") else None
result = planner.run(WorkspaceClient(), out_dir, warehouse_id=None, days=int(dbutils.widgets.get("days")),
                     scan_roots=roots)
print(result)

# COMMAND ----------

import html

displayHTML("<pre>" + html.escape(open(os.path.join(out_dir, "SUMMARY.md")).read()) + "</pre>")
