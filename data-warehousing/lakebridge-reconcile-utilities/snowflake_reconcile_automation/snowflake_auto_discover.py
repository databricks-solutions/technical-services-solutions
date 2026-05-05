# Databricks notebook source
# MAGIC %md
# MAGIC # Snowflake Auto-Discovery
# MAGIC
# MAGIC **What it does:** Connects to a Snowflake account via JDBC, discovers base tables and their
# MAGIC primary keys in the specified schema, and MERGEs rows into the configurable Lakebridge metadata
# MAGIC config table (default `table_configs`) that drives the reconciliation pipeline.
# MAGIC
# MAGIC **Why it's important:** This is the **first notebook** you run when setting up reconciliation for a
# MAGIC new Snowflake database. Without it, the downstream notebooks have no idea which tables to compare
# MAGIC or what their primary keys are. It eliminates manual config entry by introspecting
# MAGIC `INFORMATION_SCHEMA.TABLES` and `SHOW PRIMARY KEYS` directly from the source.
# MAGIC
# MAGIC **How it works with the other notebooks:**
# MAGIC 1. **This notebook (auto_discover)** → writes rows to `{lakebridge_catalog}.{lakebridge_schema}.{lakebridge_config_table}`
# MAGIC 2. **snowflake_recon_wrapper** → reads the same config table (via matching `lakebridge_*` widgets), filters rows, iterates per table
# MAGIC 3. **snowflake_recon_main** → called by the wrapper; builds Lakebridge `ReconcileConfig` and `TableRecon` objects, then triggers reconciliation
# MAGIC 4. **snowflake_transformation_query_generator** → called by recon_main; reads column metadata from Snowflake and builds per-column type-aware transformations
# MAGIC
# MAGIC Running this notebook again is safe — it uses MERGE to upsert rows, so existing config is updated
# MAGIC rather than duplicated.
# MAGIC
# MAGIC **After running:** review the rows written to `table_configs` and edit per-table overrides
# MAGIC (`primary_key`, `source_filters`, `databricks_filters`, `select_columns`, `drop_columns`,
# MAGIC `column_mapping`, `column_thresholds`) before invoking `snowflake_recon_wrapper`.
# MAGIC
# MAGIC **Parameters:**
# MAGIC - `secret_scope` — Databricks secret scope with Snowflake Spark connector credentials
# MAGIC - `source_database` / `source_schema` — Snowflake database and schema to introspect
# MAGIC - `target_catalog` / `target_schema` — Databricks target catalog/schema where the reconciled copies live
# MAGIC - `lakebridge_catalog` / `lakebridge_schema` — Unity Catalog location for reconciliation metadata tables
# MAGIC - `lakebridge_config_table` — Delta table written by this notebook (default: `table_configs`)
# MAGIC - `label` — Tag applied to every config row written by this run; used later by the wrapper to select a subset
# MAGIC - `table_filter` — Table name LIKE filter applied to the source (default `%`); ignored when `specific_tables` is non-empty
# MAGIC - `specific_tables` — Optional comma-separated exact names; when set, overrides `table_filter`

# COMMAND ----------

# MAGIC %pip install -q snowflake-connector-python

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("secret_scope", "", "Secret Scope")
dbutils.widgets.text("source_database", "", "Snowflake Database (catalog)")
dbutils.widgets.text("source_schema", "PUBLIC", "Snowflake Schema")
dbutils.widgets.text("target_catalog", "", "Databricks Target Catalog")
dbutils.widgets.text("target_schema", "", "Databricks Target Schema")
dbutils.widgets.text("lakebridge_catalog", "", "Lakebridge Metadata Catalog")
dbutils.widgets.text("lakebridge_schema", "reconcile", "Lakebridge Metadata Schema")
dbutils.widgets.text("lakebridge_config_table", "table_configs", "Metadata config Delta table name")
dbutils.widgets.text("user_suffix", "", "User suffix for config table (blank = auto-derive from current_user())")
dbutils.widgets.text("label", "", "Label for this reconciliation group")
dbutils.widgets.text("table_filter", "%", "Table name LIKE filter (used when specific_tables is empty)")
dbutils.widgets.text(
    "specific_tables",
    "",
    "Optional comma-separated table names (non-empty overrides table_filter)",
)

