# Resource: `sql_warehouses`

SQL warehouses (compute endpoints for SQL).

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#sql_warehouse

## Complete schema reference

```yaml
resources:
  sql_warehouses:
    <warehouse_name>:
      auto_stop_mins: <int>  # int | The amount of time in minutes that a SQL warehouse must be idle (i.e., no
      channel:  # object | Channel Details
        dbsql_version: <string>  # string
        name: CHANNEL_NAME_PREVIEW  # enum: CHANNEL_NAME_PREVIEW, CHANNEL_NAME_CURRENT, CHANNEL_NAME_PREVIOUS, CHANNEL_NAME_CUSTOM
      cluster_size: <string>  # string | Size of the clusters allocated for this warehouse.
      creator_name: <string>  # string | warehouse creator name
      enable_photon: <bool>  # bool | Configures whether the warehouse should use Photon optimized clusters.
      enable_serverless_compute: <bool>  # bool | Configures whether the warehouse should use serverless compute
      instance_profile_arn: <string>  # DEPRECATED | string | Deprecated. Instance profile used to pass IAM role to the cluster
      lifecycle:  # object | Settings that control the deployment lifecycle of the resource, such as preventi
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
        started: <bool>  # bool | Lifecycle setting to deploy the resource in started mode. Only supported for app
      max_num_clusters: <int>  # int | Maximum number of clusters that the autoscaler will create to handle
      min_num_clusters: <int>  # int | Minimum number of available clusters that will be maintained for this SQL
      name: <string>  # string | Logical name for the cluster.
      permissions:  # array[object] | The permissions to apply to this resource.
        -
          group_name: <string>  # string | The name of the group granted the permission level.
          level: CAN_MANAGE  # REQUIRED | enum: CAN_MANAGE, IS_OWNER, CAN_USE, CAN_MONITOR, CAN_VIEW | The permission level to apply. The allowed levels depend on the resource type.
          service_principal_name: <string>  # string | The name of the service principal granted the permission level.
          user_name: <string>  # string | The name of the user granted the permission level.
      spot_instance_policy: POLICY_UNSPECIFIED  # enum: POLICY_UNSPECIFIED, COST_OPTIMIZED, RELIABILITY_OPTIMIZED | Configurations whether the endpoint should use spot instances.
      tags:  # object | A set of key-value pairs that will be tagged on all resources (e.g., AWS instanc
        custom_tags:  # array[object]
          -
            key: <string>  # string
            value: <string>  # string
      warehouse_type: TYPE_UNSPECIFIED  # enum: TYPE_UNSPECIFIED, CLASSIC, PRO | Warehouse type: `PRO` or `CLASSIC`. If you want to use serverless compute,
```

## What to ask the user

- Serverless, Pro, or Classic?
- T-shirt size (XS, S, M, L, XL, ...) and autoscale bounds?
- Auto-stop minutes?
