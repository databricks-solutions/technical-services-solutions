# Databricks notebook source
# MAGIC %md
# MAGIC # Snowflake Reconciliation Main
# MAGIC
# MAGIC **What it does:** Defines the `get_recon_results()` function that reconciles a single source/target
# MAGIC table pair using the `databricks-labs-lakebridge` library. It builds a `ReconcileConfig` and
# MAGIC `TableRecon` object, calls `TriggerReconService.trigger_recon()` for row/column reconciliation and
# MAGIC (when `include_aggregates=True`) `TriggerReconAggregateService.trigger_recon_aggregates()` for
# MAGIC aggregate checks. Returns a summary tuple with pass/fail status for row, column, and schema checks.
# MAGIC
# MAGIC **Why it's important:** This is the **core reconciliation engine wrapper**. It translates the
# MAGIC per-table config (primary keys, filters, column selections) into the Lakebridge API's expected
# MAGIC format, handles both successful and failed reconciliation results, and catches exceptions so that
# MAGIC one table failure doesn't abort the entire batch.
# MAGIC
# MAGIC **How it works with the other notebooks:**
# MAGIC - **Depends on:** `snowflake_transformation_query_generator` (imported via `%run`) — provides
# MAGIC   `get_transformations()` which builds per-column type-aware CASTs so that Snowflake and
# MAGIC   Databricks values compare correctly as strings.
# MAGIC - **Called by:** `snowflake_recon_wrapper` — which iterates over config rows from the metadata
# MAGIC   config table and calls `get_recon_results()` for each one.
# MAGIC - Summary tuples are appended to `{lakebridge_catalog}.{lakebridge_schema}.{table_recon_summary}` by the wrapper.
# MAGIC   Detailed mismatch data is written under the same metadata catalog/schema by Lakebridge
# MAGIC   (e.g. `details` and `metrics` tables; exact names are defined by the library).
# MAGIC
# MAGIC **Snowflake-specific note:** Unlike the SQL Server path, Lakebridge applies `sha256_partial` on
# MAGIC both sides for Snowflake, so the Unicode hash-encoding issue (#1619) does not apply here —
# MAGIC `column_status` is a reliable indicator.

# COMMAND ----------

# MAGIC %run "./snowflake_transformation_query_generator"

# COMMAND ----------

# MAGIC %run "./snowflake_aggregate_rule_generator"

# COMMAND ----------

from datetime import datetime
import json
import traceback

from databricks.labs.lakebridge.config import TableRecon, ReconcileConfig, DatabaseConfig, ReconcileMetadataConfig
from databricks.labs.lakebridge.reconcile.recon_config import (
    Table,
    Aggregate,
    ColumnMapping,
    ColumnThresholds,
    Transformation,
    JdbcReaderOptions,
    Filters,
)
from databricks.labs.lakebridge.reconcile.trigger_recon_service import TriggerReconService
from databricks.labs.lakebridge.reconcile.trigger_recon_aggregate_service import TriggerReconAggregateService
from databricks.labs.lakebridge.reconcile.exception import ReconciliationException
from databricks.labs.lakebridge.__about__ import __version__
from databricks.sdk import WorkspaceClient

ws = WorkspaceClient(product="lakebridge", product_version=__version__)

# COMMAND ----------


