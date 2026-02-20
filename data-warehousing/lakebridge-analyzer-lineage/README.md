# Migration Accelerator (Lakebridge Analyzer Lineage)

Databricks App that assesses ETL migration complexity and visualizes data lineage from Lakebridge analyzer reports. It supports file upload, dashboard metrics, interactive lineage graphs, and JSON export.

## Prerequisites

- **Databricks CLI** 0.283.0 or higher: [Install](https://docs.databricks.com/dev-tools/cli/install.html)
- **Workspace** access (AWS, Azure, or GCP)
- **Permissions**: Workspace Admin (or ability to create Apps), Unity Catalog volume create/manage

## 1. Prepare environment

### Unity Catalog

Create a catalog, schema, and volume for app storage. Run in your workspace (SQL):

```sql
CREATE CATALOG IF NOT EXISTS my_catalog;
CREATE SCHEMA IF NOT EXISTS my_catalog.migration_accelerator;
CREATE VOLUME IF NOT EXISTS my_catalog.migration_accelerator.app_storage;

GRANT READ VOLUME, WRITE VOLUME
ON VOLUME my_catalog.migration_accelerator.app_storage
TO `users`;

SHOW VOLUMES IN my_catalog.migration_accelerator;
```

Note the full volume path (e.g. `/Volumes/my_catalog/migration_accelerator/app_storage`) for the next step.

### CLI auth

```bash
databricks auth login
```

Use your workspace URL when prompted (e.g. `https://your-workspace.cloud.databricks.com`).

## 2. Configure and deploy

### Set volume path

In `databricks.yml`, under `targets.dev.variables` and `targets.prod.variables`, set `uc_volume_path` to your volume path from step 1:

```yaml
variables:
  uc_volume_path: /Volumes/my_catalog/migration_accelerator/app_storage
```

### Deploy and run

From the project root:

```bash
# Deploy
databricks bundle deploy -t dev
# or: databricks bundle deploy -t prod

# Run the app (installs deps, builds frontend, starts services; ~2–3 min)
databricks bundle run migration-accelerator -t dev
# or: databricks bundle run migration-accelerator -t prod
```

With a named CLI profile:

```bash
databricks bundle deploy -t prod --profile my-profile
databricks bundle run migration-accelerator -t prod --profile my-profile
```

## 3. Verify and use

- **Status**: `databricks apps get migration-accelerator` (expect `RUNNING`)
- **Logs**: `databricks apps logs migration-accelerator --tail 100` (add `--follow` to stream)
- **Health**: `curl https://<workspace-host>/apps/migration-accelerator/health` → `{"status":"healthy","version":"..."}`
- **URL**: `https://<workspace-host>/apps/migration-accelerator`

Access uses Databricks user identity; files are isolated per user. Users need the volume grants above.

## 4. Common commands

| Action        | Command |
|---------------|--------|
| App details   | `databricks apps get migration-accelerator` |
| Logs          | `databricks apps logs migration-accelerator --tail 100` |
| Stop          | `databricks apps stop migration-accelerator` |
| Start         | `databricks apps start migration-accelerator` |
| Delete app    | `databricks apps delete migration-accelerator` |
| Bundle summary| `databricks bundle summary -t prod` |

## 5. Troubleshooting

| Issue | What to check |
|-------|----------------|
| Deploy fails | CLI config, workspace URL/token, `databricks bundle deploy -t prod --debug` |
| App ERROR / won’t start | Correct `uc_volume_path` in `databricks.yml`; catalog/schema/volume exist; `databricks apps logs migration-accelerator` for build/runtime errors |
| Permission errors in app | Re-run `GRANT READ VOLUME, WRITE VOLUME` on the volume for `users`; `SHOW GRANTS ON VOLUME ...` |
| Frontend 500 / backend unreachable | Logs for backend errors; confirm both frontend and backend started; `UC_VOLUME_PATH` set from bundle |

## Project layout

- `databricks.yml` – Bundle and app config (targets, env, `uc_volume_path`)
- `src/migration_accelerator/` – Python backend (API, lineage, analyzer, storage)
- `frontend/` – Next.js UI
- `app.yaml` – App runtime config (if present)

## References

- [Databricks Apps](https://docs.databricks.com/dev-tools/databricks-apps/)
- [Databricks CLI](https://docs.databricks.com/dev-tools/cli/)
