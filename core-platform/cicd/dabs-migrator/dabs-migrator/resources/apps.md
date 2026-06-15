# Resource: `apps`

Databricks Apps (Streamlit, Dash, Flask, Gradio, etc.).

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#app

## Source code

**If migrating an existing app:** clone the entire app source tree (entrypoint, modules, `app.yaml`, `requirements.txt`, static assets) verbatim into `src/{{ app_name }}/`. Preserve directory structure and filenames. Do not replace any module with stub code or `# TODO` placeholders.

**Stubs (only when starting from scratch):**

- `app.yaml` — app config (command, env vars).
- `app.py` — entrypoint.
- `requirements.txt` — app-specific Python deps.

## Complete schema reference

Required fields: `name`

```yaml
resources:
  apps:
    <app_name>:
      budget_policy_id: <string>  # string
      compute_size: MEDIUM  # enum: MEDIUM, LARGE
      config:  # object
        command:  # array[string]
          - <value>
        env:  # array[object]
          -
            name: <string>  # REQUIRED | string
            value: <string>  # string
            value_from: <string>  # string
      description: <string>  # string | The description of the app.
      git_repository:  # PRIVATE PREVIEW | object | Git repository configuration for app deployments. When specified, deployments ca
        provider: <string>  # REQUIRED | string | Git provider. Case insensitive. Supported values: gitHub, gitHubEnterprise, bitb
        url: <string>  # REQUIRED | string | URL of the Git repository.
      git_source:  # object | Git source configuration for app deployments. Specifies which git reference (bra
        branch: <string>  # string | Git branch to checkout.
        commit: <string>  # string | Git commit SHA to checkout.
        source_code_path: <string>  # string | Relative path to the app source code within the Git repository. If not specified
        tag: <string>  # string | Git tag to checkout.
      lifecycle:  # object | Lifecycle is a struct that contains the lifecycle settings for a resource. It co
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
        started: <bool>  # bool | Lifecycle setting to deploy the resource in started mode. Only supported for app
      name: <string>  # REQUIRED | string | The name of the app. The name must contain only lowercase alphanumeric character
      permissions:  # array[object]
        -
          group_name: <string>  # string
          level: CAN_MANAGE  # REQUIRED | enum: CAN_MANAGE, CAN_USE
          service_principal_name: <string>  # string
          user_name: <string>  # string
      resources:  # array[object] | Resources for the app.
        -
          app:  # object
            name: <string>  # string
            permission: <...(nested)>  # ...(nested)
          database:  # object
            database_name: <string>  # REQUIRED | string
            instance_name: <string>  # REQUIRED | string
            permission: <...(nested)>  # REQUIRED | ...(nested)
          description: <string>  # string | Description of the App Resource.
          experiment:  # object
            experiment_id: <string>  # REQUIRED | string
            permission: <...(nested)>  # REQUIRED | ...(nested)
          genie_space:  # object
            name: <string>  # REQUIRED | string
            permission: <...(nested)>  # REQUIRED | ...(nested)
            space_id: <string>  # REQUIRED | string
          job:  # object
            id: <string>  # REQUIRED | string
            permission: <...(nested)>  # REQUIRED | ...(nested)
          name: <string>  # REQUIRED | string | Name of the App Resource.
          postgres:  # object
            branch: <string>  # string
            database: <string>  # string
            permission: <...(nested)>  # ...(nested)
          secret:  # object
            key: <string>  # REQUIRED | string
            permission: <...(nested)>  # REQUIRED | ...(nested)
            scope: <string>  # REQUIRED | string
          serving_endpoint:  # object
            name: <string>  # REQUIRED | string
            permission: <...(nested)>  # REQUIRED | ...(nested)
          sql_warehouse:  # object
            id: <string>  # REQUIRED | string
            permission: <...(nested)>  # REQUIRED | ...(nested)
          uc_securable:  # object
            permission: <...(nested)>  # REQUIRED | ...(nested)
            securable_full_name: <string>  # REQUIRED | string
            securable_type: <...(nested)>  # REQUIRED | ...(nested)
      source_code_path: <string>  # string
      space: <string>  # PRIVATE PREVIEW | string | Name of the space this app belongs to.
      telemetry_export_destinations:  # array[object]
        -
          unity_catalog:  # object | Unity Catalog Destinations for OTEL telemetry export.
            logs_table: <string>  # REQUIRED | string | Unity Catalog table for OTEL logs.
            metrics_table: <string>  # REQUIRED | string | Unity Catalog table for OTEL metrics.
            traces_table: <string>  # REQUIRED | string | Unity Catalog table for OTEL traces (spans).
      usage_policy_id: <string>  # string
      user_api_scopes:  # array[string]
        - <value>
```

## What to ask the user

- Framework (Streamlit, Dash, Flask, Gradio)?
- Which workspace resources does the app need (warehouses, secrets, serving endpoints)?
