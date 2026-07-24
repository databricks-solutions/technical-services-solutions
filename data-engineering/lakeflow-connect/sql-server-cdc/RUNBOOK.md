# Agent runbook: Lakeflow Connect SQL Server CDC

Runbook for an AI coding harness (Cursor, Claude Code, Codex, etc.).
A customer should be able to open this project and say: **run RUNBOOK.md**.
Follow every step in order.
Do not skip pauses.
Do not invent credentials, connection secrets, or workspace settings.

For a standard human setup guide, see [README.md](./README.md).

## What this demo teaches

Deploy Lakeflow Connect for SQL Server CDC with a Databricks Asset Bundle.
An **ingestion gateway** pipeline stages change data from a Unity Catalog federated SQL Server connection.
An **ingestion pipeline** lands CDC tables into Unity Catalog destination tables.
A scheduled job can trigger refreshes after the initial setup.

Rule to remember: **configure connection + tables -> deploy gateway + pipeline -> run gateway -> run ingestion -> verify UC tables.**

## Progress tracker

Mark each step only after it succeeds. Do not advance while a step is failing.

| Step | Action | Done |
| --- | --- | --- |
| 0 | Confirm prerequisites and replace placeholders | [ ] |
| 1 | `bundle validate` + `bundle deploy` | [ ] |
| 2 | Run `ingestion_gateway` pipeline | [ ] |
| 3 | Run `ingestion_pipeline` pipeline | [ ] |
| 4 | Verify destination tables in Unity Catalog | [ ] |
| 5 | (Optional) Enable `refresh_pipeline` job schedule | [ ] |

## Agent operating rules

1. Use only the CLI flags the user confirmed in Prerequisites.
2. After every `databricks bundle run` / `deploy`, wait for SUCCESS before the next step.
3. On failure: read the error, fix local code or config, redeploy if needed, re-run the failed command.
   Do not continue to the next demo step until the current one is green.
4. When this runbook says **PAUSE**, stop.
   Message the user with the exact SQL (or UI action) below.
   Wait for them to reply before continuing.
5. Prefer the Databricks CLI over clicking around the workspace UI, except for SQL verification pauses (SQL editor).
6. Do not deploy until every placeholder in `variables.yml` and `resources/ingestion_pipeline.pipeline.yml` is replaced with real values.

## Prerequisites (configure before anything else)

**PAUSE.**
Do not deploy yet.
Ask the user to confirm these values.
They are mandatory.

| Setting | Where it lives | Example |
| --- | --- | --- |
| **CLI profile** | Databricks CLI auth profile name | `my-profile` |
| **Workspace URL** | `targets.dev.workspace.host` in `databricks.yml` | `https://YOUR_WORKSPACE.cloud.databricks.com/` |
| **SQL Server UC connection** | `connection_name` in `variables.yml` | `my-sqlserver-connection` |
| **Staging catalog / schema** | `staging_catalog`, `staging_schema` in `variables.yml` | `main` / `lfconnect_staging` |
| **Destination catalog / schema** | `dest_catalog`, `dest_schema` in `variables.yml` | `main` / `lfconnect_cdc` |
| **Source catalog / schema** | `source_catalog`, `source_schema` in `variables.yml` | Names shown on the federated connection |
| **Tables to ingest** | `resources/ingestion_pipeline.pipeline.yml` | One or more `table:` blocks |

Also confirm:

- The user can authenticate with that profile (`databricks auth login --profile <PROFILE>` if needed).
- Unity Catalog is enabled and they can create schemas in the chosen catalogs.
- A Unity Catalog **connection** to SQL Server already exists (Lakehouse Federation / Lakeflow Connect prerequisite).
- CDC is enabled on the source SQL Server tables they plan to ingest.
- Gateway cluster defaults in `variables.yml` are acceptable for their cloud (Azure node types are pre-filled).

Then update:

1. `databricks.yml` — workspace host if it differs from the placeholder.
2. `variables.yml` — replace every `<...>` placeholder except the `gateway_cluster` block (keep those defaults unless the user asks to change compute).
3. `resources/ingestion_pipeline.pipeline.yml` — set `source_table` (and add more `table:` entries if needed).

Every bundle command in this runbook uses:

```bash
databricks bundle <deploy|run|validate> --profile <PROFILE> --target dev
```

Substitute `<PROFILE>` with the confirmed profile.
Substitute `<DEST_CATALOG>` and `<DEST_SCHEMA>` in SQL with the confirmed destination catalog and schema.