secret_scope = dbutils.widgets.get("secret_scope")
source_database = dbutils.widgets.get("source_database")
source_schema = dbutils.widgets.get("source_schema")
target_catalog = dbutils.widgets.get("target_catalog")
target_schema = dbutils.widgets.get("target_schema")
lakebridge_catalog = dbutils.widgets.get("lakebridge_catalog")
lakebridge_schema = dbutils.widgets.get("lakebridge_schema")
lakebridge_config_table = (
    dbutils.widgets.get("lakebridge_config_table") or "table_configs"
).lower()
import re as _re
_raw_suffix = (dbutils.widgets.get("user_suffix") or "").strip()
if not _raw_suffix:
    _raw_suffix = spark.sql("SELECT current_user()").first()[0].split("@")[0]
_user_suffix = _re.sub(r"[^a-z0-9]+", "_", _raw_suffix.lower()).strip("_")
lakebridge_config_table = f"{lakebridge_config_table}_{_user_suffix}"
label = dbutils.widgets.get("label").lower()
table_filter = dbutils.widgets.get("table_filter") or "%"
specific_tables_raw = dbutils.widgets.get("specific_tables") or ""
specific_table_list = [t.strip() for t in specific_tables_raw.split(",") if t.strip()]

# COMMAND ----------


def _get_secret_or_none(key):
    try:
        return dbutils.secrets.get(scope=secret_scope, key=key)
    except Exception:
        return None


def _pem_to_spark_option(pem_text, pem_password=None):
    # The Snowflake Spark connector's `pem_private_key` option expects the
    # base64 body of a PKCS#8 PEM with the BEGIN/END markers stripped and all
    # newlines removed. Passing the raw PEM file content causes "Input PEM
    # private key is invalid". Lakebridge's own SnowflakeDataSource does the
    # same transformation — we mirror it here.
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


def _snowflake_options():
    opts = {
        "sfUrl": dbutils.secrets.get(scope=secret_scope, key="sfUrl"),
        "sfUser": dbutils.secrets.get(scope=secret_scope, key="sfUser"),
        "sfDatabase": dbutils.secrets.get(scope=secret_scope, key="sfDatabase"),
        "sfSchema": dbutils.secrets.get(scope=secret_scope, key="sfSchema"),
        "sfWarehouse": dbutils.secrets.get(scope=secret_scope, key="sfWarehouse"),
        "sfRole": dbutils.secrets.get(scope=secret_scope, key="sfRole"),
    }
    # Prefer PEM keypair auth (Snowflake's recommended service-account method);
    # fall back to sfPassword if pem_private_key is not in the secret scope.
    pem_key = _get_secret_or_none("pem_private_key")
    if pem_key:
        pem_pwd = _get_secret_or_none("pem_private_key_password")
        opts["pem_private_key"] = _pem_to_spark_option(pem_key, pem_pwd)
    else:
        opts["sfPassword"] = dbutils.secrets.get(scope=secret_scope, key="sfPassword")
    return opts


def _read_snowflake(query):
    return (
        spark.read.format("snowflake")
        .options(**_snowflake_options())
        .option("query", query)
        .load()
    )


def _snowflake_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


# COMMAND ----------

# Discover all base tables in the schema (specific_tables IN list overrides table_filter LIKE).
# Snowflake INFORMATION_SCHEMA requires the database qualifier; unquoted identifiers are
# folded to upper case, so we compare against upper-cased names.

