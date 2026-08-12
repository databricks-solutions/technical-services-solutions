# Resource: `database_instances`

Lakebase Postgres database instances (managed Postgres).

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#database_instance

## Complete schema reference

Required fields: `name`

```yaml
resources:
  database_instances:
    <database_instance_name>:
      capacity: <string>  # string | The sku of the instance. Valid values are "CU_1", "CU_2", "CU_4", "CU_8".
      custom_tags:  # array[object] | [Beta] Custom tags associated with the instance. This field is only included on
        -
          key: <string>  # string | [Beta] The key of the custom tag.
          value: <string>  # string | [Beta] The value of the custom tag.
      enable_pg_native_login: <bool>  # bool | Whether to enable PG native password login on the instance. Defaults to false.
      enable_readable_secondaries: <bool>  # bool | Whether to enable secondaries to serve read-only traffic. Defaults to false.
      lifecycle:  # object | Settings that control the deployment lifecycle of the resource, such as preventi
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      name: <string>  # REQUIRED | string | The name of the instance. This is the unique identifier for the instance.
      node_count: <int>  # int | The number of nodes in the instance, composed of 1 primary and 0 or more seconda
      parent_instance_ref:  # object | The ref of the parent instance. This is only available if the instance is
        branch_time: <string>  # string | Branch time of the ref database instance.
        lsn: <string>  # string | User-specified WAL LSN of the ref database instance.
        name: <string>  # string | Name of the ref database instance.
      permissions:  # array[object] | The permissions to apply to this resource.
        -
          group_name: <string>  # string | The name of the group granted the permission level.
          level: CAN_MANAGE  # REQUIRED | enum: CAN_MANAGE, CAN_RESTART, CAN_ATTACH_TO, IS_OWNER, CAN_MANAGE_RUN, CAN_VIEW, ... | The permission level to apply. The allowed levels depend on the resource type.
          service_principal_name: <string>  # string | The name of the service principal granted the permission level.
          user_name: <string>  # string | The name of the user granted the permission level.
      retention_window_in_days: <int>  # int | The retention window for the instance. This is the time window in days
      stopped: <bool>  # bool | Whether to stop the instance. An input only param, see effective_stopped for the
      usage_policy_id: <string>  # string | [Beta] The desired usage policy to associate with the instance.
```

## What to ask the user

- Capacity (compute units)?
- Retention window for PITR?
