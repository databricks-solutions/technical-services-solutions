# Databricks notebook source
# MAGIC %md
# MAGIC ## Snowflake Aggregate Rule Generator
# MAGIC
# MAGIC Queries `INFORMATION_SCHEMA.COLUMNS` on Snowflake and builds `Aggregate` rule
# MAGIC objects for each column, keyed by data type:
# MAGIC
# MAGIC | Type family | Aggregates generated |
# MAGIC |---|---|
# MAGIC | Numeric (`NUMBER`, `INT`, `BIGINT`, `FLOAT`, `DOUBLE`, etc.) | `count`, `sum`, `min`, `max` |
# MAGIC | Date / Timestamp (`DATE`, `TIME`, `TIMESTAMP_*`) | `count`, `min`, `max` |
# MAGIC | All other types (text, boolean, binary, variant, etc.) | `count` |
# MAGIC
# MAGIC `count` on every column catches NULL-skew and missing-row divergence independently
# MAGIC of the row-hash comparison. `sum`/`min`/`max` on numeric columns surface value
# MAGIC drift even when a row-count check would otherwise pass.
# MAGIC
# MAGIC Columns present in `column_thresholds` are skipped — Lakebridge compares those
# MAGIC numerically using the threshold bounds, not via aggregate rules.
# MAGIC
# MAGIC **Depends on:** `_read_snowflake()` defined in `snowflake_transformation_query_generator`
# MAGIC (already `%run`-imported before this notebook is imported).

# COMMAND ----------

from databricks.labs.lakebridge.reconcile.recon_config import Aggregate

# COMMAND ----------

_AGG_NUMERIC_TYPES = frozenset({
    "number", "decimal", "numeric",
    "int", "integer", "bigint", "smallint", "tinyint", "byteint",
    "float", "float4", "float8", "double", "double precision", "real",
})

_AGG_DATETIME_TYPES = frozenset({
    "date", "time",
    "timestamp_ntz", "timestamp", "datetime",
    "timestamp_ltz", "timestamp_tz",
})

_AGG_SKIP_TYPES = frozenset({"geography", "geometry", "vector"})


def get_aggregates(
    source_database,
    source_schema,
    source_table,
    secret_scope,
    column_mapping=None,
    column_thresholds=None,
) -> list:
    """Return a list of Aggregate objects derived from Snowflake INFORMATION_SCHEMA."""
    query = (
        f"SELECT COLUMN_NAME, DATA_TYPE "
        f"FROM {source_database}.INFORMATION_SCHEMA.COLUMNS "
        f"WHERE TABLE_SCHEMA = UPPER('{source_schema}') "
        f"AND TABLE_NAME = UPPER('{source_table}') "
        f"AND TABLE_CATALOG = UPPER('{source_database}') "
        f"ORDER BY ORDINAL_POSITION"
    )
    df = _read_snowflake(secret_scope, query)

    col_name_field = "COLUMN_NAME" if "COLUMN_NAME" in df.columns else "column_name"
    data_type_field = "DATA_TYPE" if "DATA_TYPE" in df.columns else "data_type"

    _col_map = {m["source_name"]: m["target_name"] for m in column_mapping} if column_mapping else {}
    _threshold_cols = {t["column_name"] for t in column_thresholds} if column_thresholds else set()

    aggregates = []
    for row in df.select(col_name_field, data_type_field).collect():
        col_name = row[0]
        tgt_name = _col_map.get(col_name, col_name)
        data_type = row[1].lower()

        if data_type in _AGG_SKIP_TYPES:
            continue
        if col_name in _threshold_cols or tgt_name in _threshold_cols:
            continue

        aggregates.append(Aggregate(type="count", agg_columns=[col_name]))

        if data_type in _AGG_NUMERIC_TYPES:
            aggregates.append(Aggregate(type="sum", agg_columns=[col_name]))
            aggregates.append(Aggregate(type="min", agg_columns=[col_name]))
            aggregates.append(Aggregate(type="max", agg_columns=[col_name]))
        elif data_type in _AGG_DATETIME_TYPES:
            aggregates.append(Aggregate(type="min", agg_columns=[col_name]))
            aggregates.append(Aggregate(type="max", agg_columns=[col_name]))

    return aggregates
