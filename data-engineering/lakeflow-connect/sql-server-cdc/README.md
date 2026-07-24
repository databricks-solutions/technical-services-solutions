# Lakeflow Connect: SQL Server CDC

Databricks Asset Bundle (DABs) to deploy [Lakeflow Connect](https://docs.databricks.com/aws/en/ingestion/lakeflow-connect) for SQL Server CDC into Unity Catalog.

Use this bundle after you create a Unity Catalog connection to SQL Server to stand up:

1. An **ingestion gateway** pipeline (federated read + staging storage)
2. A **CDC ingestion pipeline** (source tables → UC destination tables)
3. An optional **scheduled job** to refresh ingestion

> **AI-assisted setup:** For step-by-step execution with an agent (Cursor, Claude Code, etc.), see [RUNBOOK.md](./RUNBOOK.md).

## Architecture

```text
SQL Server (CDC) ──► UC Connection ──► Ingestion Gateway ──► Ingestion Pipeline ──► UC destination tables
```

| Component | Bundle resource | Purpose |
| --- | --- | --- |
| Ingestion gateway | `ingestion_gateway` | Reads from the federated SQL Server connection; stages data in UC |
| Ingestion pipeline | `ingestion_pipeline` | Ingests configured CDC tables into destination catalog/schema |
| Refresh job | `refresh_pipeline` | Optional daily trigger for the ingestion pipeline |

## Prerequisites

- Databricks workspace with Unity Catalog enabled
- [Databricks CLI](https://docs.databricks.com/aws/en/dev-tools/cli/) authenticated (`databricks auth login`) — required for local CLI deployment; optional if you deploy from the workspace UI
- A Unity Catalog **connection** to SQL Server (see [Create the SQL Server connection](#create-the-sql-server-connection) below)
- CDC enabled on the SQL Server tables you plan to ingest ([source setup](https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/sql-server-source-setup))
- UC catalog(s) and schema(s) for staging, pipeline logs, and destination data
- `CREATE CONNECTION` on the Unity Catalog metastore (or an existing connection with `USE CONNECTION`)

## Create the SQL Server connection

This bundle references an existing Unity Catalog connection through `connection_name` in `variables.yml`. Create the connection once in the workspace before deploying the bundle.

The connection stores the SQL Server host and credentials. Users with `USE CONNECTION` can build ingestion pipelines without direct access to the password.

### UI (Catalog Explorer)

1. In the workspace, open **Catalog**.
2. Click **Connect**, then **Connections**.
3. Click **Create connection**.
4. Enter a **Connection name** (use this value for `connection_name` in `variables.yml`).
5. For **Connection type**, select **SQL Server**.
6. Enter **Host** (SQL Server hostname or FQDN, for example `myserver.database.windows.net`).
7. Enter **User** and **Password** (or choose OAuth if your environment uses Entra ID).
8. Click **Create connection**.

Optional: open the connection in Catalog Explorer and use **Test connection** to confirm Databricks can reach SQL Server.

See [Create a SQL Server connection](https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/sql-server-connection) for details and privilege requirements.

### SQL

Run in a notebook or the SQL editor. Replace the placeholders with your values.

```sql
CREATE CONNECTION IF NOT EXISTS <connection_name>
TYPE SQLSERVER
OPTIONS (
  host '<sql_server_host>',
  port '1433',
  user '<sql_server_user>',
  password '<sql_server_password>'
);
```

Prefer Databricks secrets instead of literals for credentials:

```sql
CREATE CONNECTION IF NOT EXISTS <connection_name>
TYPE SQLSERVER
OPTIONS (
  host '<sql_server_host>',
  port '1433',
  user secret('<secret_scope>', '<user_secret_key>'),
  password secret('<secret_scope>', '<password_secret_key>')
);
```

Grant other users access to the connection (for example, so they can deploy this bundle):

```sql
GRANT USE CONNECTION ON CONNECTION <connection_name> TO `<user_or_group>`;
```

List connections to confirm the name:

```sql
SHOW CONNECTIONS;
```

**Note:** In Lakeflow Connect, the SQL Server **database name** maps to `source_catalog` in `variables.yml`, and the SQL Server **schema** (for example `dbo`) maps to `source_schema`.

## Configuration

### 1. Workspace (`databricks.yml`)

Set your workspace URL under `targets.dev.workspace.host`:

```yaml
workspace:
  host: https://YOUR_WORKSPACE.cloud.databricks.com/
```

### 2. Variables (`variables.yml`)

Replace the `<...>` placeholders under `targets.dev.variables`:

| Variable | Description |
| --- | --- |
| `ingestion_gateway_name` | Name for the gateway pipeline and staging storage |
| `connection_name` | Unity Catalog connection to SQL Server |
| `staging_catalog` / `staging_schema` | Where gateway stages data |
| `ingestion_pipeline_name` | Name for the CDC ingestion pipeline |
| `pipeline_log_catalog` / `pipeline_log_schema` | Pipeline event log location |
| `source_catalog` / `source_schema` | Source names on the federated connection |
| `dest_catalog` / `dest_schema` | UC destination for ingested tables |

The `gateway_cluster` block ships with Azure-friendly defaults. Change node types only if your cloud or workload requires it.

### 3. Tables (`resources/ingestion_pipeline.pipeline.yml`)

Set `source_table` for each table to ingest. Copy the `table:` block to add more tables, or uncomment the `schema:` example for whole-schema ingestion.

## Deploy and run

You can deploy from your local machine with the Databricks CLI, or from the workspace after cloning this repository into a Git folder (Repos).

### Option A: CLI (local)

From the `sql-server-cdc` directory on your machine:

```bash
# Validate and deploy
databricks bundle validate --profile <PROFILE> --target dev
databricks bundle deploy --profile <PROFILE> --target dev

# Run gateway first, then ingestion
databricks bundle run ingestion_gateway --profile <PROFILE> --target dev
databricks bundle run ingestion_pipeline --profile <PROFILE> --target dev
```

### Option B: Workspace (Git folder)

Use this path when you want to edit, deploy, and run the bundle entirely in the Databricks workspace UI.

**Requirements:** workspace files enabled, serverless compute enabled, and a Git folder. See [Bundles in the workspace](https://docs.databricks.com/aws/en/dev-tools/bundles/workspace).

#### 1. Clone the repository into a Git folder

1. Connect your Git provider under **Settings → Linked accounts → Git integration** ([docs](https://docs.databricks.com/aws/en/repos/git-operations-with-repos)).
2. In the sidebar, open **Workspace** and browse to the folder where you want the repo (for example **Users → `<your-user>`**).
3. Click **Create → Git folder**.
4. Enter the repository URL `https://github.com/databricks-solutions/technical-services-solutions.git`, select your Git provider, and click **Create Git folder**.

For this monorepo, optionally enable **Sparse checkout** and limit the clone to:

```text
data-engineering/lakeflow-connect/sql-server-cdc
```

#### 2. Configure the bundle in the workspace

1. In the Git folder, open:

   ```text
   data-engineering/lakeflow-connect/sql-server-cdc
   ```

2. Edit `databricks.yml`, `variables.yml`, and `resources/ingestion_pipeline.pipeline.yml` with your workspace and connection values (same as [Configuration](#configuration) above).
3. Set `targets.dev.workspace.host` to your current workspace URL.

#### 3. Deploy from the bundle editor

1. Open `databricks.yml` in that folder.
2. Click the **Deployments** icon (rocket) in the left sidebar.
3. Under **Targets**, select `dev`.
4. Click **Deploy**, review the confirmation dialog, then click **Deploy** again.
5. When deployment completes, deployed resources appear under **Bundle resources**.

See [Deploy bundles from the workspace](https://docs.databricks.com/aws/en/dev-tools/bundles/workspace-deploy).

#### 4. Run pipelines from the workspace

In the **Deployments** pane, under **Bundle resources**:

1. Click the **Run** (play) icon on `ingestion_gateway` and wait for SUCCESS.
2. Click the **Run** icon on `ingestion_pipeline`.

Run the gateway before the ingestion pipeline.

To trigger the refresh job once, run `refresh_pipeline` the same way.

**Note:** Workspace UI deployment applies to the **current workspace only**. To deploy to a different workspace, use the CLI or CI/CD.

#### Alternative: CLI from the workspace web terminal

If you prefer commands inside the workspace, open a [web terminal](https://docs.databricks.com/aws/en/compute/web-terminal) in the bundle folder and run the same `databricks bundle` commands as in Option A (no `--profile` needed when already authenticated in the workspace).

### Verify in Unity Catalog

Browse to your destination catalog and schema in the **Catalog** explorer, or query in the SQL editor:

```sql
SELECT * FROM <dest_catalog>.<dest_schema>.<table_name> LIMIT 20;
```

### Optional: manual job run

```bash
databricks bundle run refresh_pipeline --profile <PROFILE> --target dev
```

The job is deployed with a daily schedule. In `development` mode, schedules are paused by default.

## Project structure

| Path | Description |
| --- | --- |
| `databricks.yml` | Bundle definition and targets |
| `variables.yml` | Variable declarations and per-target values |
| `resources/ingestion_gateway.pipeline.yml` | Gateway pipeline |
| `resources/ingestion_pipeline.pipeline.yml` | CDC ingestion pipeline |
| `resources/trigger_ingestion.job.yml` | Scheduled refresh job |
| `RUNBOOK.md` | Agent-guided step-by-step runbook |

## Production

Uncomment and configure the `prod` target in `databricks.yml`, then add a `targets.prod` section in `variables.yml` with production catalog, schema, and connection values.

## References

- [Lakeflow Connect](https://docs.databricks.com/aws/en/ingestion/lakeflow-connect)
- [Databricks Asset Bundles](https://docs.databricks.com/aws/en/dev-tools/bundles/index.html)
- [Bundles in the workspace](https://docs.databricks.com/aws/en/dev-tools/bundles/workspace)
- [Deploy bundles from the workspace](https://docs.databricks.com/aws/en/dev-tools/bundles/workspace-deploy)
- [Git folders (Repos)](https://docs.databricks.com/aws/en/repos/git-operations-with-repos)
- [Create a SQL Server connection](https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/sql-server-connection)
- [SQL Server source setup (CDC)](https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/sql-server-source-setup)
- [Connect to managed ingestion sources](https://docs.databricks.com/aws/en/connect/managed-ingestion)
- [CREATE CONNECTION (SQL reference)](https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-syntax-ddl-create-connection)
