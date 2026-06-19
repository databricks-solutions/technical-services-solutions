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
          key: <string>  # string | The key of the custom tag.
          value: <string>  # string | The value of the custom tag.
      default_branch: <string>  # string
      default_endpoint_settings:  # object
        autoscaling_limit_max_cu: <float>  # float | The maximum number of Compute Units. Minimum value is 0.5.
        autoscaling_limit_min_cu: <float>  # float | The minimum number of Compute Units. Minimum value is 0.5.
        no_suspension: <bool>  # bool | When set to true, explicitly disables automatic suspension (never suspend).
        pg_settings:  # map[string, string] | A raw representation of Postgres settings.
          <key>: <value>
        suspend_timeout_duration: <string>  # string | Duration of inactivity after which the compute endpoint is automatically suspend
      display_name: <string>  # string
      enable_pg_native_login: <bool>  # bool
      history_retention_duration: <string>  # string
      lifecycle:  # object
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      permissions:  # array[object]
        -
          group_name: <string>  # string | The name of the group that has the permission set in level.
          level: CAN_MANAGE  # REQUIRED | enum: CAN_MANAGE, CAN_RESTART, CAN_ATTACH_TO, IS_OWNER, CAN_MANAGE_RUN, CAN_VIEW, ... | The allowed permission for user, group, service principal defined for this permi
          service_principal_name: <string>  # string | The name of the service principal that has the permission set in level.
          user_name: <string>  # string | The name of the user that has the permission set in level.
      pg_version: <int>  # int
      project_id: <string>  # REQUIRED | string
```

## What to ask the user

- Postgres major version?
- Region?
