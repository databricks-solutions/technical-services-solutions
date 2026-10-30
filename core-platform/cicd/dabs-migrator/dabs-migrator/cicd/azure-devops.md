# CI/CD: Azure DevOps Pipelines

Generates three pipelines under `.azure-pipelines/`.

## Binding (one-time, source target only)

Before the first recurring deploy to the source workspace, run a one-time bind-and-deploy pipeline. Emit it as `.azure-pipelines/bind_and_deploy_<source_target>.yml`, trigger it manually once (with environment approval), and then delete the file.

```yaml
# .azure-pipelines/bind_and_deploy_<source_target>.yml
# ONE-TIME: binds migrated resources to their source workspace counterparts, then deploys.
# Delete this file after the first successful run.
trigger: none
pr: none

pool:
  vmImage: ubuntu-latest

variables:
  - group: databricks-bundle

stages:
  - stage: BindAndDeploy
    jobs:
      - deployment: bind_and_deploy
        environment: <source_target>   # add approvals/checks in the environment settings
        strategy:
          runOnce:
            deploy:
              steps:
                - checkout: self
                - script: curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh
                  displayName: Install Databricks CLI
                - script: |
                    set -euo pipefail
                    grep -v '^#' bindings/<source_target>.yml | while IFS=': ' read -r key bind_id; do
                      [ -z "$key" ] && continue
                      bind_id=$(printf '%s' "$bind_id" | tr -d '"')
                      echo "Binding $key -> $bind_id"
                      databricks bundle deployment bind "$key" "$bind_id" -t <source_target> --auto-approve
                    done
                  displayName: Bind migrated resources
                  env:
                    DATABRICKS_HOST: $(DATABRICKS_HOST)
                    DATABRICKS_CLIENT_ID: $(DATABRICKS_CLIENT_ID)
                    DATABRICKS_CLIENT_SECRET: $(DATABRICKS_CLIENT_SECRET)
                - script: |
                    set -euo pipefail
                    PLAN=$(databricks bundle plan -t <source_target> 2>&1)
                    printf '%s\n' "$PLAN"
                    if printf '%s\n' "$PLAN" | grep -qiE '\b(create|recreate|delete)\b'; then
                      echo "ERROR: Plan shows create/recreate/delete for a bound resource."
                      echo "The bind may have used the wrong ID, or the YAML config does not match the source asset."
                      echo "Review the plan output above, correct bindings/<source_target>.yml if needed, and re-run."
                      exit 1
                    fi
                    echo "Plan check passed — all bound resources will be updated in-place."
                  displayName: Plan — verify bound resources show update, not create/recreate/delete
                  env:
                    DATABRICKS_HOST: $(DATABRICKS_HOST)
                    DATABRICKS_CLIENT_ID: $(DATABRICKS_CLIENT_ID)
                    DATABRICKS_CLIENT_SECRET: $(DATABRICKS_CLIENT_SECRET)
                    DATABRICKS_BUNDLE_ENV: <source_target>
                - script: databricks bundle deploy -t <source_target>
                  displayName: Deploy bundle
                  env:
                    DATABRICKS_HOST: $(DATABRICKS_HOST)
                    DATABRICKS_CLIENT_ID: $(DATABRICKS_CLIENT_ID)
                    DATABRICKS_CLIENT_SECRET: $(DATABRICKS_CLIENT_SECRET)
                    DATABRICKS_BUNDLE_ENV: <source_target>
```

> Do **not** add `bundle deployment bind` to `pr-validate.yml`, `deploy-staging.yml`, or `deploy-prod.yml`. Binding is one-time; repeating it in recurring pipelines fails on the second run.

## Required variables (variable group `databricks-bundle`)

| Variable | Notes |
|---|---|
| `DATABRICKS_HOST` | workspace URL — use environment-scoped variable groups or pipeline variables to set a different value per environment |
| `DATABRICKS_CLIENT_ID` | secret variable, service principal application (client) ID |
| `DATABRICKS_CLIENT_SECRET` | secret variable, service principal client secret |

## `.azure-pipelines/pr-validate.yml`

