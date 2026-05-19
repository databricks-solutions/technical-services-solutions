# Snowflake Reconcile Automation — Setup and Usage Steps


## Prerequisites

- A Databricks workspace with Unity Catalog enabled.
- A Snowflake account reachable from Databricks
- Snowflake tables already migrated/replicated to Databricks Delta tables.

### Workspace-level requirements (one-time)

1. **Enable the `remote_query` preview** — workspace admin → *Settings → Previews* → toggle on **"Enables remote query table-valued function (remote_query)"**. Propagation takes a few minutes after toggling.
2. **Use a SQL warehouse on DBR 17.3 or newer.** Until 17.3 reaches the Current channel, switch the warehouse to the **Preview** channel.

## Step 1: Create a Databricks secret scope for the Snowflake credentials

The UC Connection in the next step references the Snowflake password (or PEM private key) via `secret('<scope>', '<key>')`. Create the scope and store the credential first, using the Databricks CLI:

```bash
databricks secrets create-scope snowflake_recon
# Password auth:
databricks secrets put-secret  snowflake_recon password --string-value '<snowflake-password>'
# Or keypair auth (PKCS#8 PEM body — preferred for service accounts):
databricks secrets put-secret  snowflake_recon pem_private_key --string-value "$(cat rsa_key.p8)"
```

Scope and key names are free-form; just use the same values in the `CREATE CONNECTION` DDL below. If your workspace already has a scope you want to reuse, skip the create and just `put-secret` into it.

## Step 2: Create a Unity Catalog Connection to Snowflake

These notebooks read Snowflake via Databricks Lakehouse Federation's `remote_query()` table-valued function, which requires a Unity Catalog Connection. Credentials are stored in the secret scope from Step 1 — Unity Catalog reads them at query time, so no driver install or per-notebook credential handling is needed.

Run this once, from a SQL editor or notebook in the workspace, replacing the placeholders:

```sql
CREATE CONNECTION snowflake_recon TYPE snowflake
OPTIONS (
  host '<account>.snowflakecomputing.com',
  port '443',
  sfWarehouse '<warehouse>',
  user '<snowflake-user>',
  password secret('snowflake_recon', 'password')
);
```

