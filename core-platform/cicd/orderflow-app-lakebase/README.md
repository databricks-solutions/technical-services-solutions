# OrderFlow — end-to-end Databricks template

A complete, production-shaped **order & inventory management** application built on the
Databricks developer stack. It is designed to be **cloned and adapted** by customers as a
reference for how the pieces fit together end-to-end.

```
┌──────────────┐   writes/reads    ┌─────────────────────┐
│ Databricks   │◄─────────────────►│ Lakebase (Postgres) │   OLTP: products, orders,
│ App          │  CRUD over HTTP   │  project: orderflow │   customers, order_items
│ React+FastAPI│                   └──────────┬──────────┘
└──────────────┘                              │ ingest (job task 1)
        ▲                                      ▼
        │ browse analytics          ┌─────────────────────┐
        │                           │ UC bronze tables    │
        │                           └──────────┬──────────┘
        │                                      │ Lakeflow pipeline (job task 2)
        │                                      ▼
        │                           ┌─────────────────────┐
        └───────────────────────────│ UC silver + gold    │  analytics: category sales,
                                     │  + daily snapshot   │  status funnel, low stock
                                     └─────────────────────┘  (job task 3: daily rollup)
```

## What's in the box

| Layer | Component | Path |
|---|---|---|
| **Transactional DB** | Lakebase (managed serverless Postgres) | `scripts/schema.sql`, `scripts/seed.sql` |
| **App** | React + FastAPI CRUD app, Databricks-branded | `app/` |
| **Pipeline** | Lakeflow declarative medallion transform | `pipeline/transformations.py` |
| **Job** | Ingest → pipeline → daily rollup, scheduled | `jobs/`, `resources/job.yml` |
| **IaC** | Databricks Asset Bundle wiring everything | `databricks.yml`, `resources/*.yml` |
| **CI/CD** | GitHub Actions validate + deploy | `.github/workflows/` |

## Prerequisites

- Databricks CLI `v1.0+` — `databricks version`
- An FE-VM **serverless** workspace (required for Lakebase + Apps)
- Node 22+, Python 3.11+, `uv`, and a Postgres client (`psql`)
- An authenticated CLI profile:
  ```bash
  databricks auth login --host <workspace-url> --profile <profile>
  ```

## Quick start

The Lakebase project, branch, endpoint, database, and role are all declared as
bundle resources (`resources/lakebase.yml`) — `bundle deploy` provisions them.

```bash
# 1. Create the analytics schema in Unity Catalog (pipeline output target)
databricks schemas create orderflow <catalog> -p <profile>

# 2. Deploy everything — provisions Lakebase + app + pipeline + job + volume
cd app/frontend && npm ci && npm run build && cd ../..
databricks bundle deploy -t dev -p <profile>

# 3. Apply the OLTP schema + seed data to the new Lakebase database, and grant
#    the app's service principal access to the tables.
PROFILE=<profile> ./scripts/init_db.sh
APP_SP_CLIENT_ID=$(databricks apps get orderflow-app -p <profile> -o json \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['service_principal_client_id'])")
PROFILE=<profile> APP_SP_CLIENT_ID=$APP_SP_CLIENT_ID ./scripts/grant_app_role.sh

# 4. Deploy the app source, then kick off the data job (ingest → pipeline → rollup)
databricks apps deploy orderflow-app \
  --source-code-path "$(databricks bundle summary -t dev -o json -p <profile> \
    | python3 -c "import sys,json;print(json.load(sys.stdin)['workspace']['file_path'])")/app" \
  -p <profile>
databricks bundle run orderflow_job -t dev -p <profile>
```

> **Note on Lakebase + bundles:** creating a `postgres_project` auto-provisions a
> `production` branch, `primary` endpoint, and a user role. The bundle declares those
> explicitly; on first deploy in an existing workspace you may need to
> `databricks bundle deployment bind <resource_key> <resource_id>` to adopt the
> auto-created branch/endpoint/role (see `docs/ARCHITECTURE.md`).

## Configuration

Variables are **declared** (description only) in the top-level `variables` block of
`databricks.yml`, and their **values are set per target** under `targets.<env>.variables`.
This keeps each environment explicit and self-contained.

| Variable | Meaning |
|---|---|
| `catalog` / `schema` | Where the medallion tables are written |
| `lakebase_host` | The Lakebase endpoint hostname (from `databricks postgres list-endpoints`) |
| `lakebase_endpoint_name` | Full endpoint path used to mint OAuth tokens |
| `lakebase_database` | Postgres database name |
| `notification_email` | Job failure alerts |

To point the template at a different workspace, edit the target's `host` and its
`variables:` values (e.g. under `targets.prod`), then `databricks bundle deploy -t prod`.

## Local development

```bash
# Backend (terminal 1)
cd app
export DATABRICKS_PROFILE=<profile>
export ENDPOINT_NAME="projects/orderflow-db/branches/production/endpoints/primary"
export LAKEBASE_HOST="<endpoint-host>"
export LAKEBASE_DATABASE="orderflow"
uv run uvicorn app:app --reload --port 8000

# Frontend (terminal 2) — proxies /api to :8000
cd app/frontend && npm run dev   # http://localhost:5173
```

## CI/CD

`.github/workflows/ci.yml` validates the bundle and builds the app on every PR.
`.github/workflows/deploy.yml` deploys on push to `main`. Configure these repo secrets:

- `DATABRICKS_HOST`
- `DATABRICKS_CLIENT_ID` / `DATABRICKS_CLIENT_SECRET` (a service principal with deploy rights)

## How authentication works (no stored passwords)

The app never stores a database password. Lakebase is attached as an **app resource**, so
`PGHOST`/`PGUSER`/`PGPORT`/`PGDATABASE` are injected at runtime; the app then mints a short-lived
OAuth token per connection via `w.postgres.generate_database_credential(...)` (see
`app/server/db.py`). The connection pool recycles connections before the 1-hour token expires.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for a deeper walkthrough.
