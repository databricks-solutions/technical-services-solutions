# CI/CD: GitLab CI

Single `.gitlab-ci.yml` at repo root.

## Required CI/CD variables

| Variable | Scope | Masked |
|---|---|---|
| `DATABRICKS_HOST` | per environment (staging/prod) | yes |
| `DATABRICKS_CLIENT_ID` | both, protected | yes |
| `DATABRICKS_CLIENT_SECRET` | both, protected | yes |

## `.gitlab-ci.yml`

```yaml
stages: [validate, deploy]

default:
  image: ubuntu:24.04
  before_script:
    - apt-get update && apt-get install -y curl ca-certificates
    - curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh

validate:
  stage: validate
  script:
    - databricks bundle validate -t staging --output json | tee bundle-validate.json
  artifacts:
    paths: [bundle-validate.json]
  variables:
    DATABRICKS_HOST: $DATABRICKS_HOST
    DATABRICKS_CLIENT_ID: $DATABRICKS_CLIENT_ID
    DATABRICKS_CLIENT_SECRET: $DATABRICKS_CLIENT_SECRET
    DATABRICKS_BUNDLE_ENV: staging
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

deploy_staging:
  stage: deploy
  environment:
    name: staging
  script:
    - databricks bundle validate -t staging --output json
    - databricks bundle deploy -t staging
  variables:
    DATABRICKS_HOST: $DATABRICKS_HOST
    DATABRICKS_CLIENT_ID: $DATABRICKS_CLIENT_ID
    DATABRICKS_CLIENT_SECRET: $DATABRICKS_CLIENT_SECRET
    DATABRICKS_BUNDLE_ENV: staging
  rules:
    - if: $CI_COMMIT_BRANCH == "main"

deploy_prod:
  stage: deploy
  environment:
    name: prod
    action: prepare
  script:
    - databricks bundle validate -t prod --output json
    - databricks bundle deploy -t prod
  variables:
    DATABRICKS_HOST: $DATABRICKS_HOST
    DATABRICKS_CLIENT_ID: $DATABRICKS_CLIENT_ID
    DATABRICKS_CLIENT_SECRET: $DATABRICKS_CLIENT_SECRET
    DATABRICKS_BUNDLE_ENV: prod
  rules:
    - if: $CI_COMMIT_TAG =~ /^v/
      when: manual
```

## Notes

- `when: manual` on `deploy_prod` enforces a click-to-approve gate.
- Mark `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` as **Protected** so they are only injected on protected branches/tags.
- Scope `DATABRICKS_HOST` to each GitLab environment so staging and prod use different workspace URLs.
- Every bundle command passes `-t <target>` explicitly. `DATABRICKS_BUNDLE_ENV` is set to the same target as well; keep the two in sync.
- Catalog, schema and other non-secret per-environment values are committed per target in `databricks.yml` (`targets.<target>.variables`). Do not set `BUNDLE_VAR_catalog` or `BUNDLE_VAR_schema` in CI: `BUNDLE_VAR_*` overrides the target values, so one shared value would point every target at the same tables.
