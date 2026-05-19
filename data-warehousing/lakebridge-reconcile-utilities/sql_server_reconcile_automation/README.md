# SQL Server Reconcile Automation — Setup and Usage Steps

## Prerequisites

- A Databricks workspace with Unity Catalog enabled.
- A SQL Server instance reachable from Databricks
- SQL Server tables already migrated/replicated to Databricks Delta tables.

### Workspace-level requirements (one-time)

1. **Enable the `remote_query` preview** — workspace admin → *Settings → Previews* → toggle on **"Enables remote query table-valued function (remote_query)"**. Propagation takes a few minutes after toggling.
2. **Use a SQL warehouse on DBR 17.3 or newer.** Until 17.3 reaches the Current channel, switch the warehouse to the **Preview** channel

## Step 1: Create a Databricks secret scope for the SQL Server password

The UC Connection in the next step references the SQL Server password via `secret('<scope>', '<key>')`. Create the scope and store the password first, using the Databricks CLI:

```bash
databricks secrets create-scope sqlserver_recon
databricks secrets put-secret  sqlserver_recon password --string-value '<sql-server-password>'
```

Scope and key names are free-form; just use the same values in the `CREATE CONNECTION` DDL below. If your workspace already has a scope you want to reuse, skip the create and just `put-secret` into it.

## Step 2: Create a Unity Catalog Connection to SQL Server

These notebooks read SQL Server via Databricks Lakehouse Federation's `remote_query()` table-valued function, which requires a Unity Catalog Connection. Credentials are stored in the secret scope from Step 1 — Unity Catalog reads them at query time, so no driver install or per-notebook credential handling is needed.

Run this once, from a SQL editor or notebook in the workspace, replacing the placeholders. The notebooks pass the database name per query via the helper, so the SQL Server connection's default catalog (`master`) is fine to leave alone:

```sql
CREATE CONNECTION sqlserver_recon TYPE sqlserver
OPTIONS (
  host '<sql-server-host>',
  port '1433',
  user '<sql-server-user>',
  password secret('sqlserver_recon', 'password'),
  trustServerCertificate 'false'  -- set 'true' only if the server uses a self-signed cert
);
```

