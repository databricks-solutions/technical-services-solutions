# Databricks notebook source
# MAGIC %pip install databricks-labs-lakebridge

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %md
# MAGIC # Snowflake Reconciliation Wrapper
# MAGIC
# MAGIC **What it does:** This is the **entry point** you run (or schedule as a job) to execute
# MAGIC reconciliation for config rows matching optional filters. It reads from the metadata config table
# MAGIC (`lakebridge_config_table`), applies label / table / catalog-schema filters, calls
# MAGIC `get_recon_results()` from `snowflake_recon_main` per row, and appends results to
# MAGIC `table_recon_summary` under `lakebridge_catalog` / `lakebridge_schema`.
# MAGIC
# MAGIC **Why it's important:** This is the only notebook you need to run directly. It orchestrates
# MAGIC the full reconciliation batch and produces the summary report. You can filter by label to
# MAGIC run subsets of tables. Multiple labels can be comma-separated.
# MAGIC
# MAGIC **How it works with the other notebooks:**
# MAGIC 1. **snowflake_auto_discover** → MERGEs into `{lakebridge_catalog}.{lakebridge_schema}.{lakebridge_config_table}`
# MAGIC 2. **This notebook (wrapper)** → reads the same logical table via `lakebridge_*` metadata widgets, filters rows, calls recon_main
# MAGIC 3. **snowflake_recon_main** → imported via `%run`; does the actual reconciliation per table
# MAGIC 4. **snowflake_transformation_query_generator** → imported transitively via recon_main; builds type-aware column transformations
# MAGIC
# MAGIC **Parameters:**
# MAGIC - `secret_scope` — Databricks secret scope with Snowflake Spark connector credentials
# MAGIC - `lakebridge_catalog` / `lakebridge_schema` — Unity Catalog location for reconciliation metadata tables
# MAGIC - `lakebridge_config_table` / `table_recon_summary` — Delta table names (must match auto_discover / DDL)
# MAGIC - `label` — Comma-separated labels (required filter on config rows)
# MAGIC - `report_type` — `auto` (derive from PK), `row`, `all`, `schema`, or `data`
# MAGIC - `include_aggregates` — Whether to run aggregate checks (sum/min/max/count per column) after row/column reconciliation
# MAGIC - `reconcile_tables` — Optional comma-separated names; matches `source_table` or `databricks_table` (case-insensitive)
# MAGIC - `filter_source_catalog` / `filter_source_schema` / `filter_target_catalog` / `filter_target_schema` — Optional exact filters on config row columns

# COMMAND ----------

# MAGIC %run "./snowflake_recon_main"

# COMMAND ----------

# Hardcoded: this wrapper is specific to Snowflake. Lakebridge's data_source
# value must be "snowflake" for the Snowflake connector.
source_system = "snowflake"

dbutils.widgets.text("secret_scope", "", "Secret Scope")
dbutils.widgets.text("lakebridge_catalog", "", "Lakebridge Metadata Catalog")
dbutils.widgets.text("lakebridge_schema", "reconcile", "Lakebridge Metadata Schema")
dbutils.widgets.text("lakebridge_config_table", "table_configs", "Config Table Name")
dbutils.widgets.text("table_recon_summary", "table_recon_summary", "Summary Table Name")
dbutils.widgets.text("user_suffix", "", "User suffix for config/summary tables (blank = auto-derive from current_user())")
dbutils.widgets.text("label", "", "Label (comma-separated for multiple)")
dbutils.widgets.dropdown(
    "report_type", "auto",
    ["auto", "row", "all", "schema", "data"],
    "Row/column report type (auto = derive from primary key)",
)
dbutils.widgets.dropdown(
    "include_aggregates", "true",
    ["true", "false"],
    "Include aggregate checks (sum/min/max/count per column)",
)
dbutils.widgets.text(
    "reconcile_tables",
    "",
    "Optional comma-separated table names (source_table or databricks_table, case-insensitive)",
)
dbutils.widgets.text("filter_source_catalog", "", "Optional: filter config rows by source_catalog")
dbutils.widgets.text("filter_source_schema", "", "Optional: filter config rows by source_schema")
dbutils.widgets.text(
    "filter_target_catalog", "", "Optional: filter config rows by databricks_catalog"
)
dbutils.widgets.text(
    "filter_target_schema", "", "Optional: filter config rows by databricks_schema"
)

secret_scope = dbutils.widgets.get("secret_scope")
lakebridge_catalog = dbutils.widgets.get("lakebridge_catalog").lower()
lakebridge_schema = dbutils.widgets.get("lakebridge_schema").lower()
lakebridge_config_table = dbutils.widgets.get("lakebridge_config_table").lower()
table_recon_summary = dbutils.widgets.get("table_recon_summary")
import re as _re
_raw_suffix = (dbutils.widgets.get("user_suffix") or "").strip()
if not _raw_suffix:
    _raw_suffix = spark.sql("SELECT current_user()").first()[0].split("@")[0]
