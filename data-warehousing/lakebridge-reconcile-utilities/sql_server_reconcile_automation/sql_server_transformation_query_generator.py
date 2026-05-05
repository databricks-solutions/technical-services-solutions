# Databricks notebook source
# MAGIC %md
# MAGIC ## SQL Server ↔ Databricks Transformation Query Generator
# MAGIC
# MAGIC Lakebridge reconciliation compares **source** (SQL Server via JDBC) against **target** (Databricks Delta)
# MAGIC by converting both sides to a common string representation, then checking equality. The transformations
# MAGIC below are necessary because each platform renders the same logical value differently in its native types.
# MAGIC
# MAGIC ### Why each cast is needed
# MAGIC
# MAGIC | Type Family | Source (T-SQL) | Target (Spark SQL) | Why |
# MAGIC |---|---|---|---|
# MAGIC | **Integer** (`INT`, `BIGINT`, `SMALLINT`, `TINYINT`) | `CAST(col AS VARCHAR(MAX))` | `cast(col as string)` | Straightforward — both render integers identically as strings. |
# MAGIC | **Float/Real** (`FLOAT`, `REAL`) | `STR(col, 40, 6)` if &lt; 1E32, else `CONVERT(VARCHAR(50), col, 2)` | `format_number(col, 6)` if &lt; 1E32, else `lower(printf('%.15e', col))` | Values &lt; 1E32 are rendered as fixed-point (6dp). Larger values use scientific notation — style 2 on T-SQL and `printf %.15e` on Spark both produce 16 significant digits. |
# MAGIC | **Decimal/Money** (`DECIMAL`, `NUMERIC`, `MONEY`, `SMALLMONEY`) | `CAST(CAST(col AS DECIMAL(38,6)) AS VARCHAR(MAX))` | `cast(cast(col as decimal(38,6)) as string)` | Normalizing through `DECIMAL(38,6)` ensures identical precision on both sides. |
# MAGIC | **All string types** (`VARCHAR`, `CHAR`, `TEXT`, `NVARCHAR`, `NCHAR`, `NTEXT`) | `TRIM(CAST(col AS NVARCHAR(MAX)))` | `trim(cast(col as string))` | Always cast to `NVARCHAR(MAX)`. For `varchar`/`char`/`text` this converts CP1252 → UTF-16, preventing Arrow encoding errors on non-ASCII data. For `nvarchar`/`nchar`/`ntext` it's a harmless no-op. `TRIM` normalizes `CHAR(n)` padding. |
# MAGIC | **Date** | `CONVERT(VARCHAR(10), col, 101)` | `date_format(col, 'MM/dd/yyyy')` | SQL Server default date string is `Jan 15 2024`; Spark's is `2024-01-15`. Style 101 forces `MM/DD/YYYY` on both sides. |
# MAGIC | **Time** | `CONVERT(VARCHAR(12), col, 108)` | `cast(col as string)` | Style 108 = `HH:mm:ss`, matching Spark's time string output. |
# MAGIC | **DateTime/DateTime2/SmallDatetime** | `CONVERT(VARCHAR(23), col, 120)` | `cast(col as string)` | Style 120 = ODBC canonical `yyyy-MM-dd HH:mm:ss`. Without this, SQL Server renders `Jan 15 2024 10:30AM`. |
# MAGIC | **DateTimeOffset** | `CONVERT(VARCHAR(34), col, 127)` | `date_format(col, "yyyy-MM-dd'T'HH:mm:ss.SSSXXX")` | Style 127 = ISO 8601 with timezone. Both sides produce `yyyy-MM-ddTHH:mm:ss.fff+HH:MM`. |
# MAGIC | **BIT → BOOLEAN** | `CAST(CAST(col AS INT) AS VARCHAR)` | `cast(cast(col as int) as string)` | SQL Server BIT renders as `0`/`1`; Databricks BOOLEAN renders as `true`/`false`. Casting through INT normalizes to `0`/`1`. |
# MAGIC | **Binary/VarBinary** | `CONVERT(VARCHAR(MAX), col, 2)` | `hex(col)` | Style 2 = hex without `0x` prefix (e.g. `DEADBEEF`), matching Spark's `hex()`. |
# MAGIC | **UniqueIdentifier** | `LOWER(CAST(col AS VARCHAR(36)))` | `lower(cast(col as string))` | SQL Server may return UUIDs in uppercase; `LOWER()` normalizes both sides. |
# MAGIC | **XML** | `CAST(col AS VARCHAR(MAX))` | `cast(col as string)` | Raw XML text comparison. Whitespace differences may cause false mismatches. |
# MAGIC
# MAGIC ### NULL handling
# MAGIC
# MAGIC Every transformation wraps with `COALESCE(..., '_null_recon_')`. This is required because `NULL = NULL`
# MAGIC returns `NULL` (falsy) in SQL, so NULLs would always appear as mismatches. The sentinel value ensures
# MAGIC NULL-to-NULL comparisons return true.

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