For RSA keypair auth (recommended for service accounts), use the equivalent option set documented in the [Snowflake federation guide](https://docs.databricks.com/aws/en/query-federation/snowflake) — UC supports `pem_private_key` as a connection option referencing `secret('snowflake_recon', 'pem_private_key')`.

The notebooks reference the connection by name via the `uc_connection_name` widget. To verify it works:

```sql
SELECT * FROM remote_query('snowflake_recon', query => 'SELECT CURRENT_VERSION()');
```

You need the `USE CONNECTION` privilege on the connection (granted by default to the creator).

## Step 3: Prepare Unity Catalog for metadata

Pick a **catalog** and **schema** for reconciliation metadata (for example `lakebridge` and `reconcile`). Create them in **Unity Catalog** if they do not exist yet (Catalog Explorer, or `CREATE SCHEMA` in a SQL warehouse / notebook). Also create a UC Volume `reconcile_volume` in that schema as the Reconcile run will fail with `ReadAndWriteWithVolumeException` if it's missing:

```sql
CREATE SCHEMA IF NOT EXISTS <lakebridge_catalog>.<lakebridge_schema>;
CREATE VOLUME IF NOT EXISTS <lakebridge_catalog>.<lakebridge_schema>.reconcile_volume;
```

- **`snowflake_auto_discover`** creates `{lakebridge_catalog}.{lakebridge_schema}.{lakebridge_config_table}` (default table name `table_configs`) when it has rows to merge.
- **`snowflake_recon_wrapper`** creates `{lakebridge_catalog}.{lakebridge_schema}.{table_recon_summary}` (default `table_recon_summary`) when it runs.
- The reconcile **engine** creates `main`, `details`, `metrics`, `aggregate_rules`, `aggregate_metrics` in the same schema on first run.

Use the **same** `lakebridge_catalog` and `lakebridge_schema` widget values in auto discover and in the wrapper.

## Step 4: Upload Notebooks

Upload all four `.py` notebooks to a single folder in your Databricks workspace:

- `snowflake_auto_discover.py`
- `snowflake_transformation_query_generator.py`
- `snowflake_recon_main.py`
- `snowflake_recon_wrapper.py`

They must all be in the same folder because they reference each other with `%run`.

## Step 5: Run snowflake_auto_discover

Open `snowflake_auto_discover` in Databricks and fill in the widgets:

| Widget | Description |
| --- | --- |
| `uc_connection_name` | The UC Connection from Step 2 (e.g., `snowflake_recon`) |
| `source_database` | Snowflake database (catalog) |
| `source_schema` | Snowflake schema (default: `PUBLIC`) |
| `target_catalog` | Databricks catalog where target tables live |
| `target_schema` | Databricks schema where target tables live |
| `lakebridge_catalog` | Metadata catalog (must exist in UC; same value as Step 3 and wrapper) |
| `lakebridge_schema` | Metadata schema (must exist in UC; same value as Step 3 and wrapper) |
| `lakebridge_config_table` | Delta table name for config rows (default: `table_configs`; use the same value as the wrapper's `lakebridge_config_table` in Step 7) |
| `label` | A grouping label (e.g., `migration_batch_1`) |

**Table selection** (only one mode applies):

- **`specific_tables`** — Optional comma-separated Snowflake table names. If non-empty, discovery uses `TABLE_NAME IN (...)` and ignores `table_filter`. Order is preserved; missing/invalid names log a warning.
- **`table_filter`** — SQL `LIKE` pattern on `TABLE_NAME` (default: `%`). Used only when `specific_tables` is empty.

Run the notebook. It will:

- Query Snowflake via the UC Connection's `remote_query()`
- Discover base tables per the filters above from `{source_database}.INFORMATION_SCHEMA.TABLES`
- Look up primary keys for each table via `SHOW PRIMARY KEYS IN TABLE` (also routed through `remote_query()`)
- MERGE source-to-target mappings into `{lakebridge_catalog}.{lakebridge_schema}.{lakebridge_config_table}`

**Snowflake identifier note:** Unquoted identifiers in Snowflake are folded to upper case. The discovery query compares against `UPPER()` of your widget values, so you can type either case.

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

## Step 7: Run snowflake_recon_wrapper

Open `snowflake_recon_wrapper` in Databricks and fill in the widgets:

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

- Build Snowflake-specific transformations per column data type
- Construct `ReconcileConfig(source=SourceConnectionConfig(dialect="snowflake", uc_connection_name=..., ...), target=TargetConnectionConfig(...), metadata_config=...)` — Lakebridge v0.13.0's new connection-config layout
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

- The dialect string passed to `SourceConnectionConfig` is `"snowflake"` (matching `ReconSourceType.SNOWFLAKE` in Lakebridge).
- Lakebridge applies `sha256_partial` on both sides for Snowflake, so Unicode columns compare cleanly. `column_status` is reliable.
- Re-running `snowflake_auto_discover` is safe (uses MERGE, not INSERT).
- The transformation generator handles Snowflake types: `NUMBER`, `DECIMAL`, `INT`/`BIGINT`/`SMALLINT`/`TINYINT`, `FLOAT`/`DOUBLE`/`REAL`, `TEXT`/`VARCHAR`/`CHAR`, `DATE`, `TIME`, `TIMESTAMP_NTZ`/`TIMESTAMP_LTZ`/`TIMESTAMP_TZ`, `BOOLEAN`, `BINARY`, `VARIANT`/`OBJECT`/`ARRAY`.
- Skipped types (no meaningful cross-platform comparison): `GEOGRAPHY`, `GEOMETRY`, `VECTOR`.
- For tables without primary keys, reconciliation runs in `"row"` mode (hash-based row comparison). With primary keys, it runs in `"all"` mode (row + column + schema).

### Target-side type representation

Lakebridge transformations assume the Delta target stores the Snowflake source types in these canonical forms. If your replicator writes a different shape, edit `snowflake_transformation_query_generator` accordingly:

| Snowflake source | Delta target representation |
| --- | --- |
| `NUMBER` / `INT` family | `DECIMAL` or matching integer |
| `FLOAT` / `DOUBLE` / `REAL` | `DOUBLE` |
| `TEXT` / `VARCHAR` / `CHAR` | `STRING` |
| `DATE` | `DATE` or ISO `STRING` |
| `TIME` | ISO `STRING` (`HH:mm:ss[.SSS]`) |
| `TIMESTAMP_NTZ` | `TIMESTAMP` or ISO `STRING` (`yyyy-MM-dd HH:mm:ss.SSS`) |
| `TIMESTAMP_LTZ` / `TIMESTAMP_TZ` | ISO 8601 `STRING` — **T-separator** form `yyyy-MM-ddTHH:mm:ss±HH:mm` (the transformation parses this exact pattern; space-separated forms fail with `CANNOT_PARSE_TIMESTAMP`) |
| `BOOLEAN` | `BOOLEAN` |
| `BINARY` / `VARBINARY` | `BINARY` (rendered as hex on both sides) |
| `VARIANT` / `OBJECT` / `ARRAY` | `STRING` containing canonical JSON |

### Known platform issues

- **`remote_query(... query => '...')` doesn't honour the SQL-standard `''` quote escape.** A literal-rich inner query written as `query => 'SELECT * FROM t WHERE c = ''x'''` reaches Snowflake with the inner quotes stripped (`WHERE c = x`). Backslash-escape works (`query => 'SELECT * FROM t WHERE c = \'x\''`), and that's how Lakebridge's engine builds its hash-query strings internally — engine-generated SQL is fine. These notebooks sidestep the issue entirely on the INFORMATION_SCHEMA / SHOW PRIMARY KEYS paths by reading via `dbtable => '...'` (or by using SHOW which has no embedded literals), with predicates applied on the Spark side. If you ever hand-write a `query =>` string, use `\'` not `''`.