Verify the connection works (this query has no embedded string literals so it sidesteps a current `query =>` parser quirk — see [Known platform issues](#known-platform-issues)):

```sql
SELECT * FROM remote_query('sqlserver_recon', query => 'SELECT @@VERSION');
```

You need the `USE CONNECTION` privilege on the connection (granted by default to the creator).


## Step 3: Prepare Unity Catalog for metadata

Pick a **catalog** and **schema** for reconciliation metadata (for example `lakebridge` and `reconcile`). Create them in **Unity Catalog** if they do not exist yet (Catalog Explorer, or `CREATE SCHEMA` in a SQL warehouse / notebook). Also create the UC Volume `reconcile_volume` as the Reconcile run will fail with `ReadAndWriteWithVolumeException` if it's missing:

```sql
CREATE SCHEMA IF NOT EXISTS <lakebridge_catalog>.<lakebridge_schema>;
CREATE VOLUME IF NOT EXISTS <lakebridge_catalog>.<lakebridge_schema>.reconcile_volume;
```

There is **no** `setup_ddl.sql` in this folder: notebooks create the Delta tables at runtime with `CREATE TABLE IF NOT EXISTS`:

- **`sql_server_auto_discover`** creates `{lakebridge_catalog}.{lakebridge_schema}.{lakebridge_config_table}` (default `table_configs`) when it has rows to merge.
- **`sql_server_recon_wrapper`** creates `{lakebridge_catalog}.{lakebridge_schema}.{table_recon_summary}` (default `table_recon_summary`) when it runs.
- The reconcile **engine** creates `main`, `details`, `metrics`, `aggregate_rules`, `aggregate_metrics` in the same schema on first run.

Use the **same** `lakebridge_catalog` and `lakebridge_schema` widget values in auto discover and in the wrapper.

## Step 4: Upload Notebooks

Upload all four `.py` notebooks to a single folder in your Databricks workspace:

- `sql_server_auto_discover.py`
- `sql_server_transformation_query_generator.py`
- `sql_server_recon_main.py`
- `sql_server_recon_wrapper.py`

They must all be in the same folder because they reference each other with `%run`.

## Step 5: Run sql_server_auto_discover

Open `sql_server_auto_discover` in Databricks and fill in the widgets:

| Widget | Description |
| --- | --- |
| `uc_connection_name` | The UC Connection from Step 2 (e.g., `sqlserver_recon`) |
| `source_database` | SQL Server database name (catalog) |
| `source_schema` | SQL Server schema (e.g., `dbo`) |
| `target_catalog` | Databricks catalog where target tables live |
| `target_schema` | Databricks schema where target tables live |
| `lakebridge_catalog` | Metadata catalog (must exist in UC; same value as Step 3 and wrapper) |
| `lakebridge_schema` | Metadata schema (must exist in UC; same value as Step 3 and wrapper) |
| `lakebridge_config_table` | Delta table name for config rows (default: `table_configs`; use the same value as the wrapper's `lakebridge_config_table` in Step 7) |
| `label` | A grouping label (e.g., `migration_batch_1`) |

**Table selection** (only one mode applies):

- **`specific_tables`** — Optional comma-separated SQL Server table names. If non-empty, discovery uses `TABLE_NAME IN (...)` and ignores `table_filter`. Order is preserved; missing/invalid names log a warning.
- **`table_filter`** — SQL `LIKE` pattern on `TABLE_NAME` (default: `%`). Used only when `specific_tables` is empty.

Run the notebook. It will:

- Query SQL Server via the UC Connection's `remote_query()`
- Discover base tables per the filters above
- Look up primary keys for each table from `INFORMATION_SCHEMA.KEY_COLUMN_USAGE`
- MERGE source-to-target mappings into `{lakebridge_catalog}.{lakebridge_schema}.{lakebridge_config_table}`

Target table names default to lowercase versions of source table names.

**Note:** Re-running with a subset does not DELETE config rows for tables you skipped; use a dedicated label if you need a clean subset.

## Step 6: Review the config table

Query the config table using the same names as in Step 5, for example:

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

## Step 7: Run sql_server_recon_wrapper

Open `sql_server_recon_wrapper` in Databricks and fill in the widgets:

| Widget | Description |
| --- | --- |
| `uc_connection_name` | Same UC Connection from Step 2 |
| `lakebridge_catalog` | Metadata catalog (same value as Step 5 `lakebridge_catalog`) |
| `lakebridge_schema` | Metadata schema (same value as Step 5 `lakebridge_schema`) |
| `lakebridge_config_table` | Same physical name as Step 5 (default: `table_configs`) |
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
- Construct `ReconcileConfig(source=SourceConnectionConfig(dialect="mssql", uc_connection_name=..., ...), target=TargetConnectionConfig(...), metadata_config=...)` — Lakebridge v0.13.0's new connection-config layout
- Run `TriggerReconService` to compare source and target via `remote_query()`
- Append pass/fail tuples to `table_recon_summary`

## Step 8: Check Results

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

- The dialect string passed to `SourceConnectionConfig` is `"mssql"` (matching `ReconSourceType.MSSQL` in Lakebridge).
- Re-running `sql_server_auto_discover` is safe (uses MERGE, not INSERT).
- The transformation generator handles SQL Server types: `int`, `bigint`, `decimal`, `float`, `varchar`, `nvarchar`, `date`, `time`, `datetime`, `datetime2`, `datetimeoffset`, `bit`, `binary`, `uniqueidentifier`, etc.
- For tables without primary keys, reconciliation runs in `"row"` mode (hash-based row comparison). With primary keys, it runs in `"all"` mode (row + column + schema).

### Target-side type representation

Lakebridge transformations assume the Delta target stores the SQL Server source types in these canonical forms. If your replicator writes a different shape, edit `sql_server_transformation_query_generator` accordingly:

| SQL Server source | Delta target representation |
| --- | --- |
| `INT` / `BIGINT` / `SMALLINT` | matching numeric type |
| `DECIMAL(p,s)` / `MONEY` | `DECIMAL(p,s)` |
| `NVARCHAR` / `VARCHAR` / `TEXT` | `STRING` |
| `DATE` | `DATE` or ISO `STRING` |
| `DATETIME` / `DATETIME2` | `TIMESTAMP` or ISO `STRING` |
| `DATETIMEOFFSET` | ISO 8601 `STRING` — **must be T-separator** form `yyyy-MM-dd'T'HH:mm:ss.fff±HH:mm` (the transformation parses this exact pattern; space-separated forms fail with `CANNOT_PARSE_TIMESTAMP`) |
| `BIT` | `BOOLEAN` |
| `BINARY` / `VARBINARY` | `BINARY` (rendered as hex on both sides) |

### Why `schema_status` may be `false` even when data matches

When `DATETIMEOFFSET` source columns land in Delta as `STRING` (the only portable target), the engine flags `schema_status = false` because the declared types differ. The per-column comparison still passes correctly via the temporal transformation — inspect `<lakebridge_catalog>.<lakebridge_schema>.details` and `metrics` for the recon id to confirm. The wrapper still reports `status="failed"` in this case because the wrapper's pass criterion requires both `row_status` and `column_status` true. If schema-mismatch-as-failed is too strict for you, edit the status logic in `sql_server_recon_main` to also accept `schema_status=false` when `row_status=true` and column hashes match.

### Known platform issues

- **`remote_query(... query => '...')` doesn't honour the SQL-standard `''` quote escape.** A literal-rich inner query written as `query => 'SELECT * FROM t WHERE c = ''x'''` reaches SQL Server with the inner quotes stripped (`WHERE c = x`) and fails with `Invalid column name 'x'`. Backslash-escape works (`query => 'SELECT * FROM t WHERE c = \'x\''`), and that's how Lakebridge's engine builds its hash-query strings internally — so engine-generated SQL is fine. These notebooks use a different sidestep: source-side INFORMATION_SCHEMA reads go through `dbtable => '...'` (no inner SQL, no escape), with predicates applied on the Spark side. If you ever build your own `query =>` strings by hand, use `\'` not `''`.
