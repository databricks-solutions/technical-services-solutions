# CI/CD: Jenkins

Declarative `Jenkinsfile` at repo root. Assumes Jenkins agents have `curl` and `bash`.

## Required Jenkins credentials

| ID | Type |
|---|---|
| `databricks-host` | Secret text — configure separate credential IDs per environment if needed |
| `databricks-client-id` | Secret text |
| `databricks-client-secret` | Secret text |
| `catalog` | Secret text |
| `schema` | Secret text |

## `Jenkinsfile`

```groovy
pipeline {
  agent any

  environment {
    DATABRICKS_CLIENT_ID     = credentials('databricks-client-id')
    DATABRICKS_CLIENT_SECRET = credentials('databricks-client-secret')
    BUNDLE_VAR_catalog       = credentials('catalog')
    BUNDLE_VAR_schema        = credentials('schema')
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
        sh 'databricks bundle validate --output json | tee bundle-validate.json'
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
        sh 'databricks bundle deploy'
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
        sh 'databricks bundle validate --output json'
        sh 'databricks bundle deploy'
      }
    }
  }
}
```

## Notes

- The `input` block on the prod stage gates deployment behind a manual approval.
- Run on a tag build (`buildingTag()`) — configure your multibranch/MultiPipeline to discover tags.
- Store `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET`, `catalog`, and `schema` as separate **Secret text** credentials in Jenkins Credentials Manager.
- `DATABRICKS_BUNDLE_ENV` is hardcoded per stage and tells the CLI which target to use (replaces the `-t` flag).
- `BUNDLE_VAR_catalog` and `BUNDLE_VAR_schema` pass the `catalog` and `schema` credentials into bundle variables via the `BUNDLE_VAR_` prefix convention.
