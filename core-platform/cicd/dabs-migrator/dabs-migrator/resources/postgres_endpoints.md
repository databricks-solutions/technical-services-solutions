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
      endpoint_type: ENDPOINT_TYPE_READ_WRITE  # REQUIRED | enum: ENDPOINT_TYPE_READ_WRITE, ENDPOINT_TYPE_READ_ONLY | The compute endpoint type. Either `read_write` or `read_only`.
      group:  # object
        enable_readable_secondaries: <bool>  # bool | [Beta] Whether to allow read-only connections to read-write endpoints. Only rele
        max: <int>  # REQUIRED | int | [Beta] The maximum number of computes in the endpoint group. Currently, this mus
        min: <int>  # REQUIRED | int | [Beta] The minimum number of computes in the endpoint group. Currently, this mus
      lifecycle:  # object | Settings that control the deployment lifecycle of the resource, such as preventi
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      no_suspension: <bool>  # bool
      parent: <string>  # REQUIRED | string
      replace_existing: <bool>  # bool
      settings:  # object | A collection of settings for a compute endpoint.
        pg_settings:  # map[string, string] | [Beta] A raw representation of Postgres settings.
          <key>: <value>
      suspend_timeout_duration: <string>  # string
```

## What to ask the user

- Read-write or read-only?
- Min/max CU and suspend timeout?
