# CI/CD: Jenkins

Declarative `Jenkinsfile` at repo root. Assumes Jenkins agents have `curl` and `bash`.

## Binding (one-time, staging and prod source targets only)

> **Dev source targets do not use this stage.** The first `bundle deploy -t dev` intentionally creates a new isolated dev copy — no bind needed. Only generate and run this stage when `source_target` is `staging` or `prod`.

Before the first recurring deploy to a staging or prod source workspace, add a temporary `Bind and deploy` stage to the `Jenkinsfile`, run it once (the `input` block requires a manual click), and then remove the stage.

```groovy
// Add temporarily to Jenkinsfile. Remove after the first successful run.
// The sh step starts with #!/bin/bash so it runs in bash, not /bin/sh (dash on many agents).
// The agent needs jq installed.
stage('Bind and deploy (one-time, <source_target>)') {
  when { branch 'main' }
  environment {
    DATABRICKS_HOST       = credentials('databricks-host')
    DATABRICKS_BUNDLE_ENV = '<source_target>'
  }
  input {
    message 'Bind migrated resources and deploy to <source_target>?'
    ok 'Bind and deploy'
  }
  steps {
    sh '''#!/bin/bash
      set -euo pipefail
      bash scripts/auto-bind.sh <source_target> || { bash scripts/auto-bind.sh <source_target> --rollback; exit 1; }
      bash scripts/plan-check.sh <source_target> --first-deploy || { bash scripts/auto-bind.sh <source_target> --rollback; exit 1; }
      databricks bundle deploy -t <source_target>
    '''
  }
  post {
    always {
      archiveArtifacts artifacts: 'plan-<source_target>.json', allowEmptyArchive: true
    }
  }
}
```

> The step runs `scripts/auto-bind.sh`, then `scripts/plan-check.sh --first-deploy`, and deploys only if the check passes. If binding or the check fails, `auto-bind.sh --rollback` unbinds the keys this run bound, so nothing stays half-bound. The check blocks any delete or replacement, any create of a bound key, any other create, and changes to `run_as`, schedules, catalog/schema, storage or notifications of an existing asset, unless approved in `plan-allow/<source_target>.txt` (reviewed in a pull request). The full plan is saved as `plan-<source_target>.json`.

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
        sh 'bash scripts/plan-check.sh staging && databricks bundle deploy -t staging'
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
        sh 'bash scripts/plan-check.sh prod && databricks bundle deploy -t prod'
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
