# Snowflake Reconcile Automation — Setup and Usage Steps

## Prerequisites

- Lakebridge is installed (`pip install databricks-labs-lakebridge`)
- A Databricks workspace with Unity Catalog enabled
- A Snowflake account accessible from Databricks via the Snowflake Spark connector
- Snowflake tables already migrated/replicated to Databricks Delta tables

## Step 1: Create a Databricks Secret Scope

Create a secret scope and add the following keys with your Snowflake connection details. These are the exact option keys consumed by the Snowflake Spark connector (`spark.read.format("snowflake")`).

**Scope name example:** `lakebridge_snowflake`

**Required keys:**

| Key | Description |
| --- | --- |
| `sfUrl` | Snowflake account URL, e.g. `https://<account_id>.snowflakecomputing.com` |
| `sfUser` | Snowflake username |
| `sfDatabase` | Default database |
| `sfSchema` | Default schema |
| `sfWarehouse` | Warehouse to use for queries |
| `sfRole` | Role to use for queries |

**Authentication keys — pick one.** The notebooks and Lakebridge's Snowflake connector both prefer `pem_private_key` and fall back to `sfPassword`.

| Key | Description |
| --- | --- |
| `pem_private_key` | Full PKCS#8 PEM body (keypair auth — recommended) |
| `pem_private_key_password` | Only if the PEM is passphrase-encrypted |
| `sfPassword` | Password (fallback; omit when `pem_private_key` is set) |

Generate and register a keypair:

```bash
# 1. Generate an unencrypted PKCS#8 private key:
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out rsa_key.p8 -nocrypt

# 2. Extract the public key:
openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub

# 3. Register it on the Snowflake user (base64 body only — no header/footer):
#    ALTER USER <user> SET RSA_PUBLIC_KEY='<base64 body>';
```

Create the scope using the Databricks CLI:

```bash
databricks secrets create-scope lakebridge_snowflake
databricks secrets put-secret lakebridge_snowflake sfUrl --string-value "https://<account_id>.snowflakecomputing.com"
databricks secrets put-secret lakebridge_snowflake pem_private_key --string-value "$(cat rsa_key.p8)"
# ... (repeat for sfUser, sfDatabase, sfSchema, sfWarehouse, sfRole)
```

## Step 2: Prepare Unity Catalog for metadata

Pick a **catalog** and **schema** for reconciliation metadata (for example `lakebridge` and `reconcile`). Create them in **Unity Catalog** if they do not exist yet (Catalog Explorer, or `CREATE SCHEMA` in a SQL warehouse / notebook).



- **`snowflake_auto_discover`** creates `{lakebridge_catalog}.{lakebridge_schema}.{lakebridge_config_table}` (default table name `table_configs`) when it has rows to merge.
- **`snowflake_recon_wrapper`** creates `{lakebridge_catalog}.{lakebridge_schema}.{table_recon_summary}` (default `table_recon_summary`) when it runs.

Use the **same** `lakebridge_catalog` and `lakebridge_schema` widget values in auto discover and in the wrapper.

## Step 3: Upload Notebooks

Upload all four `.py` notebooks to a single folder in your Databricks workspace:

- `snowflake_auto_discover.py`
- `snowflake_transformation_query_generator.py`
- `snowflake_recon_main.py`
- `snowflake_recon_wrapper.py`

They must all be in the same folder because they reference each other with `%run`.

## Step 4: Run snowflake_auto_discover

Open `snowflake_auto_discover` in Databricks and fill in the widgets:

