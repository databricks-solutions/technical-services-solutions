# CI/CD: Bitbucket Pipelines

Single `bitbucket-pipelines.yml` at repo root.

## Required repository variables

| Variable | Secured |
|---|---|
| `DATABRICKS_HOST` | yes — use Deployment variables scoped to `staging` / `production` for different values per environment |
| `DATABRICKS_CLIENT_ID` | yes |
| `DATABRICKS_CLIENT_SECRET` | yes |
| `catalog` | yes |
| `schema` | yes |

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
          - export BUNDLE_VAR_catalog=$catalog
          - export BUNDLE_VAR_schema=$schema
          - databricks bundle validate --output json | tee bundle-validate.json
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
            - export BUNDLE_VAR_catalog=$catalog
            - export BUNDLE_VAR_schema=$schema
            - databricks bundle validate --output json
            - databricks bundle deploy

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
            - export BUNDLE_VAR_catalog=$catalog
            - export BUNDLE_VAR_schema=$schema
            - databricks bundle validate --output json
            - databricks bundle deploy
```

## Notes

- `trigger: manual` on the prod step requires an explicit click in the Bitbucket UI.
- Use **Deployment variables** scoped to `staging` / `production` so each deployment environment supplies its own `DATABRICKS_HOST`.
- Mark `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET`, `catalog`, and `schema` as secured repository variables.
- `DATABRICKS_BUNDLE_ENV` is hardcoded per step and tells the CLI which target to use (replaces the `-t` flag).
- `BUNDLE_VAR_catalog` and `BUNDLE_VAR_schema` pass the `catalog` and `schema` variables into bundle variables via the `BUNDLE_VAR_` prefix convention.
