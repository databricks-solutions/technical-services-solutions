# CI/CD: CircleCI

`.circleci/config.yml` at repo root.

## Required project environment variables

| Variable |
|---|
| `DATABRICKS_HOST` — use context or per-environment variable to set different values for staging and prod |
| `DATABRICKS_CLIENT_ID` |
| `DATABRICKS_CLIENT_SECRET` |
| `catalog` |
| `schema` |

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
            BUNDLE_VAR_catalog: $catalog
            BUNDLE_VAR_schema: $schema
          command: databricks bundle validate --output json | tee bundle-validate.json
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
            BUNDLE_VAR_catalog: $catalog
            BUNDLE_VAR_schema: $schema
          command: |
            databricks bundle validate --output json
            databricks bundle deploy

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
            BUNDLE_VAR_catalog: $catalog
            BUNDLE_VAR_schema: $schema
          command: |
            databricks bundle validate --output json
            databricks bundle deploy

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
- Set `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET`, `catalog`, and `schema` as project environment variables in CircleCI project settings.
- `DATABRICKS_BUNDLE_ENV` is hardcoded per job and tells the CLI which target to use (replaces the `-t` flag).
- `BUNDLE_VAR_catalog` and `BUNDLE_VAR_schema` pass the `catalog` and `schema` variables into bundle variables via the `BUNDLE_VAR_` prefix convention.
