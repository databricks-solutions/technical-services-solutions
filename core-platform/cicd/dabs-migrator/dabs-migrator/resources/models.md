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
      lifecycle:  # object | Lifecycle is a struct that contains the lifecycle settings for a resource. It co
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      name: <string>  # REQUIRED | string | Register models under this name
      permissions:  # array[object]
        -
          group_name: <string>  # string
          level: CAN_MANAGE  # REQUIRED | enum: CAN_MANAGE, CAN_MANAGE_PRODUCTION_VERSIONS, CAN_MANAGE_STAGING_VERSIONS, CAN_EDIT, CAN_READ
          service_principal_name: <string>  # string
          user_name: <string>  # string
      tags:  # array[object] | Additional metadata for registered model.
        -
          key: <string>  # string | The tag key.
          value: <string>  # string | The tag value.
```

## What to ask the user

- Is this UC-enabled? If yes, use `registered_models` instead.
