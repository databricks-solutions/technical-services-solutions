# Resource: `postgres_branches`

Lakebase Autoscaling branch — copy-on-write Postgres branch within a project.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#postgres_branch

## Complete schema reference

Required fields: `branch_id`, `parent`

```yaml
resources:
  postgres_branches:
    <postgres_branch_name>:
      branch_id: <string>  # REQUIRED | string
      expire_time:  # map[string, string]
        <key>: <value>
      is_protected: <bool>  # bool
      lifecycle:  # object | Settings that control the deployment lifecycle of the resource, such as preventi
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      no_expiry: <bool>  # bool
      parent: <string>  # REQUIRED | string
      replace_existing: <bool>  # bool
      source_branch: <string>  # string
      source_branch_lsn: <string>  # string
      source_branch_time:  # map[string, string]
        <key>: <value>
      ttl: <string>  # string
```

## What to ask the user

- Parent project + parent branch?
- Protected (no deletion) for prod branches?