_tables_base = (
    f'SELECT TABLE_NAME '
    f'FROM {source_database}.INFORMATION_SCHEMA.TABLES '
    f"WHERE TABLE_SCHEMA = UPPER('{source_schema}') "
    f"AND TABLE_CATALOG = UPPER('{source_database}') "
    f"AND TABLE_TYPE = 'BASE TABLE' "
)

if specific_table_list:
    in_clause = ",".join(
        _snowflake_string_literal(n.upper()) for n in specific_table_list
    )
    tables_query = _tables_base + f"AND TABLE_NAME IN ({in_clause}) "
else:
    tables_query = _tables_base + f"AND TABLE_NAME LIKE UPPER('{table_filter}') "

tables_df = _read_snowflake(tables_query)
# Snowflake returns column names in upper case by default
table_col = "TABLE_NAME" if "TABLE_NAME" in tables_df.columns else "table_name"
discovered_from_jdbc = [row[table_col] for row in tables_df.collect()]
by_lower = {}
for name in discovered_from_jdbc:
    by_lower.setdefault(name.lower(), name)

if specific_table_list:
    discovered_tables = []
    for t in specific_table_list:
        actual = by_lower.get(t.lower())
        if actual is None:
            print(
                f"  Warning: table not found or not a BASE TABLE in "
                f"{source_database}.{source_schema}: {t}"
            )
        elif actual not in discovered_tables:
            discovered_tables.append(actual)
else:
    discovered_tables = sorted(discovered_from_jdbc)

print(f"Discovered {len(discovered_tables)} tables in {source_database}.{source_schema}")

# COMMAND ----------

# Discover primary keys for each table and build config rows.
# Snowflake's INFORMATION_SCHEMA does not expose PK columns directly, so use
# `SHOW PRIMARY KEYS IN TABLE`. The Spark connector's preactions + RESULT_SCAN
# pattern is fragile (internal bookkeeping queries can shift LAST_QUERY_ID()),
# so use snowflake-connector-python for a single-session SHOW + fetch.

import snowflake.connector
from urllib.parse import urlparse


def _snowflake_account():
    host = urlparse(dbutils.secrets.get(scope=secret_scope, key="sfUrl")).hostname or ""
    return host.split(".snowflakecomputing.com")[0]


def _snowflake_py_conn():
    kwargs = {
        "user": dbutils.secrets.get(scope=secret_scope, key="sfUser"),
        "account": _snowflake_account(),
        "warehouse": dbutils.secrets.get(scope=secret_scope, key="sfWarehouse"),
        "database": dbutils.secrets.get(scope=secret_scope, key="sfDatabase"),
        "role": dbutils.secrets.get(scope=secret_scope, key="sfRole"),
    }
    # PEM keypair preferred; password fallback. The Python connector expects a
    # DER-encoded private key in the `private_key` kwarg, so load + serialize
    # the PEM we stored in the secret scope.
    pem_key_str = _get_secret_or_none("pem_private_key")
    if pem_key_str:
        from cryptography.hazmat.primitives import serialization
        pem_pwd_str = _get_secret_or_none("pem_private_key_password")
        pwd_bytes = pem_pwd_str.encode("utf-8") if pem_pwd_str else None
        p_key = serialization.load_pem_private_key(
            pem_key_str.encode("utf-8"),
            password=pwd_bytes,
        )
        kwargs["private_key"] = p_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    else:
        kwargs["password"] = dbutils.secrets.get(scope=secret_scope, key="sfPassword")
    return snowflake.connector.connect(**kwargs)


