# CI/CD: CircleCI

`.circleci/config.yml` at repo root.

## Binding (one-time, staging and prod source targets only)

> **Dev source targets do not use this job.** The first `bundle deploy -t dev` intentionally creates a new isolated dev copy — no bind needed. Only generate and run this job when `source_target` is `staging` or `prod`.

Before the first recurring deploy to a staging or prod source workspace, add a temporary `bind-and-deploy-<source_target>` job to `.circleci/config.yml`, gate it behind an `approval` job, run it once, and then remove both jobs.

```yaml
# Add temporarily to .circleci/config.yml. Remove both jobs after the first successful run.
# DATABRICKS_HOST, DATABRICKS_CLIENT_ID and DATABRICKS_CLIENT_SECRET come from project environment
# variables or a context. Do not re-map them under `environment:` (CircleCI does not expand $VAR there).
jobs:
  bind-and-deploy-<source_target>:
    executor: ubuntu
    steps:
      - checkout
      - install-cli
      - run:
          name: Bind, check the plan, deploy (unbind again if anything fails)
          environment:
            DATABRICKS_BUNDLE_ENV: <source_target>
          command: |
            set -euo pipefail
            bash scripts/auto-bind.sh <source_target> || { bash scripts/auto-bind.sh <source_target> --rollback; exit 1; }
            bash scripts/plan-check.sh <source_target> --first-deploy || { bash scripts/auto-bind.sh <source_target> --rollback; exit 1; }
            databricks bundle deploy -t <source_target>
      - store_artifacts:
          path: plan-<source_target>.json

workflows:
  bind-and-deploy-once:
    jobs:
      - hold-bind:
          type: approval
          filters:
            branches:
              only: main
      - bind-and-deploy-<source_target>:
          requires: [hold-bind]
          # context: databricks-<source_target>   # if the credentials live in a context
          filters:
            branches:
              only: main
```

> The step runs `scripts/auto-bind.sh`, then `scripts/plan-check.sh --first-deploy`, and deploys only if the check passes. If binding or the check fails, `auto-bind.sh --rollback` unbinds the keys this run bound, so nothing stays half-bound. The check blocks any delete or replacement, any create of a bound key, any other create, and changes to `run_as`, schedules, catalog/schema, storage or notifications of an existing asset, unless approved in `plan-allow/<source_target>.txt` (reviewed in a pull request). The full plan is saved as `plan-<source_target>.json`.

> Do **not** add `bundle deployment bind` to the `validate`, `deploy-staging`, or `deploy-prod` jobs. Binding is one-time; repeating it in recurring jobs fails on the second run.

## Required project environment variables

| Variable |
|---|
| `DATABRICKS_HOST` — use context or per-environment variable to set different values for staging and prod |
| `DATABRICKS_CLIENT_ID` |
| `DATABRICKS_CLIENT_SECRET` |

## `.circleci/config.yml`

```yaml
version: 2.1

executors:
  ubuntu:
    docker:
      - image: cimg/base:current

commands:
  install-cli:
    steps:
      - run:
          name: Install Databricks CLI
          command: curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sudo sh

jobs:
  validate:
    executor: ubuntu
    steps:
      - checkout
      - install-cli
      - run:
          name: Validate bundle
          environment:
            DATABRICKS_HOST: $DATABRICKS_HOST
            DATABRICKS_CLIENT_ID: $DATABRICKS_CLIENT_ID
            DATABRICKS_CLIENT_SECRET: $DATABRICKS_CLIENT_SECRET
            DATABRICKS_BUNDLE_ENV: staging
          command: databricks bundle validate -t staging --output json | tee bundle-validate.json
      - store_artifacts:
          path: bundle-validate.json

  deploy-staging:
    executor: ubuntu
    steps:
      - checkout
      - install-cli
      - run:
          environment:
            DATABRICKS_HOST: $DATABRICKS_HOST
            DATABRICKS_CLIENT_ID: $DATABRICKS_CLIENT_ID
            DATABRICKS_CLIENT_SECRET: $DATABRICKS_CLIENT_SECRET
            DATABRICKS_BUNDLE_ENV: staging
          command: |
            databricks bundle validate -t staging --output json
            bash scripts/plan-check.sh staging && databricks bundle deploy -t staging

  deploy-prod:
    executor: ubuntu
    steps:
      - checkout
      - install-cli
      - run:
          environment:
            DATABRICKS_HOST: $DATABRICKS_HOST
            DATABRICKS_CLIENT_ID: $DATABRICKS_CLIENT_ID
            DATABRICKS_CLIENT_SECRET: $DATABRICKS_CLIENT_SECRET
            DATABRICKS_BUNDLE_ENV: prod
          command: |
            databricks bundle validate -t prod --output json
            bash scripts/plan-check.sh prod && databricks bundle deploy -t prod

workflows:
  validate-and-deploy:
    jobs:
      - validate
      - deploy-staging:
          requires: [validate]
          filters:
            branches:
              only: main
      - hold-prod:
          type: approval
          filters:
            tags:
              only: /^v.*/
            branches:
              ignore: /.*/
      - deploy-prod:
          requires: [hold-prod]
          filters:
            tags:
              only: /^v.*/
            branches:
              ignore: /.*/
```

## Notes

- `type: approval` on `hold-prod` is the manual gate.
- CircleCI requires explicit tag filters on every job in a tag-triggered workflow — copy the `filters:` block.
- Set `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` as project environment variables in CircleCI project settings.
- Every bundle command passes `-t <target>` explicitly. `DATABRICKS_BUNDLE_ENV` is set to the same target as well; keep the two in sync.
- Catalog, schema and other non-secret per-environment values are committed per target in `databricks.yml` (`targets.<target>.variables`). Do not set `BUNDLE_VAR_catalog` or `BUNDLE_VAR_schema` in CI: `BUNDLE_VAR_*` overrides the target values, so one shared value would point every target at the same tables.
