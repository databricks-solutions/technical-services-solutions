# CI/CD: GitHub Actions

Default CI/CD tool. Generates three workflows under `.github/workflows/`.

Reference: https://docs.databricks.com/aws/en/dev-tools/bundles/jobs-tutorial

## Required repo secrets

| Secret | Where used | Notes |
|---|---|---|
| `DATABRICKS_HOST` | all pipelines | workspace URL — store as an environment secret so staging and prod each have their own value |
| `DATABRICKS_CLIENT_ID` | all pipelines | service principal application (client) ID |
| `DATABRICKS_CLIENT_SECRET` | all pipelines | service principal client secret |

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
        run: databricks bundle validate -t staging --output json | tee bundle-validate.json

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
        run: databricks bundle validate -t staging --output json

      - name: Deploy bundle
        env:
          DATABRICKS_HOST: ${{ secrets.DATABRICKS_HOST }}
          DATABRICKS_CLIENT_ID: ${{ secrets.DATABRICKS_CLIENT_ID }}
          DATABRICKS_CLIENT_SECRET: ${{ secrets.DATABRICKS_CLIENT_SECRET }}
          DATABRICKS_BUNDLE_ENV: staging
        run: databricks bundle deploy -t staging
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
        run: databricks bundle validate -t prod --output json

      - name: Deploy bundle
        env:
          DATABRICKS_HOST: ${{ secrets.DATABRICKS_HOST }}
          DATABRICKS_CLIENT_ID: ${{ secrets.DATABRICKS_CLIENT_ID }}
          DATABRICKS_CLIENT_SECRET: ${{ secrets.DATABRICKS_CLIENT_SECRET }}
          DATABRICKS_BUNDLE_ENV: prod
        run: databricks bundle deploy -t prod
```

## Notes

- Use a GitHub `environment:` for `staging` and `prod` so each environment can hold its own `DATABRICKS_HOST` secret and you can require manual approval on prod.
- Never run `databricks repos` in any of these workflows — bundle deploy handles workspace sync.
- `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` authenticate as a service principal. Store both as repository secrets.
- Every bundle command passes `-t <target>` explicitly. `DATABRICKS_BUNDLE_ENV` is set to the same target as well; keep the two in sync.
- Catalog, schema and other non-secret per-environment values are committed per target in `databricks.yml` (`targets.<target>.variables`). Do not set `BUNDLE_VAR_catalog` or `BUNDLE_VAR_schema` in CI: `BUNDLE_VAR_*` overrides the target values, so one shared value would point every target at the same tables.
