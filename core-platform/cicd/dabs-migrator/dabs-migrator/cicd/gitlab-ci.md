# CI/CD: GitLab CI

Single `.gitlab-ci.yml` at repo root.

## Binding (one-time, staging and prod source targets only)

> **Dev source targets do not use this job.** The first `bundle deploy -t dev` intentionally creates a new isolated dev copy — no bind needed. Only generate and run this job when `source_target` is `staging` or `prod`.

Before the first recurring deploy to a staging or prod source workspace, add a `bind_and_deploy_<source_target>` job to `.gitlab-ci.yml`, trigger it manually once (via the GitLab UI `when: manual` gate), and then remove the job.

```yaml
# Add temporarily to .gitlab-ci.yml — remove after the first successful run.
bind_and_deploy_<source_target>:
  stage: deploy
  environment:
    name: <source_target>
  script:
    - bash scripts/auto-bind.sh <source_target>
    - |
      set -euo pipefail
      PLAN_JSON=$(databricks bundle plan -t <source_target> -o json 2>&1)
      printf '%s\n' "$PLAN_JSON" | jq .
      if echo "$PLAN_JSON" | jq -e '[.plan | to_entries[] | select(.value.action == "recreate" or .value.action == "delete")] | length > 0' &>/dev/null; then
        echo "ERROR: Plan shows recreate/delete — config mismatch or wrong bind ID."; exit 1
      fi
      if [[ -f "bindings/<source_target>.yml" ]]; then
        while IFS= read -r line; do
          [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
          key=$(echo "$line" | cut -d: -f1 | tr -d ' '); [[ -z "$key" ]] && continue
          if echo "$PLAN_JSON" | jq -e --arg k "$key" '[.plan | to_entries[] | select(.key | endswith("." + $k)) | select(.value.action == "create")] | length > 0' &>/dev/null; then
            echo "ERROR: Bound resource '$key' plans as 'create' — bind may have failed."; exit 1
          fi
        done < "bindings/<source_target>.yml"
      fi
      echo "Plan check passed."
    - databricks bundle deploy -t <source_target>
  variables:
    DATABRICKS_HOST: $DATABRICKS_HOST
    DATABRICKS_CLIENT_ID: $DATABRICKS_CLIENT_ID
    DATABRICKS_CLIENT_SECRET: $DATABRICKS_CLIENT_SECRET
    DATABRICKS_BUNDLE_ENV: <source_target>
  rules:
    - when: manual
```

> Do **not** add `bundle deployment bind` to `validate`, `deploy_staging`, or `deploy_prod`. Binding is one-time; repeating it in recurring jobs fails on the second run.

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
