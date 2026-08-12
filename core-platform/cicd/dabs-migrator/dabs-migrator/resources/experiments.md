# Resource: `experiments`

MLflow experiments.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#experiment

## Complete schema reference

Required fields: `name`

```yaml
resources:
  experiments:
    <experiment_name>:
      artifact_location: <string>  # string | Location where all artifacts for the experiment are stored.
      lifecycle:  # object | Settings that control the deployment lifecycle of the resource, such as preventi
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      name: <string>  # REQUIRED | string | Experiment name.
      permissions:  # array[object] | The permissions to apply to this resource.
        -
          group_name: <string>  # string | The name of the group granted the permission level.
          level: CAN_MANAGE  # REQUIRED | enum: CAN_MANAGE, CAN_EDIT, CAN_READ | The permission level to apply. The allowed levels depend on the resource type.
          service_principal_name: <string>  # string | The name of the service principal granted the permission level.
          user_name: <string>  # string | The name of the user granted the permission level.
      tags:  # array[object] | A collection of tags to set on the experiment. Maximum tag size and number of ta
        -
          key: <string>  # string | The tag key.
          value: <string>  # string | The tag value.
```

## What to ask the user

- Workspace path for the experiment?
- Tags / project metadata?
