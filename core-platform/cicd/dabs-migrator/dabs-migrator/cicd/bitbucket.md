# CI/CD: Bitbucket Pipelines

Single `bitbucket-pipelines.yml` at repo root.

## Binding (one-time, staging and prod source targets only)

> **Dev source targets do not use this pipeline.** The first `bundle deploy -t dev` intentionally creates a new isolated dev copy — no bind needed. Only generate and run this pipeline when `source_target` is `staging` or `prod`.

Before the first recurring deploy to a staging or prod source workspace, add a custom pipeline to `bitbucket-pipelines.yml`, trigger it manually once from the Bitbucket UI (Pipelines → Run pipeline → custom), and then remove the step.

```yaml
# Add temporarily under pipelines.custom in bitbucket-pipelines.yml.
# Remove after the first successful run.
pipelines:
  custom:
    bind-and-deploy-<source_target>:
      - step:
          name: "Bind and deploy (one-time, <source_target>)"
          deployment: <source_target>
          trigger: manual
          script:
            - apt-get update && apt-get install -y curl ca-certificates
            - curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh
            - bash scripts/auto-bind.sh <source_target>
            - |
              set -euo pipefail
              PLAN_JSON=$(databricks bundle plan -t <source_target> -o json 2>&1)
              printf '%s\n' "$PLAN_JSON" | jq .
              if echo "$PLAN_JSON" | jq -e '[.plan | to_entries[] | select(.value.action == "recreate" or .value.action == "delete")] | length > 0' &>/dev/null; then
                echo "ERROR: Plan shows recreate/delete — config mismatch or wrong bind ID."; exit 1
              fi
              if [[ -f "bindings/<source_target>.yml" ]]; then
                while IFS= read -r line; do
                  [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
                  key=$(echo "$line" | cut -d: -f1 | tr -d ' '); [[ -z "$key" ]] && continue
                  if echo "$PLAN_JSON" | jq -e --arg k "$key" '[.plan | to_entries[] | select(.key | endswith("." + $k)) | select(.value.action == "create")] | length > 0' &>/dev/null; then
                    echo "ERROR: Bound resource '$key' plans as 'create' — bind may have failed."; exit 1
                  fi
                done < "bindings/<source_target>.yml"
              fi
              echo "Plan check passed."
            - databricks bundle deploy -t <source_target>
          script_env:
            DATABRICKS_HOST: $DATABRICKS_HOST
            DATABRICKS_CLIENT_ID: $DATABRICKS_CLIENT_ID
            DATABRICKS_CLIENT_SECRET: $DATABRICKS_CLIENT_SECRET
            DATABRICKS_BUNDLE_ENV: <source_target>
```

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
