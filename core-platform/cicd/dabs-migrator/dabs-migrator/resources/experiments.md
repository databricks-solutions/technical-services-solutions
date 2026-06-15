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
      lifecycle:  # object | Lifecycle is a struct that contains the lifecycle settings for a resource. It co
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      name: <string>  # REQUIRED | string | Experiment name.
      permissions:  # array[object]
        -
          group_name: <string>  # string
          level: CAN_MANAGE  # REQUIRED | enum: CAN_MANAGE, CAN_EDIT, CAN_READ
          service_principal_name: <string>  # string
          user_name: <string>  # string
      tags:  # array[object] | A collection of tags to set on the experiment. Maximum tag size and number of ta
        -
          key: <string>  # string | The tag key.
          value: <string>  # string | The tag value.
```

## What to ask the user

- Workspace path for the experiment?
- Tags / project metadata?
