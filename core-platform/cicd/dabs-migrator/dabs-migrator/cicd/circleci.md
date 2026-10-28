# CI/CD: CircleCI

`.circleci/config.yml` at repo root.

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
