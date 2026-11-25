# CI/CD: GitHub Actions

Default CI/CD tool. Generates three workflows under `.github/workflows/`.

Reference: https://docs.databricks.com/aws/en/dev-tools/bundles/jobs-tutorial

## Binding (one-time, staging and prod source targets only)

> **Dev source targets do not use this workflow.** The first `bundle deploy -t dev` intentionally creates a new isolated dev copy — no bind needed. Only generate and run this workflow when `source_target` is `staging` or `prod`.

Before the first recurring deploy to a staging or prod source workspace, run a one-time bind-and-deploy workflow that links each bundle resource to its existing workspace counterpart. This workflow is separate from the three recurring files below. Emit it as `.github/workflows/bind_and_deploy_<source_target>.yml`, run it once with environment approval, and then delete the file.

```yaml
# .github/workflows/bind_and_deploy_<source_target>.yml
# ONE-TIME: binds migrated resources to their source workspace counterparts, checks the plan, then deploys.
# Delete this file after the first successful run.
name: "Bind and deploy (one-time, <source_target>)"
on:
  workflow_dispatch:

jobs:
  bind-and-deploy:
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    environment: <source_target>   # required reviewers + deployment branch rule (main only) in repo settings
    steps:
      - uses: actions/checkout@v4

      - name: Install Databricks CLI
        uses: databricks/setup-cli@main

      - name: Bind, check the plan, deploy (unbind again if anything fails)
        shell: bash
        env:
          DATABRICKS_HOST: ${{ secrets.DATABRICKS_HOST }}
          DATABRICKS_CLIENT_ID: ${{ secrets.DATABRICKS_CLIENT_ID }}
          DATABRICKS_CLIENT_SECRET: ${{ secrets.DATABRICKS_CLIENT_SECRET }}
          DATABRICKS_BUNDLE_ENV: <source_target>
        run: |
          set -euo pipefail
          bash scripts/auto-bind.sh <source_target> || { bash scripts/auto-bind.sh <source_target> --rollback; exit 1; }
          bash scripts/plan-check.sh <source_target> --first-deploy || { bash scripts/auto-bind.sh <source_target> --rollback; exit 1; }
          databricks bundle deploy -t <source_target>

      - name: Upload the plan
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: plan-<source_target>
          path: plan-<source_target>.json
          if-no-files-found: ignore
```

> The step runs `scripts/auto-bind.sh`, then `scripts/plan-check.sh --first-deploy`, and deploys only if the check passes. If binding or the check fails, `auto-bind.sh --rollback` unbinds the keys this run bound, so nothing stays half-bound. The check blocks any delete or replacement, any create of a bound key, any other create, and changes to `run_as`, schedules, catalog/schema, storage or notifications of an existing asset, unless approved in `plan-allow/<source_target>.txt` (reviewed in a pull request). The full plan is saved as `plan-<source_target>.json`.

> Do **not** add `bundle deployment bind` to `pr_validate.yml`, `deploy_to_staging.yml`, or `deploy_to_prod.yml`. Binding is one-time; repeating it in recurring pipelines fails on the second run.

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
        run: bash scripts/plan-check.sh staging && databricks bundle deploy -t staging
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
        run: bash scripts/plan-check.sh prod && databricks bundle deploy -t prod
```

## Notes

- Use a GitHub `environment:` for `staging` and `prod` so each environment can hold its own `DATABRICKS_HOST` secret and you can require manual approval on prod.
- Never run `databricks repos` in any of these workflows — bundle deploy handles workspace sync.
- `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` authenticate as a service principal. Store both as repository secrets.
- Every bundle command passes `-t <target>` explicitly. `DATABRICKS_BUNDLE_ENV` is set to the same target as well; keep the two in sync.
- Catalog, schema and other non-secret per-environment values are committed per target in `databricks.yml` (`targets.<target>.variables`). Do not set `BUNDLE_VAR_catalog` or `BUNDLE_VAR_schema` in CI: `BUNDLE_VAR_*` overrides the target values, so one shared value would point every target at the same tables.
