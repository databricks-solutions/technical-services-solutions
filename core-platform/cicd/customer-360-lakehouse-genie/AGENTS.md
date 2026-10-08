# Deploy — Customer 360 Lakehouse

Workflow-only example (no app or serving components). Because of a `genie_spaces`
ordering constraint, deploy is a **3-phase flow** (deploy all-except-Genie → run
the setup job to build the tables → full deploy adds Genie) — see the section
below. `deploy` creates the resources (schema, volume, pipeline, dashboard, Genie
space, setup job); `run` executes the setup job that builds/populates them.

## Prerequisites
- Databricks CLI **v1.3.0+** (required for the `genie_spaces` resource + `engine: direct`).
- A CLI profile with workspace auth (`--profile <name>` or `DATABRICKS_CONFIG_PROFILE`).
- A SQL Warehouse ID (powers the dashboard + Genie space).

## Deploy — a 3-phase flow (important: read this)

This bundle deploys in **three steps**, not one — because of how the Genie space
resource works. The `genie_spaces` resource **validates that its bound tables
exist at deploy time**, but those tables are *built by the setup job at run
time*. So a plain `bundle deploy` fails on the Genie space (its tables don't
exist yet). The fix: deploy everything **except** Genie, run the job to build the
tables, then deploy again to add Genie. See **Known limitations** in the README.

### Deploy (dev)

```bash
# Phase 1 — deploy everything EXCEPT the Genie space (its tables don't exist yet).
databricks bundle deploy -t dev --var warehouse_id=<your-warehouse-id> \
  --select schemas.customer360_schema,volumes.raw_data,pipelines.customer360_pipeline,dashboards.customer360_dashboard,jobs.customer360_setup

# Phase 2 — run the setup job to BUILD the tables:
#           generate_data → run_pipeline → deploy_metric_view + validate_metrics
databricks bundle run -t dev customer360_setup --var warehouse_id=<your-warehouse-id>

# Phase 3 — full deploy: the Genie space's tables now exist, so it validates + creates.
databricks bundle deploy -t dev --var warehouse_id=<your-warehouse-id>
```

`dev` is the default target — host comes from your CLI profile (`--profile …`).
`catalog` ships as the placeholder `<your_catalog>`; `schema` defaults to
`customer_360_demo`. **Before your first deploy, set `catalog` (in `databricks.yml`
or via `--var catalog=…`) to an existing catalog AND edit the `identifier` values
in `src/genie/genie_space.json` to the same catalog** — the Genie space's table
references are hardcoded there (the `genie_spaces` resource does not substitute
`${var...}` into its `file_path` JSON), so the two must agree or the space's
tables won't resolve (see README "Known limitations"). Once set, keep it fixed:
dev and prod are isolated at the **workspace level** (separate workspaces), both
using the same catalog/schema.

### Deploy (prod)

Prod is a **separate workspace** and runs as a **service principal**. Same
3-phase flow. Point the CLI at the prod workspace with the **`DATABRICKS_HOST`
env var** (`workspace.host` can't be `${var}`-interpolated — this is what the
CI/CD pipelines do), and set the SP application ID via `--var
prod_service_principal=<app-id>`:

```bash
# Point at the prod workspace (auth via OAuth M2M — see CI/CD below).
export DATABRICKS_HOST=https://<your-prod-workspace>.cloud.databricks.com
export DATABRICKS_CLIENT_ID=<prod-sp-application-id>
export DATABRICKS_CLIENT_SECRET=<prod-sp-oauth-secret>

# Phase 1 — everything except Genie
databricks bundle deploy -t prod \
  --var warehouse_id=<id> \
  --var prod_service_principal=<prod-sp-application-id> \
  --select schemas.customer360_schema,volumes.raw_data,pipelines.customer360_pipeline,dashboards.customer360_dashboard,jobs.customer360_setup

# Phase 2 — build the tables
databricks bundle run -t prod customer360_setup --var warehouse_id=<id> \
  --var prod_service_principal=<prod-sp-application-id>

# Phase 3 — full deploy (adds Genie)
databricks bundle deploy -t prod \
  --var warehouse_id=<id> \
  --var prod_service_principal=<prod-sp-application-id>
```