def get_recon_results(
    pk,
    source_catalog,
    source_schema,
    source_table,
    target_catalog,
    target_schema,
    target_table,
    filters_src,
    filters_tgt,
    select_columns,
    drop_columns,
    column_mapping,
    column_thresholds,
    label,
    secret_scope,
    lakebridge_catalog,
    lakebridge_schema,
    source_system,
    aggregates_json=None,
    include_aggregates=True,
    report_type_override=None,
):
    print(f"Processing table: {target_catalog}.{target_schema}.{target_table}")

    pk_split = [col.strip() for col in pk.split(",")] if pk.strip() else []
    report_type = report_type_override or ("row" if not pk_split else "all")

    select_columns = (
        [col.strip() for col in select_columns.split(",")]
        if select_columns and select_columns.strip()
        else None
    )
    drop_columns = (
        [col.strip() for col in drop_columns.split(",")]
        if drop_columns and drop_columns.strip()
        else None
    )

    reconcile_config = ReconcileConfig(
        data_source=source_system,
        report_type=report_type,
        secret_scope=secret_scope,
        database_config=DatabaseConfig(
            source_catalog=source_catalog,
            source_schema=source_schema,
            target_catalog=target_catalog,
            target_schema=target_schema,
        ),
        metadata_config=ReconcileMetadataConfig(
            catalog=lakebridge_catalog,
            schema=lakebridge_schema,
        ),
    )

    column_mapping_parsed = None
    column_mapping_objs = None
    if column_mapping and column_mapping.strip():
        column_mapping_parsed = json.loads(column_mapping)
        column_mapping_objs = [
            ColumnMapping(source_name=m["source_name"], target_name=m["target_name"])
            for m in column_mapping_parsed
        ]

    column_thresholds_parsed = None
    column_thresholds_objs = None
    if column_thresholds and column_thresholds.strip():
        column_thresholds_parsed = json.loads(column_thresholds)
        column_thresholds_objs = [
            ColumnThresholds(
                column_name=t["column_name"],
                lower_bound=t["lower_bound"],
                upper_bound=t["upper_bound"],
                type=t["type"],
            )
            for t in column_thresholds_parsed
        ]

    transformations = get_transformations(
        source_catalog,
        source_schema,
        source_table,
        secret_scope,
        column_mapping=column_mapping_parsed,
        column_thresholds=column_thresholds_parsed,
    )

    aggregates_objs = None
    if include_aggregates:
        if aggregates_json and aggregates_json.strip():
            agg_list = json.loads(aggregates_json)
            aggregates_objs = [
                Aggregate(
                    type=a["type"],
                    agg_columns=a["agg_columns"],
                    group_by_columns=a.get("group_by_columns"),
                )
                for a in agg_list
            ]
        else:
            aggregates_objs = get_aggregates(
                source_catalog,
                source_schema,
                source_table,
                secret_scope,
                column_mapping=column_mapping_parsed,
                column_thresholds=column_thresholds_parsed,
            )

    table_recon = TableRecon(
        tables=[
            Table(
                source_name=source_table,
                target_name=target_table,
                join_columns=pk_split if pk_split else None,
                transformations=transformations,
                select_columns=select_columns,
                drop_columns=drop_columns,
                column_mapping=column_mapping_objs,
                column_thresholds=column_thresholds_objs,
                filters=Filters(source=filters_src, target=filters_tgt),
                aggregates=aggregates_objs,
            )
        ],
    )

    def _run_aggregate_recon():
        if not (include_aggregates and aggregates_objs):
            return
        try:
            reconcile_config_agg = ReconcileConfig(
                data_source=source_system,
                report_type="aggregate",
                secret_scope=secret_scope,
                database_config=DatabaseConfig(
                    source_catalog=source_catalog,
                    source_schema=source_schema,
                    target_catalog=target_catalog,
                    target_schema=target_schema,
                ),
                metadata_config=ReconcileMetadataConfig(
                    catalog=lakebridge_catalog,
                    schema=lakebridge_schema,
                ),
            )
            TriggerReconAggregateService.trigger_recon_aggregates(
                ws, spark, table_recon, reconcile_config_agg
            )
            print(f"  Aggregate reconcile complete for {target_table} ({len(aggregates_objs)} rules)")
        except Exception as agg_e:
            print(f"  Aggregate reconcile error for {target_table}: {agg_e}")
            traceback.print_exc()

    try:
        result = TriggerReconService.trigger_recon(ws, spark, table_recon, reconcile_config)
        recon_id = result.recon_id
        _run_aggregate_recon()
        for r in result.results:
            row_status = r.status.row
            column_status = r.status.column
            schema_status = r.status.schema
            if row_status and report_type == "row":
                status = "passed"
            elif row_status and column_status:
                status = "passed"
            else:
                status = "failed"
            return (
                datetime.now(), label, target_catalog, target_schema, target_table,
                status, recon_id, row_status, column_status, schema_status, None,
            )
    except ReconciliationException as e:
        recon_id = e.reconcile_output.recon_id
        _run_aggregate_recon()
        for r in e.reconcile_output.results:
            row_status = r.status.row
            column_status = r.status.column
            schema_status = r.status.schema
            if row_status and report_type == "row":
                status = "passed"
            elif row_status and column_status:
                status = "passed"
            else:
                status = "failed"
            return (
                datetime.now(), label, target_catalog, target_schema, target_table,
                status, recon_id, row_status, column_status, schema_status, str(e),
            )
    except Exception as e:
        traceback.print_exc()
        return (
            datetime.now(), label, target_catalog, target_schema, target_table,
            "failed", None, None, None, None, str(e),
        )