_user_suffix = _re.sub(r"[^a-z0-9]+", "_", _raw_suffix.lower()).strip("_")
lakebridge_config_table = f"{lakebridge_config_table}_{_user_suffix}"
table_recon_summary = f"{table_recon_summary}_{_user_suffix}"
label = dbutils.widgets.get("label").lower()
label_list = [col.strip() for col in label.split(",")] if label.strip() else []
_report_type_widget = dbutils.widgets.get("report_type").strip()
_report_type_override = None if _report_type_widget == "auto" else _report_type_widget
_include_aggregates = dbutils.widgets.get("include_aggregates").strip().lower() == "true"

reconcile_tables_raw = dbutils.widgets.get("reconcile_tables") or ""
reconcile_table_names = [
    t.strip().lower() for t in reconcile_tables_raw.split(",") if t.strip()
]
filter_source_catalog = (dbutils.widgets.get("filter_source_catalog") or "").strip()
filter_source_schema = (dbutils.widgets.get("filter_source_schema") or "").strip()
filter_target_catalog = (dbutils.widgets.get("filter_target_catalog") or "").strip()
filter_target_schema = (dbutils.widgets.get("filter_target_schema") or "").strip()

# COMMAND ----------

from pyspark.sql.types import StructType, StructField, StringType, TimestampType

table_recon_summary_schema = StructType(
    [
        StructField("timestamp", TimestampType(), True),
        StructField("label", StringType(), True),
        StructField("databricks_catalog", StringType(), True),
        StructField("databricks_schema", StringType(), True),
        StructField("databricks_table", StringType(), True),
        StructField("status", StringType(), True),
        StructField("recon_id", StringType(), True),
        StructField("row_status", StringType(), True),
        StructField("column_status", StringType(), True),
        StructField("schema_status", StringType(), True),
        StructField("error", StringType(), True),
    ]
)

# COMMAND ----------

import pyspark.sql.functions as f

config_df = spark.table(
    f"{lakebridge_catalog}.{lakebridge_schema}.{lakebridge_config_table}"
)
config_df = (
    config_df.withColumnRenamed("source_filters", "filters_src")
    .withColumnRenamed("databricks_filters", "filters_tgt")
    .withColumnRenamed("primary_key", "pk")
    .where(f.col("label").isin(label_list))
)

if reconcile_table_names:
    lc_src = f.lower(f.col("source_table"))
    lc_tgt = f.lower(f.col("databricks_table"))
    name_match = f.lit(False)
    for name in reconcile_table_names:
        name_match = name_match | (lc_src == f.lit(name)) | (lc_tgt == f.lit(name))
    config_df = config_df.where(name_match)

if filter_source_catalog:
    config_df = config_df.where(f.col("source_catalog") == f.lit(filter_source_catalog))
if filter_source_schema:
    config_df = config_df.where(f.col("source_schema") == f.lit(filter_source_schema))
if filter_target_catalog:
    config_df = config_df.where(
        f.col("databricks_catalog") == f.lit(filter_target_catalog)
    )
if filter_target_schema:
    config_df = config_df.where(
        f.col("databricks_schema") == f.lit(filter_target_schema)
    )


def get_args_dict(pipeline) -> dict:
    pk = ",".join(pipeline["pk"]).strip() if pipeline["pk"] else ""
    row = pipeline.asDict()
    return {
        "pk": pk,
        "source_catalog": pipeline["source_catalog"],
        "source_schema": pipeline["source_schema"],
        "source_table": pipeline["source_table"],
        "target_catalog": pipeline["databricks_catalog"].lower(),
        "target_schema": pipeline["databricks_schema"].lower(),
        "target_table": pipeline["databricks_table"].lower(),
        "filters_src": pipeline["filters_src"],
        "filters_tgt": pipeline["filters_tgt"],
        "select_columns": pipeline["select_columns"],
        "drop_columns": pipeline["drop_columns"],
        "column_mapping": pipeline["column_mapping"],
        "column_thresholds": pipeline["column_thresholds"],
        "label": pipeline["label"],
        "secret_scope": secret_scope,
        "lakebridge_catalog": lakebridge_catalog,
        "lakebridge_schema": lakebridge_schema,
        "source_system": source_system,
        "aggregates_json": row.get("aggregates"),
        "include_aggregates": _include_aggregates,
        "report_type_override": _report_type_override,
    }


# COMMAND ----------

all_results = []

for pipeline in config_df.collect():
    try:
        result = get_recon_results(**get_args_dict(pipeline))
        all_results.append(result)
    except Exception as e:
        print(f"Error processing pipeline {pipeline}: {e}")

if all_results:
    results_df = spark.createDataFrame(all_results, table_recon_summary_schema)
    results_df.display()
    spark.sql(f"""CREATE TABLE IF NOT EXISTS {lakebridge_catalog}.{lakebridge_schema}.{table_recon_summary} (
        timestamp TIMESTAMP, label STRING, databricks_catalog STRING, databricks_schema STRING,
        databricks_table STRING, status STRING, recon_id STRING, row_status STRING,
        column_status STRING, schema_status STRING, error STRING
    ) USING DELTA""")
    results_df.write.format("delta").mode("append").saveAsTable(
        f"{lakebridge_catalog}.{lakebridge_schema}.{table_recon_summary}"
    )
    print(
        f"Wrote {len(all_results)} results to {lakebridge_catalog}.{lakebridge_schema}.{table_recon_summary}"
    )
else:
    print("No config rows matched the label and optional filters -- nothing to reconcile.")
