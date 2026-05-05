# Databricks notebook source
# MAGIC %md
# MAGIC ## SQL Server Aggregate Rule Generator
# MAGIC
# MAGIC Queries `INFORMATION_SCHEMA.COLUMNS` on SQL Server (via JDBC) and builds
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
# MAGIC **Depends on:** `_read_jdbc()` defined in `sql_server_transformation_query_generator`
# MAGIC (already `%run`-imported before this notebook is imported).

# COMMAND ----------

from databricks.labs.lakebridge.reconcile.recon_config import Aggregate

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
    secret_scope,
    column_mapping=None,
    column_thresholds=None,
) -> list:
    """Return a list of Aggregate objects derived from SQL Server INFORMATION_SCHEMA."""
    query = (
        f"SELECT COLUMN_NAME, DATA_TYPE "
        f"FROM INFORMATION_SCHEMA.COLUMNS "
        f"WHERE TABLE_SCHEMA = '{source_schema}' "
        f"AND TABLE_NAME = '{source_table}' "
        f"AND TABLE_CATALOG = '{source_database}' "
        f"ORDER BY ORDINAL_POSITION"
    )
    df = _read_jdbc(secret_scope, query)

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
