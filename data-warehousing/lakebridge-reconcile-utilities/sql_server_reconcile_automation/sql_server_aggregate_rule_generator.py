# Databricks notebook source
# MAGIC %md
# MAGIC ## SQL Server Aggregate Rule Generator
# MAGIC
# MAGIC Queries `INFORMATION_SCHEMA.COLUMNS` on SQL Server (via UC Connection + `remote_query()`) and builds
# MAGIC `Aggregate` rule objects for each column, keyed by data type:
# MAGIC
# MAGIC | Type family | Aggregates generated |
# MAGIC |---|---|
# MAGIC | Numeric (`INT`, `BIGINT`, `DECIMAL`, `FLOAT`, `MONEY`, etc.) | `count`, `sum`, `min`, `max` |
# MAGIC | Date / Timestamp (`DATE`, `DATETIME`, `DATETIME2`, etc.) | `count`, `min`, `max` |
# MAGIC | All other types (text, bit, binary, etc.) | `count` |
# MAGIC
# MAGIC `count` on every column catches NULL-skew and missing-row divergence independently
# MAGIC of the row-hash comparison. `sum`/`min`/`max` on numeric columns surface value
# MAGIC drift even when a row-count check would otherwise pass.
# MAGIC
# MAGIC Columns present in `column_thresholds` are skipped — Lakebridge compares those
# MAGIC numerically using the threshold bounds, not via aggregate rules.
# MAGIC
# MAGIC **Depends on:** `_remote_query()` defined in `sql_server_transformation_query_generator`
# MAGIC (already `%run`-imported before this notebook is imported).

# COMMAND ----------

from databricks.labs.lakebridge.reconcile.recon_config import Aggregate
from pyspark.sql.functions import col

# COMMAND ----------

_AGG_NUMERIC_TYPES_SS = frozenset({
    "int", "bigint", "smallint", "tinyint",
    "decimal", "numeric",
    "float", "real",
    "money", "smallmoney",
})

_AGG_DATETIME_TYPES_SS = frozenset({
    "date", "time",
    "datetime", "datetime2", "smalldatetime", "datetimeoffset",
})

# SQL Server's rowversion/timestamp is a binary row-version counter, not a real timestamp.
_AGG_SKIP_TYPES_SS = frozenset({
    "xml", "geography", "geometry", "hierarchyid",
    "sql_variant", "rowversion", "timestamp", "image",
})


def get_aggregates(
    source_database,
    source_schema,
    source_table,
    uc_connection_name,
    column_mapping=None,
    column_thresholds=None,
) -> list:
    """Return a list of Aggregate objects derived from SQL Server INFORMATION_SCHEMA."""
    # Read whole INFORMATION_SCHEMA.COLUMNS via `dbtable` and filter on Databricks
    # side. We cannot embed string literals in a `query =>` argument because
    # remote_query() strips them during JDBC pushdown rewrite.
    df = (
        _read_remote_table(uc_connection_name, source_database, "INFORMATION_SCHEMA.COLUMNS")
        .where(
            (col("TABLE_SCHEMA") == source_schema)
            & (col("TABLE_NAME") == source_table)
            & (col("TABLE_CATALOG") == source_database)
        )
        .select("COLUMN_NAME", "DATA_TYPE", "ORDINAL_POSITION")
        .orderBy("ORDINAL_POSITION")
    )

    _col_map = {m["source_name"]: m["target_name"] for m in column_mapping} if column_mapping else {}
    _threshold_cols = {t["column_name"] for t in column_thresholds} if column_thresholds else set()

    aggregates = []
    for row in df.collect():
        col_name = row.COLUMN_NAME
        tgt_name = _col_map.get(col_name, col_name)
        data_type = row.DATA_TYPE.lower()

        if data_type in _AGG_SKIP_TYPES_SS:
            continue
        if col_name in _threshold_cols or tgt_name in _threshold_cols:
            continue

        aggregates.append(Aggregate(type="count", agg_columns=[col_name]))

        if data_type in _AGG_NUMERIC_TYPES_SS:
            aggregates.append(Aggregate(type="sum", agg_columns=[col_name]))
            aggregates.append(Aggregate(type="min", agg_columns=[col_name]))
            aggregates.append(Aggregate(type="max", agg_columns=[col_name]))
        elif data_type in _AGG_DATETIME_TYPES_SS:
            aggregates.append(Aggregate(type="min", agg_columns=[col_name]))
            aggregates.append(Aggregate(type="max", agg_columns=[col_name]))

    return aggregates
