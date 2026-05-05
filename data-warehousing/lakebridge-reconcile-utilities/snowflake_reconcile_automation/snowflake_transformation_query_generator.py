# Databricks notebook source
# MAGIC %md
# MAGIC ## Snowflake ↔ Databricks Transformation Query Generator
# MAGIC
# MAGIC Lakebridge reconciliation compares **source** (Snowflake via the Snowflake Spark connector)
# MAGIC against **target** (Databricks Delta) by converting both sides to a common string
# MAGIC representation, then checking equality. The transformations below are necessary because each
# MAGIC platform renders the same logical value differently in its native types.
# MAGIC
# MAGIC ### Why each cast is needed
# MAGIC
# MAGIC | Type Family | Source (Snowflake SQL) | Target (Spark SQL) | Why |
# MAGIC |---|---|---|---|
# MAGIC | **Integer / Numeric** (`NUMBER`, `INT`, `BIGINT`, `DECIMAL`) | `CAST(CAST(col AS NUMBER(38,6)) AS VARCHAR)` | `cast(cast(col as decimal(38,6)) as string)` | Normalizing through a shared precision ensures integers and decimals render identically regardless of declared scale. |
# MAGIC | **Float / Double / Real** (`FLOAT`, `DOUBLE`, `DOUBLE PRECISION`, `REAL`) | Fixed-point for `<1E32`, else scientific | Same pattern on Spark (`format_number` / `printf`) | Snowflake's FLOAT is an 8-byte double. Guarded fixed-point keeps normal values readable; scientific notation for large magnitudes matches Spark. |
# MAGIC | **Text** (`TEXT`, `VARCHAR`, `CHAR`, `STRING`) | `TRIM(CAST(col AS VARCHAR))` | `trim(cast(col as string))` | Snowflake is UTF-8 native — no encoding workaround needed. `TRIM` normalizes fixed-width padding. |
# MAGIC | **Date** | `TO_CHAR(col, 'YYYY-MM-DD')` | `date_format(col, 'yyyy-MM-dd')` | ISO date form on both sides. |
# MAGIC | **Time** | `TO_CHAR(col, 'HH24:MI:SS')` | `substr(cast(col as string), 1, 8)` | Second precision; Spark renders TIME as `HH:mm:ss.SSS...` — truncate to match. |
# MAGIC | **Timestamp** (`TIMESTAMP_NTZ`, `TIMESTAMP_LTZ`, `TIMESTAMP_TZ`) | `TO_CHAR(col, 'YYYY-MM-DD HH24:MI:SS.FF3')` | `date_format(col, 'yyyy-MM-dd HH:mm:ss.SSS')` | Millisecond precision; Snowflake's FF3 = 3 fractional digits matches Spark's SSS. |
# MAGIC | **Boolean** | `CAST(IFF(col, 1, 0) AS VARCHAR)` | `cast(cast(col as int) as string)` | Snowflake BOOLEAN renders as `TRUE`/`FALSE`; Databricks as `true`/`false`. Casting through INT normalizes to `0`/`1`. |
# MAGIC | **Binary** | `HEX_ENCODE(col)` | `hex(col)` | Hex string without prefix on both sides. Snowflake `HEX_ENCODE` returns uppercase; Spark `hex` also uppercase. |
# MAGIC | **VARIANT / OBJECT / ARRAY** | `TO_JSON(col)` | `cast(col as string)` | Canonical JSON text comparison. |
# MAGIC
# MAGIC ### NULL handling
# MAGIC
# MAGIC Every transformation wraps with `COALESCE(..., '_null_recon_')`. This is required because `NULL = NULL`
# MAGIC returns `NULL` (falsy) in SQL, so NULLs would always appear as mismatches. The sentinel value ensures
# MAGIC NULL-to-NULL comparisons return true.
# MAGIC
# MAGIC ### Note on Unicode
# MAGIC
# MAGIC Snowflake stores text as UTF-8 natively and Lakebridge applies `sha256_partial` on both sides
# MAGIC for the Snowflake path, so Unicode columns compare cleanly without the encoding-mismatch
# MAGIC pitfalls that affect the T-SQL path (see upstream issue
# MAGIC `databrickslabs/lakebridge#1619`).

# COMMAND ----------

from databricks.labs.lakebridge.reconcile.recon_config import (
    Table,
    ColumnMapping,
    Transformation,
    ColumnThresholds,
    JdbcReaderOptions,
    Filters,
    Aggregate,
)

# COMMAND ----------


def _get_secret_or_none(secret_scope, key):
    try:
        return dbutils.secrets.get(scope=secret_scope, key=key)
    except Exception:
        return None


def _pem_to_spark_option(pem_text, pem_password=None):
    # The Snowflake Spark connector's `pem_private_key` option expects the
    # base64 body of a PKCS#8 PEM with the BEGIN/END markers stripped and all
    # newlines removed. Passing the raw PEM content causes "Input PEM private
    # key is invalid". Mirrors Lakebridge's SnowflakeDataSource._get_private_key.
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import serialization
    pwd_bytes = pem_password.encode("utf-8") if pem_password else None
    p_key = serialization.load_pem_private_key(pem_text.encode("utf-8"), pwd_bytes, backend=default_backend())
    pkb = p_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    return "".join(pkb.strip().split("\n")[1:-1])


