# Resource: `postgres_catalogs`

Lakebase Postgres catalog — registers a Lakebase database as a Unity Catalog catalog so its tables are queryable from the lakehouse. One YAML per catalog under `resources/postgres_catalogs/<name>.yml`.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#postgres_catalog

## Destroy protection

Always set `lifecycle.prevent_destroy: true` on migrated Postgres catalogs. Once bound, the bundle owns the catalog — running `databricks bundle destroy`, removing this YAML entry, or renaming the resource key will **delete the UC catalog registration for the Postgres database**.

```yaml
resources:
  postgres_catalogs:
    my_pg_catalog:
      lifecycle:
        prevent_destroy: true
      # ... rest of config
```

To intentionally destroy a bound Postgres catalog: set `prevent_destroy: false`, run `databricks bundle deploy`, then `databricks bundle destroy`.

> ⚠️ **Never rename a bound resource's key.** A key rename is treated as delete + create by the bundle.

## Complete schema reference

Required fields: `catalog_id`, `postgres_database`

```yaml
resources:
  postgres_catalogs:
    <postgres_catalog_name>:
      branch: <string>  # string
      catalog_id: <string>  # REQUIRED | string
      create_database_if_missing: <bool>  # bool
      lifecycle:  # object | Settings that control the deployment lifecycle of the resource, such as preventi
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      postgres_database: <string>  # REQUIRED | string
```

## What to ask the user

- Which Lakebase project/branch backs the catalog?
- Create the Postgres database if it does not already exist?
