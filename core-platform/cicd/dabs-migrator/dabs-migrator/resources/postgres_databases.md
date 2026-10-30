# Resource: `postgres_databases`

Lakebase Postgres database — a logical Postgres database within a project branch. One YAML per database under `resources/postgres_databases/<name>.yml`.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#postgres_database

## Destroy protection

Always set `lifecycle.prevent_destroy: true` on migrated Postgres databases. Once bound, the bundle owns the database — running `databricks bundle destroy`, removing this YAML entry, or renaming the resource key will **delete the original Postgres database and all its data**.

```yaml
resources:
  postgres_databases:
    my_pg_database:
      lifecycle:
        prevent_destroy: true
      # ... rest of config
```

To intentionally destroy a bound Postgres database: set `prevent_destroy: false`, run `databricks bundle deploy`, then `databricks bundle destroy`.

> ⚠️ **Never rename a bound resource's key.** A key rename is treated as delete + create by the bundle.

## Complete schema reference

Required fields: `database_id`, `parent`

```yaml
resources:
  postgres_databases:
    <postgres_database_name>:
      database_id: <string>  # REQUIRED | string
      lifecycle:  # object | Settings that control the deployment lifecycle of the resource, such as preventi
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      parent: <string>  # REQUIRED | string
      postgres_database: <string>  # string
      role: <string>  # string
```

## What to ask the user

- Which parent project/branch owns the database?
- Owning Postgres role for the database?
