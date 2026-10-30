# CI/CD: CircleCI

`.circleci/config.yml` at repo root.

## Binding (one-time, source target only)

Before the first recurring deploy to the source workspace, add a temporary `bind-and-deploy-<source_target>` job to `.circleci/config.yml`, gate it behind an `approval` job, run it once, and then remove both jobs.

```yaml
# Add temporarily to .circleci/config.yml — remove after the first successful run.
jobs:
  bind-and-deploy-<source_target>:
    executor: ubuntu
    steps:
      - checkout
      - install-cli
      - run:
          name: Bind migrated resources and deploy to <source_target>
          environment:
            DATABRICKS_HOST: $DATABRICKS_HOST
            DATABRICKS_CLIENT_ID: $DATABRICKS_CLIENT_ID
            DATABRICKS_CLIENT_SECRET: $DATABRICKS_CLIENT_SECRET
            DATABRICKS_BUNDLE_ENV: <source_target>
          command: |
            set -euo pipefail
            grep -v '^#' bindings/<source_target>.yml | while IFS=': ' read -r key bind_id; do
              [ -z "$key" ] && continue
              bind_id=$(printf '%s' "$bind_id" | tr -d '"')
              echo "Binding $key -> $bind_id"
              databricks bundle deployment bind "$key" "$bind_id" -t <source_target> --auto-approve
            done
            PLAN=$(databricks bundle plan -t <source_target> 2>&1)
            printf '%s\n' "$PLAN"
            if printf '%s\n' "$PLAN" | grep -qiE '\b(create|recreate|delete)\b'; then
              echo "ERROR: Plan shows create/recreate/delete for a bound resource."
              echo "The bind may have used the wrong ID, or the YAML config does not match the source asset."
              echo "Review the plan output above, correct bindings/<source_target>.yml if needed, and re-run."
              exit 1
            fi
            echo "Plan check passed — all bound resources will be updated in-place."
            databricks bundle deploy -t <source_target>

# Gate it behind a manual approval in the workflow:
workflows:
  bind-and-deploy-once:
    jobs:
      - hold-bind:
          type: approval
      - bind-and-deploy-<source_target>:
          requires: [hold-bind]
```

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
            databricks bundle deploy -t staging

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
            databricks bundle deploy -t prod

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
