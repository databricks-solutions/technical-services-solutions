# Resource: `postgres_projects`

Lakebase Autoscaling project — top-level container.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#postgres_project

## Complete schema reference

Required fields: `project_id`

```yaml
resources:
  postgres_projects:
    <postgres_project_name>:
      budget_policy_id: <string>  # string
      custom_tags:  # array[object]
        -
          key: <string>  # string | [Beta] The key of the custom tag.
          value: <string>  # string | [Beta] The value of the custom tag.
      default_branch: <string>  # string
      default_endpoint_settings:  # object | A collection of settings for a compute endpoint.
        autoscaling_limit_max_cu: <float>  # float | [Beta] The maximum number of Compute Units. Minimum value is 0.5.
        autoscaling_limit_min_cu: <float>  # float | [Beta] The minimum number of Compute Units. Minimum value is 0.5.
        no_suspension: <bool>  # bool | [Beta] When set to true, explicitly disables automatic suspension (never suspend
        pg_settings:  # map[string, string] | [Beta] A raw representation of Postgres settings.
          <key>: <value>
        suspend_timeout_duration: <string>  # string | [Beta] Duration of inactivity after which the compute endpoint is automatically
      display_name: <string>  # string
      enable_pg_native_login: <bool>  # bool
      history_retention_duration: <string>  # string
      lifecycle:  # object | Settings that control the deployment lifecycle of the resource, such as preventi
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      permissions:  # array[object] | The permissions to apply to this resource.
        -
          group_name: <string>  # string | The name of the group granted the permission level.
          level: CAN_MANAGE  # REQUIRED | enum: CAN_MANAGE, CAN_RESTART, CAN_ATTACH_TO, IS_OWNER, CAN_MANAGE_RUN, CAN_VIEW, ... | The permission level to apply. The allowed levels depend on the resource type.
          service_principal_name: <string>  # string | The name of the service principal granted the permission level.
          user_name: <string>  # string | The name of the user granted the permission level.
      pg_version: <int>  # int
      project_id: <string>  # REQUIRED | string
      purge_on_delete: <bool>  # bool
```

## What to ask the user

- Postgres major version?
- Region?
