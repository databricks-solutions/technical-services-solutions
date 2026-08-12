# Resource: `vector_search_endpoints`

Vector Search endpoint — compute that serves one or more vector search indexes. One YAML per endpoint under `resources/vector_search_endpoints/<name>.yml`.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#vector_search_endpoint

## Complete schema reference

Required fields: `endpoint_type`, `name`

```yaml
resources:
  vector_search_endpoints:
    <vector_search_endpoint_name>:
      budget_policy_id: <string>  # string | The budget policy id to be applied
      endpoint_type: STORAGE_OPTIMIZED  # REQUIRED | enum: STORAGE_OPTIMIZED, STANDARD | Type of endpoint
      lifecycle:  # object | Settings that control the deployment lifecycle of the resource, such as preventi
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      name: <string>  # REQUIRED | string | Name of the AI Search endpoint
      permissions:  # array[object] | The permissions to apply to this resource.
        -
          group_name: <string>  # string | The name of the group granted the permission level.
          level: CAN_MANAGE  # REQUIRED | enum: CAN_MANAGE, CAN_RESTART, CAN_ATTACH_TO, IS_OWNER, CAN_MANAGE_RUN, CAN_VIEW, ... | The permission level to apply. The allowed levels depend on the resource type.
          service_principal_name: <string>  # string | The name of the service principal granted the permission level.
          user_name: <string>  # string | The name of the user granted the permission level.
      target_qps: <int>  # int | Target QPS for the endpoint. Mutually exclusive with num_replicas.
      usage_policy_id: <string>  # PRIVATE PREVIEW | string | The usage policy id to be applied once we've migrated to usage policies
```

## What to ask the user

- Endpoint type — `STORAGE_OPTIMIZED` or `STANDARD`?
- Target QPS for the endpoint?
