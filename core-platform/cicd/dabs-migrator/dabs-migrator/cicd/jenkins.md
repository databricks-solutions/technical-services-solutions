# CI/CD: Jenkins

Declarative `Jenkinsfile` at repo root. Assumes Jenkins agents have `curl` and `bash`.

## Binding (one-time, staging and prod source targets only)

> **Dev source targets do not use this stage.** The first `bundle deploy -t dev` intentionally creates a new isolated dev copy — no bind needed. Only generate and run this stage when `source_target` is `staging` or `prod`.

Before the first recurring deploy to a staging or prod source workspace, add a temporary `Bind and deploy` stage to the `Jenkinsfile`, run it once (the `input` block requires a manual click), and then remove the stage.

```groovy
// Add temporarily to Jenkinsfile — remove after the first successful run.
stage('Bind and deploy (one-time, <source_target>)') {
  environment {
    DATABRICKS_HOST       = credentials('databricks-host')
    DATABRICKS_BUNDLE_ENV = '<source_target>'
  }
  input {
    message 'Bind migrated resources and deploy to <source_target>?'
    ok 'Bind and deploy'
  }
  steps {
    sh '''
      set -euo pipefail
      bash scripts/auto-bind.sh <source_target>
      PLAN_JSON=$(databricks bundle plan -t <source_target> -o json 2>&1)
      printf '%s\n' "$PLAN_JSON" | jq .
      if echo "$PLAN_JSON" | jq -e '[.plan | to_entries[] | select(.value.action == "recreate" or .value.action == "delete")] | length > 0' &>/dev/null; then
        echo "ERROR: Plan shows recreate/delete — config mismatch or wrong bind ID."; exit 1
      fi
      if [[ -f "bindings/<source_target>.yml" ]]; then
        while IFS= read -r line; do
          [[ "$line" =~ ^#.*$ || -z "\\$line" ]] && continue
          key=$(echo "$line" | cut -d: -f1 | tr -d ' '); [[ -z "$key" ]] && continue
          if echo "$PLAN_JSON" | jq -e --arg k "$key" '[.plan | to_entries[] | select(.key | endswith("." + $k)) | select(.value.action == "create")] | length > 0' &>/dev/null; then
            echo "ERROR: Bound resource '$key' plans as 'create' — bind may have failed."; exit 1
          fi
        done < "bindings/<source_target>.yml"
      fi
      echo "Plan check passed."
      databricks bundle deploy -t <source_target>
    '''
  }
}
```

> Do **not** add `bundle deployment bind` to the `Validate`, `Deploy staging`, or `Deploy prod` stages. Binding is one-time; repeating it in recurring stages fails on the second run.

## Required Jenkins credentials

| ID | Type |
|---|---|
| `databricks-host` | Secret text — configure separate credential IDs per environment if needed |
| `databricks-client-id` | Secret text |
| `databricks-client-secret` | Secret text |

## `Jenkinsfile`

```groovy
pipeline {
  agent any

  environment {
    DATABRICKS_CLIENT_ID     = credentials('databricks-client-id')
    DATABRICKS_CLIENT_SECRET = credentials('databricks-client-secret')
  }

  stages {
    stage('Install Databricks CLI') {
      steps {
        sh 'curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh'
      }
    }

    stage('Validate') {
      environment {
        DATABRICKS_HOST       = credentials('databricks-host')
        DATABRICKS_BUNDLE_ENV = 'staging'
      }
      steps {
        sh 'databricks bundle validate -t staging --output json | tee bundle-validate.json'
        archiveArtifacts artifacts: 'bundle-validate.json', fingerprint: true
      }
    }

    stage('Deploy staging') {
      when { branch 'main' }
      environment {
        DATABRICKS_HOST       = credentials('databricks-host')
        DATABRICKS_BUNDLE_ENV = 'staging'
      }
      steps {
        sh 'databricks bundle deploy -t staging'
      }
    }

    stage('Deploy prod') {
      when { buildingTag() }
      environment {
        DATABRICKS_HOST       = credentials('databricks-host')
        DATABRICKS_BUNDLE_ENV = 'prod'
      }
      input {
        message 'Deploy to prod?'
        ok 'Deploy'
      }
      steps {
        sh 'databricks bundle validate -t prod --output json'
        sh 'databricks bundle deploy -t prod'
      }
    }
  }
}
```

## Notes

- The `input` block on the prod stage gates deployment behind a manual approval.
- Run on a tag build (`buildingTag()`) — configure your multibranch/MultiPipeline to discover tags.
- Store `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` as separate **Secret text** credentials in Jenkins Credentials Manager.
- Every bundle command passes `-t <target>` explicitly. `DATABRICKS_BUNDLE_ENV` is set to the same target as well; keep the two in sync.
- Catalog, schema and other non-secret per-environment values are committed per target in `databricks.yml` (`targets.<target>.variables`). Do not set `BUNDLE_VAR_catalog` or `BUNDLE_VAR_schema` in CI: `BUNDLE_VAR_*` overrides the target values, so one shared value would point every target at the same tables.
