# CI/CD: Azure DevOps Pipelines

Generates three pipelines under `.azure-pipelines/`.

## Required variables (variable group `databricks-bundle`)

| Variable | Notes |
|---|---|
| `DATABRICKS_HOST` | workspace URL — use environment-scoped variable groups or pipeline variables to set a different value per environment |
| `DATABRICKS_CLIENT_ID` | secret variable, service principal application (client) ID |
| `DATABRICKS_CLIENT_SECRET` | secret variable, service principal client secret |
| `catalog` | secret variable, Unity Catalog catalog name |
| `schema` | secret variable, Unity Catalog schema name |

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

  - script: databricks bundle validate --output json | tee bundle-validate.json
    displayName: Validate bundle
    env:
      DATABRICKS_HOST: $(DATABRICKS_HOST)
      DATABRICKS_CLIENT_ID: $(DATABRICKS_CLIENT_ID)
      DATABRICKS_CLIENT_SECRET: $(DATABRICKS_CLIENT_SECRET)
      DATABRICKS_BUNDLE_ENV: staging
      BUNDLE_VAR_catalog: $(catalog)
      BUNDLE_VAR_schema: $(schema)

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
                - script: databricks bundle validate --output json
                  displayName: Validate bundle
                  env:
                    DATABRICKS_HOST: $(DATABRICKS_HOST)
                    DATABRICKS_CLIENT_ID: $(DATABRICKS_CLIENT_ID)
                    DATABRICKS_CLIENT_SECRET: $(DATABRICKS_CLIENT_SECRET)
                    DATABRICKS_BUNDLE_ENV: staging
                    BUNDLE_VAR_catalog: $(catalog)
                    BUNDLE_VAR_schema: $(schema)
                - script: databricks bundle deploy
                  displayName: Deploy bundle
                  env:
                    DATABRICKS_HOST: $(DATABRICKS_HOST)
                    DATABRICKS_CLIENT_ID: $(DATABRICKS_CLIENT_ID)
                    DATABRICKS_CLIENT_SECRET: $(DATABRICKS_CLIENT_SECRET)
                    DATABRICKS_BUNDLE_ENV: staging
                    BUNDLE_VAR_catalog: $(catalog)
                    BUNDLE_VAR_schema: $(schema)
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
                - script: databricks bundle validate --output json
                  displayName: Validate bundle
                  env:
                    DATABRICKS_HOST: $(DATABRICKS_HOST)
                    DATABRICKS_CLIENT_ID: $(DATABRICKS_CLIENT_ID)
                    DATABRICKS_CLIENT_SECRET: $(DATABRICKS_CLIENT_SECRET)
                    DATABRICKS_BUNDLE_ENV: prod
                    BUNDLE_VAR_catalog: $(catalog)
                    BUNDLE_VAR_schema: $(schema)
                - script: databricks bundle deploy
                  displayName: Deploy bundle
                  env:
                    DATABRICKS_HOST: $(DATABRICKS_HOST)
                    DATABRICKS_CLIENT_ID: $(DATABRICKS_CLIENT_ID)
                    DATABRICKS_CLIENT_SECRET: $(DATABRICKS_CLIENT_SECRET)
                    DATABRICKS_BUNDLE_ENV: prod
                    BUNDLE_VAR_catalog: $(catalog)
                    BUNDLE_VAR_schema: $(schema)
```

## Notes

- Configure approvals on the `prod` Environment in Azure DevOps Project Settings → Environments.
- Mark `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET`, `catalog`, and `schema` as secret in the variable group.
- `DATABRICKS_BUNDLE_ENV` is hardcoded per pipeline and tells the CLI which target to use (replaces the `-t` flag).
- `BUNDLE_VAR_catalog` and `BUNDLE_VAR_schema` pass the `catalog` and `schema` variables into bundle variables via the `BUNDLE_VAR_` prefix convention.