```yaml
trigger: none
pr:
  branches:
    include: [main]

pool:
  vmImage: ubuntu-latest

variables:
  - group: databricks-bundle

steps:
  - script: curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh
    displayName: Install Databricks CLI

  - script: databricks bundle validate -t staging --output json | tee bundle-validate.json
    displayName: Validate bundle
    env:
      DATABRICKS_HOST: $(DATABRICKS_HOST)
      DATABRICKS_CLIENT_ID: $(DATABRICKS_CLIENT_ID)
      DATABRICKS_CLIENT_SECRET: $(DATABRICKS_CLIENT_SECRET)
      DATABRICKS_BUNDLE_ENV: staging

  - publish: bundle-validate.json
    artifact: bundle-validate
```

## `.azure-pipelines/deploy-staging.yml`

```yaml
trigger:
  branches:
    include: [main]
pr: none

pool:
  vmImage: ubuntu-latest

variables:
  - group: databricks-bundle

stages:
  - stage: Deploy
    jobs:
      - deployment: staging
        environment: staging
        strategy:
          runOnce:
            deploy:
              steps:
                - checkout: self
                - script: curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh
                  displayName: Install Databricks CLI
                - script: databricks bundle validate -t staging --output json
                  displayName: Validate bundle
                  env:
                    DATABRICKS_HOST: $(DATABRICKS_HOST)
                    DATABRICKS_CLIENT_ID: $(DATABRICKS_CLIENT_ID)
                    DATABRICKS_CLIENT_SECRET: $(DATABRICKS_CLIENT_SECRET)
                    DATABRICKS_BUNDLE_ENV: staging
                - script: databricks bundle deploy -t staging
                  displayName: Deploy bundle
                  env:
                    DATABRICKS_HOST: $(DATABRICKS_HOST)
                    DATABRICKS_CLIENT_ID: $(DATABRICKS_CLIENT_ID)
                    DATABRICKS_CLIENT_SECRET: $(DATABRICKS_CLIENT_SECRET)
                    DATABRICKS_BUNDLE_ENV: staging
```

## `.azure-pipelines/deploy-prod.yml`

```yaml
trigger:
  tags:
    include: ["v*"]
pr: none

pool:
  vmImage: ubuntu-latest

variables:
  - group: databricks-bundle

stages:
  - stage: Deploy
    jobs:
      - deployment: prod
        environment: prod   # add approvals/checks in the environment settings
        strategy:
          runOnce:
            deploy:
              steps:
                - checkout: self
                - script: curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh
                  displayName: Install Databricks CLI
                - script: databricks bundle validate -t prod --output json
                  displayName: Validate bundle
                  env:
                    DATABRICKS_HOST: $(DATABRICKS_HOST)
                    DATABRICKS_CLIENT_ID: $(DATABRICKS_CLIENT_ID)
                    DATABRICKS_CLIENT_SECRET: $(DATABRICKS_CLIENT_SECRET)
                    DATABRICKS_BUNDLE_ENV: prod
                - script: databricks bundle deploy -t prod
                  displayName: Deploy bundle
                  env:
                    DATABRICKS_HOST: $(DATABRICKS_HOST)
                    DATABRICKS_CLIENT_ID: $(DATABRICKS_CLIENT_ID)
                    DATABRICKS_CLIENT_SECRET: $(DATABRICKS_CLIENT_SECRET)
                    DATABRICKS_BUNDLE_ENV: prod
```

## Notes

- Configure approvals on the `prod` Environment in Azure DevOps Project Settings → Environments.
- Mark `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` as secret in the variable group.
- Every bundle command passes `-t <target>` explicitly. `DATABRICKS_BUNDLE_ENV` is set to the same target as well; keep the two in sync.
- Catalog, schema and other non-secret per-environment values are committed per target in `databricks.yml` (`targets.<target>.variables`). Do not set `BUNDLE_VAR_catalog` or `BUNDLE_VAR_schema` in CI: `BUNDLE_VAR_*` overrides the target values, so one shared value would point every target at the same tables.
