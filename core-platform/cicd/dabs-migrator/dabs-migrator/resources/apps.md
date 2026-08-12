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
      compute_max_instances: <int>  # PRIVATE PREVIEW | int | Maximum number of app instances. Must be set together with `compute_min_instance
      compute_min_instances: <int>  # PRIVATE PREVIEW | int | Minimum number of app instances. Must be set together with `compute_max_instance
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
      git_repository:  # object | Git repository configuration for app deployments. When specified, deployments ca
        provider: <string>  # REQUIRED | string | Git provider. Case insensitive. Supported values: gitHub, gitHubEnterprise, bitb
        url: <string>  # REQUIRED | string | URL of the Git repository.
      git_source:  # object | Git source configuration for app deployments. Specifies which git reference (bra
        branch: <string>  # string | Git branch to checkout.
        commit: <string>  # string | Git commit SHA to checkout.
        source_code_path: <string>  # string | Relative path to the app source code within the Git repository. If not specified
        tag: <string>  # string | Git tag to checkout.
      lifecycle:  # object | Settings that control the deployment lifecycle of the resource, such as preventi
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
        started: <bool>  # bool | Lifecycle setting to deploy the resource in started mode. Only supported for app
      name: <string>  # REQUIRED | string | The name of the app. The name must contain only lowercase alphanumeric character
      permissions:  # array[object] | The permissions to apply to this resource.
        -
          group_name: <string>  # string | The name of the group granted the permission level.
          level: CAN_MANAGE  # REQUIRED | enum: CAN_MANAGE, CAN_USE | The permission level to apply. The allowed levels depend on the resource type.
          service_principal_name: <string>  # string | The name of the service principal granted the permission level.
          user_name: <string>  # string | The name of the user granted the permission level.
      resources:  # array[object] | Resources for the app.
        -
          app:  # object
            name: <string>  # string
            permission: CAN_USE  # enum: CAN_USE
          database:  # object
            database_name: <string>  # REQUIRED | string
            instance_name: <string>  # REQUIRED | string
            permission: CAN_CONNECT_AND_CREATE  # REQUIRED | enum: CAN_CONNECT_AND_CREATE
          description: <string>  # string | Description of the App Resource.
          experiment:  # object
            experiment_id: <string>  # REQUIRED | string
            permission: CAN_MANAGE  # REQUIRED | enum: CAN_MANAGE, CAN_EDIT, CAN_READ
          genie_space:  # object
            name: <string>  # REQUIRED | string
            permission: CAN_MANAGE  # REQUIRED | enum: CAN_MANAGE, CAN_EDIT, CAN_RUN, CAN_VIEW
            space_id: <string>  # REQUIRED | string
          job:  # object
            id: <string>  # REQUIRED | string | Id of the job to grant permission on.
            permission: CAN_MANAGE  # REQUIRED | enum: CAN_MANAGE, IS_OWNER, CAN_MANAGE_RUN, CAN_VIEW | Permissions to grant on the Job. Supported permissions are: "CAN_MANAGE", "IS_OW
          name: <string>  # REQUIRED | string | Name of the App Resource.
          postgres:  # object
            branch: <string>  # string
            database: <string>  # string
            permission: CAN_CONNECT_AND_CREATE  # enum: CAN_CONNECT_AND_CREATE
          secret:  # object
            key: <string>  # REQUIRED | string | Key of the secret to grant permission on.
            permission: READ  # REQUIRED | enum: READ, WRITE, MANAGE | Permission to grant on the secret scope. For secrets, only one permission is all
            scope: <string>  # REQUIRED | string | Scope of the secret to grant permission on.
          serving_endpoint:  # object
            name: <string>  # REQUIRED | string | Name of the serving endpoint to grant permission on.
            permission: CAN_MANAGE  # REQUIRED | enum: CAN_MANAGE, CAN_QUERY, CAN_VIEW | Permission to grant on the serving endpoint. Supported permissions are: "CAN_MAN
          sql_warehouse:  # object
            id: <string>  # REQUIRED | string | Id of the SQL warehouse to grant permission on.
            permission: CAN_MANAGE  # REQUIRED | enum: CAN_MANAGE, CAN_USE, IS_OWNER | Permission to grant on the SQL warehouse. Supported permissions are: "CAN_MANAGE
          uc_securable:  # object
            permission: READ_VOLUME  # REQUIRED | enum: READ_VOLUME, WRITE_VOLUME, SELECT, EXECUTE, USE_CONNECTION, MODIFY
            securable_full_name: <string>  # REQUIRED | string
            securable_type: VOLUME  # REQUIRED | enum: VOLUME, TABLE, FUNCTION, CONNECTION
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
