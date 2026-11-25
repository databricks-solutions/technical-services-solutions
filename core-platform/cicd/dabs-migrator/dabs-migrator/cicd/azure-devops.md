# CI/CD: Azure DevOps Pipelines

Generates three pipelines under `.azure-pipelines/`.

## Binding (one-time, staging and prod source targets only)

> **Dev source targets do not use this pipeline.** The first `bundle deploy -t dev` intentionally creates a new isolated dev copy — no bind needed. Only generate and run this pipeline when `source_target` is `staging` or `prod`.

Before the first recurring deploy to a staging or prod source workspace, run a one-time bind-and-deploy pipeline. Emit it as `.azure-pipelines/bind_and_deploy_<source_target>.yml`, trigger it manually once (with environment approval), and then delete the file.

```yaml
# .azure-pipelines/bind_and_deploy_<source_target>.yml
# ONE-TIME: binds migrated resources to their source workspace counterparts, checks the plan, then deploys.
# Delete this file after the first successful run.
trigger: none
pr: none

pool:
  vmImage: ubuntu-latest

variables:
  - group: databricks-bundle

stages:
  - stage: BindAndDeploy
    condition: eq(variables['Build.SourceBranch'], 'refs/heads/main')
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
                    bash scripts/auto-bind.sh <source_target> || { bash scripts/auto-bind.sh <source_target> --rollback; exit 1; }
                    bash scripts/plan-check.sh <source_target> --first-deploy || { bash scripts/auto-bind.sh <source_target> --rollback; exit 1; }
                    databricks bundle deploy -t <source_target>
                  displayName: Bind, check the plan, deploy (unbind again if anything fails)
                  env:
                    DATABRICKS_HOST: $(DATABRICKS_HOST)
                    DATABRICKS_CLIENT_ID: $(DATABRICKS_CLIENT_ID)
                    DATABRICKS_CLIENT_SECRET: $(DATABRICKS_CLIENT_SECRET)
                    DATABRICKS_BUNDLE_ENV: <source_target>
```

> The step runs `scripts/auto-bind.sh`, then `scripts/plan-check.sh --first-deploy`, and deploys only if the check passes. If binding or the check fails, `auto-bind.sh --rollback` unbinds the keys this run bound, so nothing stays half-bound. The check blocks any delete or replacement, any create of a bound key, any other create, and changes to `run_as`, schedules, catalog/schema, storage or notifications of an existing asset, unless approved in `plan-allow/<source_target>.txt` (reviewed in a pull request). The full plan is saved as `plan-<source_target>.json`.

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
                - script: bash scripts/plan-check.sh staging && databricks bundle deploy -t staging
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
                - script: bash scripts/plan-check.sh prod && databricks bundle deploy -t prod
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
