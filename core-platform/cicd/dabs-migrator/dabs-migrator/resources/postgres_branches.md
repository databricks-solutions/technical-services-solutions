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
      expire_time:  # object
      is_protected: <bool>  # bool
      lifecycle:  # object
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      no_expiry: <bool>  # bool
      parent: <string>  # REQUIRED | string
      source_branch: <string>  # string
      source_branch_lsn: <string>  # string
      source_branch_time:  # object
      ttl: <string>  # string
```

## What to ask the user

- Parent project + parent branch?
- Protected (no deletion) for prod branches?
