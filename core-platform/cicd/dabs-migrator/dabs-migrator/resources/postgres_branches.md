# Resource: `postgres_branches`

Lakebase Autoscaling branch — copy-on-write Postgres branch within a project.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#postgres_branch

## Destroy protection

Always set `lifecycle.prevent_destroy: true` on migrated Postgres branches. Once bound, the bundle owns the branch — running `databricks bundle destroy`, removing this YAML entry, or renaming the resource key will **delete the original branch and all its data**.

```yaml
resources:
  postgres_branches:
    my_branch:
      lifecycle:
        prevent_destroy: true
      # ... rest of config
```

To intentionally destroy a bound branch: set `prevent_destroy: false`, run `databricks bundle deploy`, then `databricks bundle destroy`.

> ⚠️ **Never rename a bound resource's key.** A key rename is treated as delete + create by the bundle.

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