> Alternatively, use a CLI `--profile <prod>` whose host is the prod workspace
> instead of the `DATABRICKS_HOST` export. Either way, don't set `workspace.host`
> in `databricks.yml` — a literal there would override this.

Prod uses the same catalog/schema (isolation is by workspace, not by name) and
`run_as` the service principal — so the identity that deploys is the identity
that runs the deployed jobs/pipelines. Set `prod_service_principal` to that SP's
application ID (it must match the SP whose OAuth credentials you authenticate
with).

## CI/CD (GitHub Actions, Azure DevOps, GitLab, Jenkins)

This bundle ships ready-to-use CI/CD pipelines for four platforms — pick the one
that matches your stack:

| Platform | File |
|---|---|
| GitHub Actions | `.github/workflows/deploy.yml` |
| Azure DevOps   | `azure-pipelines.yml` |
| GitLab         | `.gitlab-ci.yml` |
| Jenkins        | `Jenkinsfile` |

**What they do (same strategy in all four — the full lifecycle):**
1. **Push to a `feature/**` branch** → `validate` + `deploy -t dev` (your inner loop).
2. **Pull request → `main`** → `validate` only (a cheap, no-compute merge gate).
3. **Merge/push to `main`** → `deploy -t prod`, authenticated **as a service principal**.

**Auth — OAuth machine-to-machine (M2M).** The CLI reads three environment
variables per environment: `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`,
`DATABRICKS_CLIENT_SECRET`. Use **one service principal per environment** (a dev
SP and a prod SP). The prod SP is also the `run_as` identity, so the deploying
identity is the one that runs the deployed jobs/pipelines: the prod pipelines
pass `--var prod_service_principal=$PROD_CLIENT_ID` (a SP's OAuth **client id** is
its **application id**), which sets `run_as.service_principal_name` on the `prod`
target automatically — you don't configure it separately.

**Secrets to configure** (in your CI platform's secret store):

| Purpose | GitHub / Azure / GitLab variable | Jenkins credential ID |
|---|---|---|
| Dev workspace URL | `DEV_DATABRICKS_HOST` | `dev-databricks-host` |
| Dev SP application ID | `DEV_CLIENT_ID` | `dev-databricks-client-id` |
| Dev SP OAuth secret | `DEV_CLIENT_SECRET` | `dev-databricks-client-secret` |
| Dev SQL warehouse ID | `DEV_WAREHOUSE_ID` | `dev-databricks-warehouse-id` |
| Prod workspace URL | `PROD_DATABRICKS_HOST` | `prod-databricks-host` |
| Prod SP application ID | `PROD_CLIENT_ID` | `prod-databricks-client-id` |
| Prod SP OAuth secret | `PROD_CLIENT_SECRET` | `prod-databricks-client-secret` |
| Prod SQL warehouse ID | `PROD_WAREHOUSE_ID` | `prod-databricks-warehouse-id` |

Where to store them: **GitHub** → Settings → Secrets and variables → Actions.
**Azure DevOps** → Pipeline → Edit → Variables (mark secret). **GitLab** →
Settings → CI/CD → Variables (masked + protected). **Jenkins** → Manage Jenkins →
Credentials (Secret text, one per ID above; requires a *multibranch* pipeline).

**Notes:**
- Adjust the `feature/**` branch glob in each file to your team's branch convention.
- **GitLab** has no official Databricks CI/CD reference — that file follows the
  standard CLI pattern (and uses the official CLI image, not `pip install`).
- **Public-repo / fork caution:** don't let PRs from untrusted forks trigger a
  deploy — that would expose your SP secrets. Harden before enabling on a public repo.

## Re-runs
All phases are idempotent. Once the tables exist, a routine content change just
needs a single `bundle deploy` (Phase 3) — the Genie space is a native
`genie_spaces` resource, so `bundle deploy` reconciles it in place. Re-run the
setup job (Phase 2) as well if the generated data or the metric view changed. You
only need the full 3-phase sequence again on a clean workspace where the tables
don't yet exist.

## Teardown
```bash
databricks bundle destroy            # add -t prod for the prod target
```
Removes the bundle-managed resources (pipeline, dashboard, Genie space, and job).
Does NOT drop the UC schema/tables/volume (delete those manually if you want a
full cleanup).