def _snowflake_options(secret_scope):
    opts = {
        "sfUrl": dbutils.secrets.get(scope=secret_scope, key="sfUrl"),
        "sfUser": dbutils.secrets.get(scope=secret_scope, key="sfUser"),
        "sfDatabase": dbutils.secrets.get(scope=secret_scope, key="sfDatabase"),
        "sfSchema": dbutils.secrets.get(scope=secret_scope, key="sfSchema"),
        "sfWarehouse": dbutils.secrets.get(scope=secret_scope, key="sfWarehouse"),
        "sfRole": dbutils.secrets.get(scope=secret_scope, key="sfRole"),
    }
    # PEM keypair preferred; fall back to sfPassword if the key is absent.
    pem_key = _get_secret_or_none(secret_scope, "pem_private_key")
    if pem_key:
        pem_pwd = _get_secret_or_none(secret_scope, "pem_private_key_password")
        opts["pem_private_key"] = _pem_to_spark_option(pem_key, pem_pwd)
    else:
        opts["sfPassword"] = dbutils.secrets.get(scope=secret_scope, key="sfPassword")
    return opts


def _read_snowflake(secret_scope, query):
    return (
        spark.read.format("snowflake")
        .options(**_snowflake_options(secret_scope))
        .option("query", query)
        .load()
    )


# COMMAND ----------


