# Resource: `models`

**Legacy** workspace model registry. Prefer `registered_models` (Unity Catalog) for new work — only use `models` if the workspace is not Unity Catalog enabled.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#model

## Complete schema reference

Required fields: `name`

```yaml
resources:
  models:
    <model_name>:
      description: <string>  # string | Optional description for registered model.
      lifecycle:  # object | Settings that control the deployment lifecycle of the resource, such as preventi
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      name: <string>  # REQUIRED | string | Register models under this name
      permissions:  # array[object] | The permissions to apply to this resource.
        -
          group_name: <string>  # string | The name of the group granted the permission level.
          level: CAN_MANAGE  # REQUIRED | enum: CAN_MANAGE, CAN_MANAGE_PRODUCTION_VERSIONS, CAN_MANAGE_STAGING_VERSIONS, CAN_EDIT, CAN_READ | The permission level to apply. The allowed levels depend on the resource type.
          service_principal_name: <string>  # string | The name of the service principal granted the permission level.
          user_name: <string>  # string | The name of the user granted the permission level.
      tags:  # array[object] | Additional metadata for registered model.
        -
          key: <string>  # string | The tag key.
          value: <string>  # string | The tag value.
```

## What to ask the user

- Is this UC-enabled? If yes, use `registered_models` instead.
