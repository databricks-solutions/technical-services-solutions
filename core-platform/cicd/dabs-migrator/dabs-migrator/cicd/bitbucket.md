# CI/CD: Bitbucket Pipelines

Single `bitbucket-pipelines.yml` at repo root.

## Binding (one-time, staging and prod source targets only)

> **Dev source targets do not use this pipeline.** The first `bundle deploy -t dev` intentionally creates a new isolated dev copy — no bind needed. Only generate and run this pipeline when `source_target` is `staging` or `prod`.

Before the first recurring deploy to a staging or prod source workspace, add a custom pipeline to `bitbucket-pipelines.yml`, trigger it manually once from the Bitbucket UI (Pipelines → Run pipeline → custom), and then remove the step.

```yaml
# Add temporarily under pipelines.custom in bitbucket-pipelines.yml. Remove after the first successful run.
# Custom pipelines are started manually (Pipelines > Run pipeline). Restrict the <source_target>
# deployment environment to the main branch in Repository settings > Deployments.
# DATABRICKS_HOST, DATABRICKS_CLIENT_ID and DATABRICKS_CLIENT_SECRET come from the deployment variables.
pipelines:
  custom:
    bind-and-deploy-<source_target>:
      - step:
          name: "Bind and deploy (one-time, <source_target>)"
          deployment: <source_target>
          script:
            - apt-get update && apt-get install -y curl ca-certificates jq
            - curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh
            - export DATABRICKS_BUNDLE_ENV=<source_target>
            - bash scripts/auto-bind.sh <source_target> || { bash scripts/auto-bind.sh <source_target> --rollback; exit 1; }
            - bash scripts/plan-check.sh <source_target> --first-deploy || { bash scripts/auto-bind.sh <source_target> --rollback; exit 1; }
            - databricks bundle deploy -t <source_target>
          artifacts:
            - plan-<source_target>.json
```

> The step runs `scripts/auto-bind.sh`, then `scripts/plan-check.sh --first-deploy`, and deploys only if the check passes. If binding or the check fails, `auto-bind.sh --rollback` unbinds the keys this run bound, so nothing stays half-bound. The check blocks any delete or replacement, any create of a bound key, any other create, and changes to `run_as`, schedules, catalog/schema, storage or notifications of an existing asset, unless approved in `plan-allow/<source_target>.txt` (reviewed in a pull request). The full plan is saved as `plan-<source_target>.json`.

> Do **not** add `bundle deployment bind` to the pull-request, `main`, or `v*` tag pipelines. Binding is one-time; repeating it in recurring steps fails on the second run.

## Required repository variables

| Variable | Secured |
|---|---|
| `DATABRICKS_HOST` | yes — use Deployment variables scoped to `staging` / `production` for different values per environment |
| `DATABRICKS_CLIENT_ID` | yes |
| `DATABRICKS_CLIENT_SECRET` | yes |

## `bitbucket-pipelines.yml`

```yaml
image: ubuntu:24.04

definitions:
  steps:
    - step: &install-cli
        name: Install Databricks CLI
        script:
          - apt-get update && apt-get install -y curl ca-certificates jq
          - curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh

    - step: &validate
        name: Validate bundle
        script:
          - apt-get update && apt-get install -y curl ca-certificates jq
          - curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh
          - export DATABRICKS_HOST=$DATABRICKS_HOST
          - export DATABRICKS_CLIENT_ID=$DATABRICKS_CLIENT_ID
          - export DATABRICKS_CLIENT_SECRET=$DATABRICKS_CLIENT_SECRET
          - export DATABRICKS_BUNDLE_ENV=staging
          - databricks bundle validate -t staging --output json | tee bundle-validate.json
        artifacts:
          - bundle-validate.json

pipelines:
  pull-requests:
    "**":
      - step: *validate

  branches:
    main:
      - step: *validate
      - step:
          name: Deploy to staging
          deployment: staging
          script:
            - apt-get update && apt-get install -y curl ca-certificates jq
            - curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh
            - export DATABRICKS_HOST=$DATABRICKS_HOST
            - export DATABRICKS_CLIENT_ID=$DATABRICKS_CLIENT_ID
            - export DATABRICKS_CLIENT_SECRET=$DATABRICKS_CLIENT_SECRET
            - export DATABRICKS_BUNDLE_ENV=staging
            - databricks bundle validate -t staging --output json
            - bash scripts/plan-check.sh staging && databricks bundle deploy -t staging

  tags:
    "v*":
      - step:
          name: Deploy to prod
          deployment: production
          trigger: manual
          script:
            - apt-get update && apt-get install -y curl ca-certificates jq
            - curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh
            - export DATABRICKS_HOST=$DATABRICKS_HOST
            - export DATABRICKS_CLIENT_ID=$DATABRICKS_CLIENT_ID
            - export DATABRICKS_CLIENT_SECRET=$DATABRICKS_CLIENT_SECRET
            - export DATABRICKS_BUNDLE_ENV=prod
            - databricks bundle validate -t prod --output json
            - bash scripts/plan-check.sh prod && databricks bundle deploy -t prod
```

## Notes

- `trigger: manual` on the prod step requires an explicit click in the Bitbucket UI.
- Use **Deployment variables** scoped to `staging` / `production` so each deployment environment supplies its own `DATABRICKS_HOST`.
- Mark `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` as secured repository variables.
- Every bundle command passes `-t <target>` explicitly. `DATABRICKS_BUNDLE_ENV` is set to the same target as well; keep the two in sync.
- Catalog, schema and other non-secret per-environment values are committed per target in `databricks.yml` (`targets.<target>.variables`). Do not set `BUNDLE_VAR_catalog` or `BUNDLE_VAR_schema` in CI: `BUNDLE_VAR_*` overrides the target values, so one shared value would point every target at the same tables.