def get_transformations(
    source_database,
    source_schema,
    source_table,
    secret_scope,
    column_mapping=None,
    column_thresholds=None,
):
    """Query Snowflake INFORMATION_SCHEMA.COLUMNS and build Transformation objects per column data type.

    The source-side expressions use Snowflake SQL functions (TO_CHAR, CAST, COALESCE, HEX_ENCODE, TO_JSON).
    The target-side expressions use Databricks SQL / Spark SQL equivalents.

    Snowflake's INFORMATION_SCHEMA stores unquoted identifiers in upper case, so we compare against
    UPPER() of the widget values.
    """

    query = (
        f"SELECT COLUMN_NAME, DATA_TYPE "
        f"FROM {source_database}.INFORMATION_SCHEMA.COLUMNS "
        f"WHERE TABLE_SCHEMA = UPPER('{source_schema}') "
        f"AND TABLE_NAME = UPPER('{source_table}') "
        f"AND TABLE_CATALOG = UPPER('{source_database}') "
        f"ORDER BY ORDINAL_POSITION"
    )
    df = _read_snowflake(secret_scope, query)

    # Types that cannot be meaningfully reconciled across platforms.
    # GEOGRAPHY/GEOMETRY produce platform-specific WKT/GeoJSON representations.
    # VECTOR is Snowflake-specific with no Databricks equivalent here.
    _SKIP_TYPES = {"geography", "geometry", "vector"}

    # Snowflake returns upper-case column names by default; handle either.
    col_name_field = "COLUMN_NAME" if "COLUMN_NAME" in df.columns else "column_name"
    data_type_field = "DATA_TYPE" if "DATA_TYPE" in df.columns else "data_type"

    # Build source→target column name mapping for renamed columns.
    _col_map = {}
    if column_mapping:
        _col_map = {m["source_name"]: m["target_name"] for m in column_mapping}

    # Columns with thresholds should NOT have transformations — Lakebridge compares
    # raw numeric values directly when thresholds are set.
    _threshold_cols = set()
    if column_thresholds:
        _threshold_cols = {t["column_name"] for t in column_thresholds}

    transformations = []
    skipped = []
    for row in df.select(col_name_field, data_type_field).collect():
        col_name = row[0]
        tgt_name = _col_map.get(col_name, col_name)
        data_type = row[1].lower()

        if data_type in _SKIP_TYPES:
            skipped.append((col_name, data_type))
            continue

        if col_name in _threshold_cols or tgt_name in _threshold_cols:
            continue

        # Snowflake quotes identifiers are case-sensitive; unquoted are upper-cased.
        # The column names coming back from INFORMATION_SCHEMA are already upper-case
        # and reference the stored column, so we use them unquoted on the source side.

        if data_type in ("number", "decimal", "numeric", "int", "integer", "bigint",
                         "smallint", "tinyint", "byteint"):
            # All numeric types in Snowflake are stored internally as NUMBER.
            # Normalize through NUMBER(38,6) to get consistent decimal rendering.
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=(
                        f"COALESCE("
                        f"CAST(CAST({col_name} AS NUMBER(38,6)) AS VARCHAR)"
                        f", '_null_recon_')"
                    ),
                    target=(
                        f"coalesce("
                        f"cast(cast({tgt_name} as decimal(38,6)) as string)"
                        f", '_null_recon_')"
                    ),
                )
            )

        elif data_type in ("float", "float4", "float8", "double", "double precision", "real"):
            # Snowflake's FLOAT/DOUBLE/REAL are all 8-byte doubles. Use fixed-point
            # rendering for normal-range values and scientific for large magnitudes,
            # so source and target produce identical string representations.
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=(
                        f"COALESCE("
                        f"CASE WHEN ABS({col_name}) < 1E32 AND {col_name} IS NOT NULL "
                        f"THEN TO_CHAR(CAST({col_name} AS NUMBER(38,6))) "
                        f"WHEN {col_name} IS NOT NULL "
                        f"THEN LOWER(TO_CHAR({col_name}, 'TM')) END"
                        f", '_null_recon_')"
                    ),
                    target=(
                        f"coalesce("
                        f"case when abs({tgt_name}) < 1E32 and {tgt_name} is not null "
                        f"then regexp_replace("
                        f"regexp_replace(format_number({tgt_name}, 6), ',', '')"
                        f", '^-(0\\\\.0+)$', '$1') "
                        f"when {tgt_name} is not null then "
                        f"regexp_replace("
                        f"regexp_replace("
                        f"regexp_replace(lower(printf('%.15e', {tgt_name})), 'e\\\\+', 'e')"
                        f", '0+e', 'e')"
                        f", '\\\\.e', 'e') end"
                        f", '_null_recon_')"
                    ),
                )
            )

        elif data_type in ("text", "varchar", "char", "character", "string"):
            # Snowflake is UTF-8 native; no encoding workaround needed.
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=f"COALESCE(TRIM(CAST({col_name} AS VARCHAR)), '_null_recon_')",
                    target=f"coalesce(trim(cast({tgt_name} as string)), '_null_recon_')",
                )
            )

        elif data_type == "date":
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=f"COALESCE(TO_CHAR({col_name}, 'YYYY-MM-DD'), '_null_recon_')",
                    target=f"coalesce(date_format({tgt_name}, 'yyyy-MM-dd'), '_null_recon_')",
                )
            )

        elif data_type == "time":
            # Second precision; Spark's time-as-string may include microseconds.
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=f"COALESCE(TO_CHAR({col_name}, 'HH24:MI:SS'), '_null_recon_')",
                    target=f"coalesce(substr(cast({tgt_name} as string), 1, 8), '_null_recon_')",
                )
            )

        elif data_type in ("timestamp_ntz", "timestamp", "datetime"):
            # Millisecond precision matches Spark's SSS.
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=f"COALESCE(TO_CHAR({col_name}, 'YYYY-MM-DD HH24:MI:SS.FF3'), '_null_recon_')",
                    target=f"coalesce(date_format({tgt_name}, 'yyyy-MM-dd HH:mm:ss.SSS'), '_null_recon_')",
                )
            )

        elif data_type in ("timestamp_ltz", "timestamp_tz"):
            # CONVERT_TIMEZONE is avoided here because Lakebridge's SQL transpiler
            # round-trips it through a custom ConvertTimeZone expression whose default
            # serialization produces CONVERT_TIME_ZONE (invalid Snowflake function).
            # Instead, cast the zoned timestamp to TIMESTAMP_NTZ, which strips the
            # offset while preserving wall-clock components. Targets that land in
            # Databricks as STRING (common for DATETIMEOFFSET → STRING mappings) are
            # normalized by taking the first 19 chars and replacing the ISO-8601
            # 'T' separator with a space.
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=(
                        f"COALESCE("
                        f"TO_CHAR(CAST({col_name} AS TIMESTAMP_NTZ), 'YYYY-MM-DD HH24:MI:SS')"
                        f", '_null_recon_')"
                    ),
                    target=(
                        f"coalesce("
                        f"replace(substr(cast({tgt_name} as string), 1, 19), 'T', ' ')"
                        f", '_null_recon_')"
                    ),
                )
            )

        elif data_type == "boolean":
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=(
                        f"CASE WHEN {col_name} IS NULL THEN '_null_recon_' "
                        f"WHEN {col_name} THEN '1' ELSE '0' END"
                    ),
                    target=f"coalesce(cast(cast({tgt_name} as int) as string), '_null_recon_')",
                )
            )

        elif data_type in ("binary", "varbinary"):
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=f"COALESCE(HEX_ENCODE({col_name}), '_null_recon_')",
                    target=f"coalesce(hex({tgt_name}), '_null_recon_')",
                )
            )

        elif data_type in ("variant", "object", "array"):
            # TO_JSON gives a canonical JSON text representation on the Snowflake side.
            # Target side assumes the Spark column is stored as a JSON STRING; if it is
            # stored as STRUCT/MAP/ARRAY instead, use `to_json({tgt_name})` on the target.
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=f"COALESCE(TO_JSON({col_name}), '_null_recon_')",
                    target=f"coalesce(cast({tgt_name} as string), '_null_recon_')",
                )
            )

        else:
            # Fallback: TO_VARCHAR handles most remaining scalar types.
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=f"COALESCE(TRIM(TO_VARCHAR({col_name})), '_null_recon_')",
                    target=f"coalesce(trim(cast({tgt_name} as string)), '_null_recon_')",
                )
            )

    if skipped:
        print(f"Skipped {len(skipped)} columns with non-reconcilable types:")
        for col_name, dtype in skipped:
            print(f"  {col_name} ({dtype})")

    return transformations