| Widget | Description |
| --- | --- |
| `secret_scope` | The scope from Step 1 (e.g., `lakebridge_snowflake`) |
| `source_database` | Snowflake database (catalog) |
| `source_schema` | Snowflake schema (default: `PUBLIC`) |
| `target_catalog` | Databricks catalog where target tables live |
| `target_schema` | Databricks schema where target tables live |
| `lakebridge_catalog` | Metadata catalog (must exist in UC; same value as Step 2 and wrapper) |
| `lakebridge_schema` | Metadata schema (must exist in UC; same value as Step 2 and wrapper) |
| `lakebridge_config_table` | Delta table name for config rows (default: `table_configs`; use the same value as the wrapper's `lakebridge_config_table` in Step 6) |
| `label` | A grouping label (e.g., `migration_batch_1`) |

**Table selection** (only one mode applies):

- **`specific_tables`** — Optional comma-separated Snowflake table names. If non-empty, discovery uses `TABLE_NAME IN (...)` and ignores `table_filter`. Order is preserved; missing/invalid names log a warning.
- **`table_filter`** — SQL `LIKE` pattern on `TABLE_NAME` (default: `%`). Used only when `specific_tables` is empty.

Run the notebook. It will:

- Connect to Snowflake via the Spark connector
- Discover base tables per the filters above from `{source_database}.INFORMATION_SCHEMA.TABLES`
- Look up primary keys for each table via `SHOW PRIMARY KEYS IN TABLE` + `RESULT_SCAN`
- MERGE source-to-target mappings into `{lakebridge_catalog}.{lakebridge_schema}.{lakebridge_config_table}`

**Snowflake identifier note:** Unquoted identifiers in Snowflake are folded to upper case. The discovery query compares against `UPPER()` of your widget values, so you can type either case.

Target table names default to lowercase versions of source table names.

**Note:** Re-running with a subset does not DELETE config rows for tables you skipped; use a dedicated label if you need a clean subset.

## Step 5: Review the config table

Query the config table using the same names as in Step 4, for example:

```sql
SELECT * FROM <lakebridge_catalog>.<lakebridge_schema>.<lakebridge_config_table>
WHERE label = '<your_label>'
ORDER BY source_table;
```

Adjust rows as needed:

- Edit `primary_key` if auto-detection missed anything
- Add `source_filters` / `databricks_filters` for partial comparisons
- Set `select_columns` or `drop_columns` to limit scope
- Change `databricks_table` if naming conventions differ

## Step 6: Run snowflake_recon_wrapper

Open `snowflake_recon_wrapper` in Databricks and fill in the widgets:

| Widget | Description |
| --- | --- |
| `secret_scope` | Same scope from Step 1 |
| `lakebridge_catalog` | Metadata catalog (same value as Step 4 `lakebridge_catalog`) |
| `lakebridge_schema` | Metadata schema (same value as Step 4 `lakebridge_schema`) |
| `lakebridge_config_table` | Same physical name as Step 4 (default: `table_configs`) |
| `table_recon_summary` | Summary Delta table name (default: `table_recon_summary`) |
| `label` | Comma-separated labels to include (matches config table `label` column) |

**Optional run filters** (narrow which config rows are reconciled; all empty = no extra filter):

- **`reconcile_tables`** — Comma-separated names; row kept if `source_table` OR `databricks_table` matches any name (case-insensitive)
- **`filter_source_catalog`** — Exact match on `source_catalog`
- **`filter_source_schema`** — Exact match on `source_schema`
- **`filter_target_catalog`** — Exact match on `databricks_catalog`
- **`filter_target_schema`** — Exact match on `databricks_schema`

Run the notebook. For each matching config row, it will:

- Build Snowflake-specific transformations per column data type
- Create a `ReconcileConfig` with `data_source="snowflake"`
- Run `TriggerReconService` to compare source and target
- Append pass/fail tuples to `table_recon_summary`

## Step 7: Check Results

Query the summary table:

```sql
SELECT * FROM <lakebridge_catalog>.<lakebridge_schema>.table_recon_summary
WHERE label = '<your_label>'
ORDER BY timestamp DESC;
```

**Key columns:**

| Column | Meaning |
| --- | --- |
| `status` | `"passed"` or `"failed"` |
| `recon_id` | Use this to drill into the Lakebridge reconciliation dashboard |
| `row_status` | Row-level match result |
| `column_status` | Column-level match result (null for row-only report) |
| `schema_status` | Schema comparison result |
| `error` | Error message if reconciliation failed |

## Notes

- The `data_source` value is `"snowflake"` (matching `ReconSourceType.SNOWFLAKE` in Lakebridge).
- Unlike the SQL Server path, Lakebridge applies `sha256_partial` on both sides for Snowflake, so the Unicode hash-encoding issue tracked in [lakebridge#1619](https://github.com/databrickslabs/lakebridge/issues/1619) does not apply — `column_status` is reliable here.
- Re-running `snowflake_auto_discover` is safe (uses MERGE, not INSERT).
- The transformation generator handles Snowflake types: `NUMBER`, `DECIMAL`, `INT`/`BIGINT`/`SMALLINT`/`TINYINT`, `FLOAT`/`DOUBLE`/`REAL`, `TEXT`/`VARCHAR`/`CHAR`, `DATE`, `TIME`, `TIMESTAMP_NTZ`/`TIMESTAMP_LTZ`/`TIMESTAMP_TZ`, `BOOLEAN`, `BINARY`, `VARIANT`/`OBJECT`/`ARRAY`.
- Skipped types (no meaningful cross-platform comparison): `GEOGRAPHY`, `GEOMETRY`, `VECTOR`.
- For tables without primary keys, reconciliation runs in `"row"` mode (hash-based row comparison). With primary keys, it runs in `"all"` mode (row + column + schema).