def _build_jdbc_url(secret_scope):
    host = dbutils.secrets.get(scope=secret_scope, key="host")
    port = dbutils.secrets.get(scope=secret_scope, key="port")
    database = dbutils.secrets.get(scope=secret_scope, key="database")
    encrypt = dbutils.secrets.get(scope=secret_scope, key="encrypt")
    trust_cert = dbutils.secrets.get(scope=secret_scope, key="trustServerCertificate")
    return (
        f"jdbc:sqlserver://{host}:{port};"
        f"databaseName={database};"
        f"encrypt={encrypt};"
        f"trustServerCertificate={trust_cert};"
    )


def _read_jdbc(secret_scope, query):
    jdbc_url = _build_jdbc_url(secret_scope)
    user = dbutils.secrets.get(scope=secret_scope, key="user")
    password = dbutils.secrets.get(scope=secret_scope, key="password")
    return (
        spark.read.format("jdbc")
        .option("url", jdbc_url)
        .option("driver", "com.microsoft.sqlserver.jdbc.SQLServerDriver")
        .option("query", query)
        .option("user", user)
        .option("password", password)
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
    """Query SQL Server INFORMATION_SCHEMA.COLUMNS and build Transformation objects per column data type.

    The source-side expressions use T-SQL functions (CONVERT, CAST, COALESCE).
    The target-side expressions use Databricks SQL / Spark SQL equivalents.
    """

    query = (
        f"SELECT COLUMN_NAME, DATA_TYPE "
        f"FROM INFORMATION_SCHEMA.COLUMNS "
        f"WHERE TABLE_SCHEMA = '{source_schema}' "
        f"AND TABLE_NAME = '{source_table}' "
        f"AND TABLE_CATALOG = '{source_database}'"
    )
    df = _read_jdbc(secret_scope, query)

    # Types that cannot be meaningfully reconciled across platforms.
    # timestamp/rowversion is a system-generated binary counter, not a real timestamp.
    # geometry/geography produce platform-specific WKT representations.
    # hierarchyid requires .ToString() on SQL Server with no Databricks equivalent.
    _SKIP_TYPES = {"geometry", "geography", "hierarchyid"}

    # Build source→target column name mapping for renamed columns.
    # The source expression always uses the source column name (col_name),
    # and the target expression uses the mapped target name (tgt_name).
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
    for row in df.select("COLUMN_NAME", "DATA_TYPE").collect():
        col_name = row[0]
        tgt_name = _col_map.get(col_name, col_name)
        data_type = row[1].lower()

        if data_type in _SKIP_TYPES:
            skipped.append((col_name, data_type))
            continue

        # Skip transformations for columns with thresholds — Lakebridge
        # handles numeric comparison natively for threshold columns.
        if col_name in _threshold_cols or tgt_name in _threshold_cols:
            continue

        if data_type in ("int", "bigint", "smallint", "tinyint"):
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=f"COALESCE(CAST({col_name} AS VARCHAR(MAX)), '_null_recon_')",
                    target=f"coalesce(cast({tgt_name} as string), '_null_recon_')",
                )
            )

        elif data_type == "float":
            # FLOAT (8-byte double) can hold values up to 1.7e+308 which overflow
            # DECIMAL(38,6).  For normal-range values use STR()/format_number(6dp).
            # For large values use CONVERT style 2 (16 significant digits, scientific)
            # on SQL Server and printf %.15e on Spark (both produce 16 sig digits).
            # Note: Spark printf('%.15e', NULL) returns the string "null", not SQL NULL,
            # so we guard with an explicit IS NULL check.
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=(
                        f"COALESCE("
                        f"CASE WHEN ABS({col_name}) < 1E32 AND {col_name} IS NOT NULL "
                        f"THEN LTRIM(STR({col_name}, 40, 6)) "
                        f"WHEN {col_name} IS NOT NULL THEN CONVERT(VARCHAR(50), {col_name}, 2) END"
                        f", '_null_recon_')"
                    ),
                    target=(
                        f"coalesce("
                        f"case when abs({tgt_name}) < 1E32 and {tgt_name} is not null "
                        f"then regexp_replace(format_number({tgt_name}, 6), ',', '') "
                        f"when {tgt_name} is not null then lower(printf('%.15e', {tgt_name})) end"
                        f", '_null_recon_')"
                    ),
                )
            )

        elif data_type == "real":
            # REAL (4-byte single-precision) has only ~7 significant digits.
            # SQL Server promotes REAL→FLOAT, exposing float→double noise.
            # Use CONVERT style 1 (8 sig digits) for small values, style 1 for large.
            # CONVERT style 1 pads exponent to 3 digits (e+038) but Spark uses
            # minimal digits (e+38), so strip leading exponent zeros with REPLACE.
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=(
                        f"COALESCE("
                        f"CASE WHEN ABS({col_name}) < 1E32 AND {col_name} IS NOT NULL "
                        f"THEN LTRIM(STR({col_name}, 40, 6)) "
                        f"WHEN {col_name} IS NOT NULL "
                        f"THEN REPLACE(REPLACE(CONVERT(VARCHAR(50), CAST({col_name} AS FLOAT), 1), 'e+0', 'e+'), 'e-0', 'e-') END"
                        f", '_null_recon_')"
                    ),
                    target=(
                        f"coalesce("
                        f"case when abs({tgt_name}) < 1E32 and {tgt_name} is not null "
                        f"then regexp_replace(format_number({tgt_name}, 6), ',', '') "
                        f"when {tgt_name} is not null then lower(printf('%.7e', {tgt_name})) end"
                        f", '_null_recon_')"
                    ),
                )
            )

        elif data_type in ("decimal", "numeric", "money", "smallmoney"):
            # Normalize through DECIMAL(38,6) and keep all 6 decimal places
            # (previous truncation to 2dp via SUBSTRING lost precision).
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=(
                        f"COALESCE("
                        f"CAST(CAST({col_name} AS DECIMAL(38,6)) AS VARCHAR(MAX))"
                        f", '_null_recon_')"
                    ),
                    target=(
                        f"coalesce("
                        f"cast(cast({tgt_name} as decimal(38,6)) as string)"
                        f", '_null_recon_')"
                    ),
                )
            )

        elif data_type in ("varchar", "char", "text", "nvarchar", "nchar", "ntext"):
            # Always cast to NVARCHAR(MAX) so SQL Server converts CP1252 → UTF-16
            # internally. The JDBC driver then sends UTF-16 → UTF-8, keeping Arrow happy.
            # For nvarchar/nchar/ntext this is a no-op; for varchar/char/text it is the
            # actual fix that prevents encoding errors on non-ASCII data.
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=f"COALESCE(TRIM(CAST({col_name} AS NVARCHAR(MAX))), '_null_recon_')",
                    target=f"coalesce(trim(cast({tgt_name} as string)), '_null_recon_')",
                )
            )

        elif data_type == "date":
            # Style 101 = MM/DD/YYYY, matches Lakebridge engine expression_generator.py
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=f"COALESCE(CONVERT(VARCHAR(10), {col_name}, 101), '_null_recon_')",
                    target=f"coalesce(date_format({tgt_name}, 'MM/dd/yyyy'), '_null_recon_')",
                )
            )

        elif data_type == "time":
            # Style 114 = HH:mm:ss.mmm (includes milliseconds).
            # Databricks stores time as STRING with up to 7 fractional digits;
            # truncate target to match SQL Server's millisecond precision.
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=f"COALESCE(CONVERT(VARCHAR(12), {col_name}, 114), '_null_recon_')",
                    target=f"coalesce(substr(cast({tgt_name} as string), 1, 12), '_null_recon_')",
                )
            )

        elif data_type == "datetimeoffset":
            # Normalize both sides to UTC at second precision.
            # SQL Server: SWITCHOFFSET converts to +00:00, style 120 formats as
            # yyyy-MM-dd HH:mm:ss (no fractional seconds, no offset).
            # Databricks: target stores as STRING like "2024-06-15T14:30:45.1234567-05:00".
            # Parse the local time, convert from its offset to UTC, then format.
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=(
                        f"COALESCE("
                        f"CONVERT(VARCHAR(19), SWITCHOFFSET({col_name}, '+00:00'), 120)"
                        f", '_null_recon_')"
                    ),
                    target=(
                        f"coalesce("
                        f"date_format("
                        f"to_utc_timestamp("
                        f"to_timestamp(substr({tgt_name}, 1, 19), \"yyyy-MM-dd'T'HH:mm:ss\"), "
                        f"concat('GMT', substr({tgt_name}, length({tgt_name}) - 5))"
                        f"), 'yyyy-MM-dd HH:mm:ss')"
                        f", '_null_recon_')"
                    ),
                )
            )

        elif data_type == "datetime2":
            # datetime2 has up to 7 fractional digits. Style 121 = yyyy-MM-dd HH:mm:ss.fff
            # preserves milliseconds. Truncate both sides to milliseconds (23 chars).
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=f"COALESCE(CONVERT(VARCHAR(23), {col_name}, 121), '_null_recon_')",
                    target=f"coalesce(date_format({tgt_name}, 'yyyy-MM-dd HH:mm:ss.SSS'), '_null_recon_')",
                )
            )

        elif data_type in ("datetime", "smalldatetime"):
            # Style 120 = ODBC canonical: yyyy-MM-dd HH:mm:ss (no fractional seconds)
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=f"COALESCE(CONVERT(VARCHAR(19), {col_name}, 120), '_null_recon_')",
                    target=f"coalesce(date_format({tgt_name}, 'yyyy-MM-dd HH:mm:ss'), '_null_recon_')",
                )
            )

        elif data_type == "bit":
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=f"COALESCE(CAST(CAST({col_name} AS INT) AS VARCHAR(MAX)), '_null_recon_')",
                    target=f"coalesce(cast(cast({tgt_name} as int) as string), '_null_recon_')",
                )
            )

        elif data_type in ("binary", "varbinary", "image", "timestamp", "rowversion"):
            # timestamp/rowversion is an 8-byte binary counter, not a date
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=f"COALESCE(CONVERT(VARCHAR(MAX), {col_name}, 2), '_null_recon_')",
                    target=f"coalesce(hex({tgt_name}), '_null_recon_')",
                )
            )

        elif data_type == "uniqueidentifier":
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=f"COALESCE(LOWER(CAST({col_name} AS VARCHAR(36))), '_null_recon_')",
                    target=f"coalesce(lower(cast({tgt_name} as string)), '_null_recon_')",
                )
            )

        elif data_type == "xml":
            # XML can be large; cast to string on both sides for content comparison.
            # Whitespace differences between source and target may cause false mismatches.
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=f"COALESCE(CAST({col_name} AS VARCHAR(MAX)), '_null_recon_')",
                    target=f"coalesce(cast({tgt_name} as string), '_null_recon_')",
                )
            )

        elif data_type == "sql_variant":
            # sql_variant wraps multiple types; extract the base type string representation.
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=f"COALESCE(CAST(SQL_VARIANT_PROPERTY({col_name}, 'BaseType') AS VARCHAR(50)) + ':' + CAST({col_name} AS VARCHAR(MAX)), '_null_recon_')",
                    target=f"coalesce(cast({tgt_name} as string), '_null_recon_')",
                )
            )

        else:
            # Use NVARCHAR(MAX) for safety — unknown types may contain non-ASCII data.
            transformations.append(
                Transformation(
                    column_name=col_name,
                    source=f"COALESCE(TRIM(CAST({col_name} AS NVARCHAR(MAX))), '_null_recon_')",
                    target=f"coalesce(trim(cast({tgt_name} as string)), '_null_recon_')",
                )
            )

    if skipped:
        print(f"Skipped {len(skipped)} columns with non-reconcilable types:")
        for col_name, dtype in skipped:
            print(f"  {col_name} ({dtype})")

    return transformations
