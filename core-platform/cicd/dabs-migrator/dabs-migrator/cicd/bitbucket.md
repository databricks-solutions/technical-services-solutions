# CI/CD: Bitbucket Pipelines

Single `bitbucket-pipelines.yml` at repo root.

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
          - apt-get update && apt-get install -y curl ca-certificates
          - curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh

    - step: &validate
        name: Validate bundle
        script:
          - apt-get update && apt-get install -y curl ca-certificates
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
            - apt-get update && apt-get install -y curl ca-certificates
            - curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh
            - export DATABRICKS_HOST=$DATABRICKS_HOST
            - export DATABRICKS_CLIENT_ID=$DATABRICKS_CLIENT_ID
            - export DATABRICKS_CLIENT_SECRET=$DATABRICKS_CLIENT_SECRET
            - export DATABRICKS_BUNDLE_ENV=staging
            - databricks bundle validate -t staging --output json
            - databricks bundle deploy -t staging

  tags:
    "v*":
      - step:
          name: Deploy to prod
          deployment: production
          trigger: manual
          script:
            - apt-get update && apt-get install -y curl ca-certificates
            - curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh
            - export DATABRICKS_HOST=$DATABRICKS_HOST
            - export DATABRICKS_CLIENT_ID=$DATABRICKS_CLIENT_ID
            - export DATABRICKS_CLIENT_SECRET=$DATABRICKS_CLIENT_SECRET
            - export DATABRICKS_BUNDLE_ENV=prod
            - databricks bundle validate -t prod --output json
            - databricks bundle deploy -t prod
```

## Notes

- `trigger: manual` on the prod step requires an explicit click in the Bitbucket UI.
- Use **Deployment variables** scoped to `staging` / `production` so each deployment environment supplies its own `DATABRICKS_HOST`.
- Mark `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` as secured repository variables.
- Every bundle command passes `-t <target>` explicitly. `DATABRICKS_BUNDLE_ENV` is set to the same target as well; keep the two in sync.
- Catalog, schema and other non-secret per-environment values are committed per target in `databricks.yml` (`targets.<target>.variables`). Do not set `BUNDLE_VAR_catalog` or `BUNDLE_VAR_schema` in CI: `BUNDLE_VAR_*` overrides the target values, so one shared value would point every target at the same tables.
