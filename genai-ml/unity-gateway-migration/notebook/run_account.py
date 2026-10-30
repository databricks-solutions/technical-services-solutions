# Databricks notebook source
# MAGIC %md
# MAGIC # Unity Gateway migration: account view
# MAGIC Ranks every workspace in the account by legacy (v1/v2) traffic, proposes migration waves and, optionally,
# MAGIC appends a snapshot to Delta tables for the progress dashboard.
# MAGIC
# MAGIC - Reads `system.serving.*`, `system.ai_gateway.usage` and `system.access.workspaces_latest` (account admin by default).
# MAGIC - The only write is the optional snapshot (`snapshot_table`).
# MAGIC - Prototype from Databricks Shared Technical Services, provided as is.

# COMMAND ----------

# MAGIC %pip install --quiet "databricks-sdk>=0.158.0"
# MAGIC %restart_python

# COMMAND ----------

dbutils.widgets.text("days", "30", "Traffic window (days)")
dbutils.widgets.text("out_dir", "", "Output folder (blank = next to this notebook)")
dbutils.widgets.text("snapshot_table", "", "Snapshot tables prefix catalog.schema.prefix (blank = no snapshot)")
dbutils.widgets.text("deep_scan", "0", "Deep-scan the N busiest workspaces (needs access to them)")
dbutils.widgets.text("deep_warehouse_id", "", "SQL warehouse ID for deep scans (required when deep_scan > 0)")
dbutils.widgets.text("requested_by", "")

# COMMAND ----------

import os
import sys

from databricks.sdk import WorkspaceClient

here = os.path.dirname(dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get())
sys.path.insert(0, "/Workspace" + here.rsplit("/notebook", 1)[0])
sys.path.insert(0, "/Workspace" + here)
import ug_migration_account as account

out_dir = dbutils.widgets.get("out_dir") or f"/Workspace{here}/ug_account_out"
os.makedirs(out_dir, exist_ok=True)
open(os.path.join(out_dir, "ug_migration_toolkit.marker"), "w").write("Unity Gateway migration toolkit output\n")
deep = int(dbutils.widgets.get("deep_scan") or 0) or None
deep_wh = dbutils.widgets.get("deep_warehouse_id").strip() or None
if deep and not deep_wh:
    # Deep scans read traffic in each workspace through a SQL warehouse; without one every scan would come back
    # without traffic data.
    raise ValueError("deep_scan needs deep_warehouse_id (a SQL warehouse ID)")
result = account.run(WorkspaceClient(), None, out_dir, days=int(dbutils.widgets.get("days")), deep=deep,
                     deep_warehouse_id=deep_wh, snapshot_prefix=dbutils.widgets.get("snapshot_table") or None)
print(result)

# COMMAND ----------

import html

displayHTML("<pre>" + html.escape(open(os.path.join(out_dir, "ACCOUNT_SUMMARY.md")).read()) + "</pre>")