**Do not continue until the user has confirmed profile, workspace URL, connection name, catalogs, schemas, and tables.**

## Layout (read-only context)

| Path | Role |
| --- | --- |
| `databricks.yml` | Bundle name, workspace host, targets. |
| `variables.yml` | Gateway + pipeline variable declarations and dev defaults. |
| `resources/ingestion_gateway.pipeline.yml` | Ingestion gateway (federated connection + staging storage). |
| `resources/ingestion_pipeline.pipeline.yml` | CDC ingestion pipeline (source tables -> UC destination). |
| `resources/trigger_ingestion.job.yml` | Optional daily job to refresh the ingestion pipeline. |

---

## Step 0: validate configuration

Review placeholders one last time.
No deploy yet.

```bash
databricks bundle validate --profile <PROFILE> --target dev
```

Expected: `Validation OK!`
If validation fails, fix YAML or variable references before Step 1.

---

## Step 1: deploy the bundle

```bash
databricks bundle deploy --profile <PROFILE> --target dev
```

Deploy creates (or updates) the ingestion gateway pipeline, ingestion pipeline, and trigger job.
Expected: `Deployment complete!`

---

## Step 2: run the ingestion gateway

The gateway must run successfully before the ingestion pipeline can pull CDC data.

```bash
databricks bundle run ingestion_gateway --profile <PROFILE> --target dev
```

Expected: pipeline update COMPLETED / SUCCESS.

### PAUSE - verify gateway

Before you continue, tell the user:

> Open the workspace at `<WORKSPACE_URL>`.
> In **Lakeflow** / **Pipelines**, confirm the ingestion gateway pipeline exists and its latest update succeeded.
> Reply when the gateway run is green.

**Do not start Step 3 until the user confirms the gateway succeeded.**

---

## Step 3: run the ingestion pipeline

```bash
databricks bundle run ingestion_pipeline --profile <PROFILE> --target dev
```

Expected: pipeline update COMPLETED / SUCCESS.

---

## Step 4: verify destination tables in Unity Catalog

### PAUSE - verify UC destination tables

Before you continue, tell the user:

> Go to the SQL editor in workspace `<WORKSPACE_URL>` (or open **Catalog** and browse to `<DEST_CATALOG>.<DEST_SCHEMA>`).
> Run the query below (adjust the table name to match `ingestion_pipeline.pipeline.yml`).
> Confirm the destination table exists in Unity Catalog and rows are present.
> Come back after you verified that and tell me to continue.

```sql
SELECT * FROM <DEST_CATALOG>.<DEST_SCHEMA>.<SOURCE_TABLE_NAME> LIMIT 20;
-- Expect: UC destination table exists; rows from the SQL Server CDC source are present.
```

**Do not declare the demo complete until the user confirms the Unity Catalog destination tables look correct.**

---

## Step 5 (optional): scheduled refresh job

The bundle deploys `trigger_ingestion_pipeline` with a daily schedule (paused in development mode by default).

If the user wants scheduled refreshes in a non-dev target:

1. Uncomment and configure the `prod` target in `databricks.yml`.
2. Set production variable values under `targets.prod` in `variables.yml`.
3. Deploy to prod and enable the job schedule in the workspace UI if needed.

To run the job once manually in dev:

```bash
databricks bundle run refresh_pipeline --profile <PROFILE> --target dev
```

Expected: job `TERMINATED SUCCESS`.

When the user confirms Step 4 (and optionally Step 5), the demo is complete.

---

## Applying this beyond the demo

1. Add one `table:` block per CDC source table in `ingestion_pipeline.pipeline.yml`.
2. Use `table_configuration` for column include/exclude lists, primary keys, or `sequence_by` when needed.
3. For whole-schema ingestion, uncomment and configure the `schema:` example in the pipeline YAML.
4. Keep gateway compute in `variables.yml`; tune `gateway_cluster` only when workload size requires it.
5. Promote to production with a dedicated `prod` target and separate catalog/schema names.

## References

- [Lakeflow Connect documentation](https://docs.databricks.com/aws/en/ingestion/lakeflow-connect)
- [Databricks Asset Bundles](https://docs.databricks.com/aws/en/dev-tools/bundles/index.html)
- [Unity Catalog connections](https://docs.databricks.com/aws/en/connect/unity-catalog/cloud-services/manage-credentials)