config_rows = []
_pk_conn = _snowflake_py_conn()
try:
    _cur = _pk_conn.cursor()
    for table_name in discovered_tables:
        try:
            _cur.execute(
                f'SHOW PRIMARY KEYS IN TABLE '
                f'"{source_database}"."{source_schema}"."{table_name}"'
            )
            rows = _cur.fetchall()
            # SHOW PRIMARY KEYS columns: created_on, database_name, schema_name,
            # table_name, column_name (4), key_sequence (5), constraint_name,
            # rely, comment
            pk_columns = [r[4] for r in sorted(rows, key=lambda r: r[5])]
        except Exception as e:
            print(f"  Warning: could not read PKs for {table_name}: {e}")
            pk_columns = []

        config_rows.append(
            {
                "label": label,
                "source_catalog": source_database,
                "source_schema": source_schema,
                "source_table": table_name,
                "databricks_catalog": target_catalog,
                "databricks_schema": target_schema,
                "databricks_table": table_name.lower(),
                "primary_key": pk_columns if pk_columns else None,
                "source_filters": None,
                "databricks_filters": None,
                "select_columns": None,
                "drop_columns": None,
                "column_mapping": None,
                "column_thresholds": None,
                "aggregates": None,
            }
        )
finally:
    _pk_conn.close()

print(f"Built {len(config_rows)} config rows")
for r in config_rows:
    pk_display = r["primary_key"] if r["primary_key"] else "(none)"
    print(f"  {r['source_table']} -> {r['databricks_table']}  PK: {pk_display}")

# COMMAND ----------

# Write config rows to a temporary view, then MERGE into metadata config table

from pyspark.sql.types import StructType, StructField, StringType, ArrayType

schema = StructType(
    [
        StructField("label", StringType(), True),
        StructField("source_catalog", StringType(), True),
        StructField("source_schema", StringType(), True),
        StructField("source_table", StringType(), True),
        StructField("databricks_catalog", StringType(), True),
        StructField("databricks_schema", StringType(), True),
        StructField("databricks_table", StringType(), True),
        StructField("primary_key", ArrayType(StringType()), True),
        StructField("source_filters", StringType(), True),
        StructField("databricks_filters", StringType(), True),
        StructField("select_columns", StringType(), True),
        StructField("drop_columns", StringType(), True),
        StructField("column_mapping", StringType(), True),
        StructField("column_thresholds", StringType(), True),
        StructField("aggregates", StringType(), True),
    ]
)

if config_rows:
    staging_df = spark.createDataFrame(config_rows, schema)
    staging_df.createOrReplaceTempView("_snowflake_auto_discover_staging")

    spark.sql(f"""CREATE TABLE IF NOT EXISTS {lakebridge_catalog}.{lakebridge_schema}.{lakebridge_config_table} (
        label STRING, source_catalog STRING, source_schema STRING, source_table STRING,
        databricks_catalog STRING, databricks_schema STRING, databricks_table STRING,
        primary_key ARRAY<STRING>, source_filters STRING, databricks_filters STRING,
        select_columns STRING, drop_columns STRING, column_mapping STRING, column_thresholds STRING,
        aggregates STRING
    ) USING DELTA""")
    target_table = f"{lakebridge_catalog}.{lakebridge_schema}.{lakebridge_config_table}"

    merge_sql = f"""
    MERGE INTO {target_table} AS tgt
    USING _snowflake_auto_discover_staging AS src
    ON  tgt.source_catalog = src.source_catalog
    AND tgt.source_schema = src.source_schema
    AND tgt.source_table = src.source_table
    AND tgt.databricks_catalog = src.databricks_catalog
    AND tgt.databricks_schema = src.databricks_schema
    AND tgt.databricks_table = src.databricks_table
    WHEN MATCHED THEN UPDATE SET
        tgt.label = src.label,
        tgt.primary_key = src.primary_key
    WHEN NOT MATCHED THEN INSERT *
    """

    spark.sql(merge_sql)
    print(f"MERGE complete into {target_table}")
else:
    print("No tables discovered -- nothing to write.")

# COMMAND ----------

# Display the current state of the config table for the label

if config_rows:
    display(
        spark.sql(
            f"SELECT * FROM {lakebridge_catalog}.{lakebridge_schema}.{lakebridge_config_table} "
            f"WHERE label = '{label}' ORDER BY source_table"
        )
    )
