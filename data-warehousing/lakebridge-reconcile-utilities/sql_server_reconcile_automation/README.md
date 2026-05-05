# SQL Server Reconcile Automation — Setup and Usage Steps

## Prerequisites

- Lakebridge is installed (`pip install databricks-labs-lakebridge`)
- A Databricks workspace with Unity Catalog enabled
- A SQL Server instance accessible from Databricks via JDBC
- SQL Server tables already migrated/replicated to Databricks Delta tables

## Step 1: Create a Databricks Secret Scope

Create a secret scope and add the following keys with your SQL Server connection details.

**Scope name example:** `lakebridge_mssql`

**Required keys:**

| Key | Description |
| --- | --- |
| `user` | SQL Server username |
| `password` | SQL Server password |
| `host` | SQL Server hostname or IP |
| `port` | SQL Server port (typically 1433) |
| `database` | SQL Server database name |
| `encrypt` | `"true"` or `"false"` |
| `trustServerCertificate` | `"true"` or `"false"` |

You can create the scope using the Databricks CLI:

```bash
databricks secrets create-scope lakebridge_mssql
databricks secrets put-secret lakebridge_mssql user --string-value "<your_user>"
# ... (repeat for each key)
```

## Step 2: Prepare Unity Catalog for metadata

Pick a **catalog** and **schema** for reconciliation metadata (for example `lakebridge` and `reconcile`). Create them in **Unity Catalog** if they do not exist yet (Catalog Explorer, or `CREATE SCHEMA` in a SQL warehouse / notebook).

There is **no** `setup_ddl.sql` in this folder: notebooks create the Delta tables at runtime with `CREATE TABLE IF NOT EXISTS`:

- **`sql_server_auto_discover`** creates `{lakebridge_catalog}.{lakebridge_schema}.{lakebridge_config_table}` (default `table_configs`) when it has rows to merge.
- **`sql_server_recon_wrapper`** creates `{lakebridge_catalog}.{lakebridge_schema}.{table_recon_summary}` (default `table_recon_summary`) when it runs.

Use the **same** `lakebridge_catalog` and `lakebridge_schema` widget values in auto discover and in the wrapper.

## Step 3: Upload Notebooks

Upload all four `.py` notebooks to a single folder in your Databricks workspace:

- `sql_server_auto_discover.py`
- `sql_server_transformation_query_generator.py`
- `sql_server_recon_main.py`
- `sql_server_recon_wrapper.py`

They must all be in the same folder because they reference each other with `%run`.

## Step 4: Run sql_server_auto_discover

Open `sql_server_auto_discover` in Databricks and fill in the widgets:

| Widget | Description |
| --- | --- |
| `secret_scope` | The scope from Step 1 (e.g., `lakebridge_mssql`) |
| `source_database` | SQL Server database name (catalog) |
| `source_schema` | SQL Server schema (e.g., `dbo`) |
| `target_catalog` | Databricks catalog where target tables live |
| `target_schema` | Databricks schema where target tables live |
| `lakebridge_catalog` | Metadata catalog (must exist in UC; same value as Step 2 and wrapper) |
| `lakebridge_schema` | Metadata schema (must exist in UC; same value as Step 2 and wrapper) |
| `lakebridge_config_table` | Delta table name for config rows (default: `table_configs`; use the same value as the wrapper’s `lakebridge_config_table` in Step 6) |
| `label` | A grouping label (e.g., `migration_batch_1`) |

**Table selection** (only one mode applies):

- **`specific_tables`** — Optional comma-separated SQL Server table names. If non-empty, discovery uses `TABLE_NAME IN (...)` and ignores `table_filter`. Order is preserved; missing/invalid names log a warning.
- **`table_filter`** — SQL `LIKE` pattern on `TABLE_NAME` (default: `%`). Used only when `specific_tables` is empty.

Run the notebook. It will:

- Connect to SQL Server via JDBC
- Discover base tables per the filters above
- Look up primary keys for each table
- MERGE source-to-target mappings into `{lakebridge_catalog}.{lakebridge_schema}.{lakebridge_config_table}`

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

## Step 6: Run sql_server_recon_wrapper

Open `sql_server_recon_wrapper` in Databricks and fill in the widgets:

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

- Build SQL Server-specific transformations per column data type
- Create a `ReconcileConfig` with `data_source="mssql"`
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

- The `data_source` value is `"mssql"` (matching `ReconSourceType.MSSQL` in Lakebridge).
- JDBC driver `com.microsoft.sqlserver.jdbc.SQLServerDriver` is automatically available on Databricks clusters.
- Re-running `sql_server_auto_discover` is safe (uses MERGE, not INSERT).
- The transformation generator handles SQL Server types: `int`, `bigint`, `decimal`, `float`, `varchar`, `nvarchar`, `date`, `time`, `datetime`, `datetime2`, `bit`, `binary`, `uniqueidentifier`, etc.
- For tables without primary keys, reconciliation runs in `"row"` mode (hash-based row comparison). With primary keys, it runs in `"all"` mode (row + column + schema).
