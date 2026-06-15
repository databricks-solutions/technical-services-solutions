# CI/CD: GitHub Actions

Default CI/CD tool. Generates three workflows under `.github/workflows/`.

Reference: https://docs.databricks.com/aws/en/dev-tools/bundles/jobs-tutorial

## Required repo secrets

| Secret | Where used | Notes |
|---|---|---|
| `DATABRICKS_HOST` | all pipelines | workspace URL — store as an environment secret so staging and prod each have their own value |
| `DATABRICKS_CLIENT_ID` | all pipelines | service principal application (client) ID |
| `DATABRICKS_CLIENT_SECRET` | all pipelines | service principal client secret |
| `catalog` | all pipelines | Unity Catalog catalog name |
| `schema` | all pipelines | Unity Catalog schema name |

## `.github/workflows/pr_validate.yml`

```yaml
name: Validate bundle
on:
  pull_request:
    branches: [main]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install Databricks CLI
        uses: databricks/setup-cli@main

      - name: Validate bundle
        env:
          DATABRICKS_HOST: ${{ secrets.DATABRICKS_HOST }}
          DATABRICKS_CLIENT_ID: ${{ secrets.DATABRICKS_CLIENT_ID }}
          DATABRICKS_CLIENT_SECRET: ${{ secrets.DATABRICKS_CLIENT_SECRET }}
          DATABRICKS_BUNDLE_ENV: staging
          BUNDLE_VAR_catalog: ${{ secrets.catalog }}
          BUNDLE_VAR_schema: ${{ secrets.schema }}
        run: databricks bundle validate --output json | tee bundle-validate.json

      - uses: actions/upload-artifact@v4
        with:
          name: bundle-validate
          path: bundle-validate.json
```

## `.github/workflows/deploy_to_staging.yml`

```yaml
name: Deploy to staging
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: staging
    steps:
      - uses: actions/checkout@v4

      - name: Install Databricks CLI
        uses: databricks/setup-cli@main

      - name: Validate bundle
        env:
          DATABRICKS_HOST: ${{ secrets.DATABRICKS_HOST }}
          DATABRICKS_CLIENT_ID: ${{ secrets.DATABRICKS_CLIENT_ID }}
          DATABRICKS_CLIENT_SECRET: ${{ secrets.DATABRICKS_CLIENT_SECRET }}
          DATABRICKS_BUNDLE_ENV: staging
          BUNDLE_VAR_catalog: ${{ secrets.catalog }}
          BUNDLE_VAR_schema: ${{ secrets.schema }}
        run: databricks bundle validate --output json

      - name: Deploy bundle
        env:
          DATABRICKS_HOST: ${{ secrets.DATABRICKS_HOST }}
          DATABRICKS_CLIENT_ID: ${{ secrets.DATABRICKS_CLIENT_ID }}
          DATABRICKS_CLIENT_SECRET: ${{ secrets.DATABRICKS_CLIENT_SECRET }}
          DATABRICKS_BUNDLE_ENV: staging
          BUNDLE_VAR_catalog: ${{ secrets.catalog }}
          BUNDLE_VAR_schema: ${{ secrets.schema }}
        run: databricks bundle deploy
```

## `.github/workflows/deploy_to_prod.yml`

```yaml
name: Deploy to prod
on:
  push:
    tags: ["v*"]
  workflow_dispatch:

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: prod   # configure required reviewers in repo settings
    steps:
      - uses: actions/checkout@v4

      - name: Install Databricks CLI
        uses: databricks/setup-cli@main

      - name: Validate bundle
        env:
          DATABRICKS_HOST: ${{ secrets.DATABRICKS_HOST }}
          DATABRICKS_CLIENT_ID: ${{ secrets.DATABRICKS_CLIENT_ID }}
          DATABRICKS_CLIENT_SECRET: ${{ secrets.DATABRICKS_CLIENT_SECRET }}
          DATABRICKS_BUNDLE_ENV: prod
          BUNDLE_VAR_catalog: ${{ secrets.catalog }}
          BUNDLE_VAR_schema: ${{ secrets.schema }}
        run: databricks bundle validate --output json

      - name: Deploy bundle
        env:
          DATABRICKS_HOST: ${{ secrets.DATABRICKS_HOST }}
          DATABRICKS_CLIENT_ID: ${{ secrets.DATABRICKS_CLIENT_ID }}
          DATABRICKS_CLIENT_SECRET: ${{ secrets.DATABRICKS_CLIENT_SECRET }}
          DATABRICKS_BUNDLE_ENV: prod
          BUNDLE_VAR_catalog: ${{ secrets.catalog }}
          BUNDLE_VAR_schema: ${{ secrets.schema }}
        run: databricks bundle deploy
```

## Notes

- Use a GitHub `environment:` for `staging` and `prod` so each environment can hold its own `DATABRICKS_HOST` secret and you can require manual approval on prod.
- Never run `databricks repos` in any of these workflows — bundle deploy handles workspace sync.
- `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` authenticate as a service principal. Store both as repository secrets.
- `DATABRICKS_BUNDLE_ENV` is hardcoded per pipeline and tells the CLI which target to use (replaces the `-t` flag).
- `BUNDLE_VAR_catalog` and `BUNDLE_VAR_schema` pass the `catalog` and `schema` secrets into bundle variables via the `BUNDLE_VAR_` prefix convention.
