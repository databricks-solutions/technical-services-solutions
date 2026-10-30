# Resource: `database_catalogs`

Registers a Lakebase Postgres database as a Unity Catalog catalog so its tables are queryable from Databricks.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#database_catalog

## Destroy protection

Always set `lifecycle.prevent_destroy: true` on migrated database catalogs. Once bound, the bundle owns the catalog registration — running `databricks bundle destroy`, removing this YAML entry, or renaming the resource key will **delete the UC catalog entry and the underlying Postgres database association**.

```yaml
resources:
  database_catalogs:
    my_db_catalog:
      lifecycle:
        prevent_destroy: true
      # ... rest of config
```

To intentionally destroy a bound database catalog: set `prevent_destroy: false`, run `databricks bundle deploy`, then `databricks bundle destroy`.

> ⚠️ **Never rename a bound resource's key.** A key rename is treated as delete + create by the bundle.

## Complete schema reference

Required fields: `database_instance_name`, `database_name`, `name`

```yaml
resources:
  database_catalogs:
    <database_catalog_name>:
      create_database_if_not_exists: <bool>  # bool
      database_instance_name: <string>  # REQUIRED | string | The name of the DatabaseInstance housing the database.
      database_name: <string>  # REQUIRED | string | The name of the database (in an instance) associated with the catalog.
      lifecycle:  # object | Settings that control the deployment lifecycle of the resource, such as preventi
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      name: <string>  # REQUIRED | string | The name of the catalog in UC.
```

## What to ask the user

- Which Lakebase database instance and database name?
- Should the bundle create the DB if missing?
