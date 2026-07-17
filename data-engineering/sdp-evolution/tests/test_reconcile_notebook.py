# Databricks notebook source
# Unit tests for reconcile(), as a single self-contained notebook.
# Job success == all asserts pass. Any failure raises and fails the run.

import os
import sys

# Add the bundle's src/ (sibling of tests/) to the path so we import the real code.
nb_dir = os.path.dirname(
    dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
)
sys.path.insert(0, "/Workspace" + os.path.join(os.path.dirname(nb_dir), "src"))

from reconcile import reconcile

INPUT_SCHEMA = (
    "order_id string, cust_name string, amount string, "
    "order_ts string, _rescued_data string"
)

# COMMAND ----------

# v1 passthrough: clean row, no rescued data.
df = spark.createDataFrame(
    [("o1", "Alice", "10.5", "2026-01-01T00:00:00", None)],
    schema=INPUT_SCHEMA,
)
row = reconcile(df).collect()[0]
assert row["customer_name"] == "Alice", row["customer_name"]
assert row["amount"] == 10.5, row["amount"]
assert row["loyalty_tier"] is None, row["loyalty_tier"]

# COMMAND ----------

# v2 drift recovered: values pulled back out of _rescued_data.
rescued = '{"customer_name":"Frank","amount":210.0,"loyalty_tier":"gold"}'
df = spark.createDataFrame(
    [("o2", None, None, "2026-02-02T00:00:00", rescued)],
    schema=INPUT_SCHEMA,
)
row = reconcile(df).collect()[0]
assert row["customer_name"] == "Frank", row["customer_name"]
assert row["amount"] == 210.0, row["amount"]
assert row["loyalty_tier"] == "gold", row["loyalty_tier"]

# COMMAND ----------

print("All reconcile tests passed.")
