# Resource: `postgres_endpoints`

Lakebase Autoscaling compute endpoint — connection point for a branch.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#postgres_endpoint

## Complete schema reference

Required fields: `endpoint_id`, `endpoint_type`, `parent`

```yaml
resources:
  postgres_endpoints:
    <postgres_endpoint_name>:
      autoscaling_limit_max_cu: <float>  # float
      autoscaling_limit_min_cu: <float>  # float
      disabled: <bool>  # bool
      endpoint_id: <string>  # REQUIRED | string
      endpoint_type: ENDPOINT_TYPE_READ_WRITE  # REQUIRED | enum: ENDPOINT_TYPE_READ_WRITE, ENDPOINT_TYPE_READ_ONLY
      group:  # object
        enable_readable_secondaries: <bool>  # bool | Whether to allow read-only connections to read-write endpoints. Only relevant fo
        max: <int>  # REQUIRED | int | The maximum number of computes in the endpoint group. Currently, this must be eq
        min: <int>  # REQUIRED | int | The minimum number of computes in the endpoint group. Currently, this must be eq
      lifecycle:  # object
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      no_suspension: <bool>  # bool
      parent: <string>  # REQUIRED | string
      settings:  # object
        pg_settings:  # map[string, string] | A raw representation of Postgres settings.
          <key>: <value>
      suspend_timeout_duration: <string>  # string
```

## What to ask the user

- Read-write or read-only?
- Min/max CU and suspend timeout?
