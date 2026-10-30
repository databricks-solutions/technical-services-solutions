# CI/CD: Jenkins

Declarative `Jenkinsfile` at repo root. Assumes Jenkins agents have `curl` and `bash`.

## Binding (one-time, source target only)

Before the first recurring deploy to the source workspace, add a temporary `Bind and deploy` stage to the `Jenkinsfile`, run it once (the `input` block requires a manual click), and then remove the stage.

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
      grep -v '^#' bindings/<source_target>.yml | while IFS=': ' read -r key bind_id; do
        [ -z "$key" ] && continue
        bind_id=$(printf '%s' "$bind_id" | tr -d '"')
        echo "Binding $key -> $bind_id"
        databricks bundle deployment bind "$key" "$bind_id" -t <source_target> --auto-approve
      done
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
