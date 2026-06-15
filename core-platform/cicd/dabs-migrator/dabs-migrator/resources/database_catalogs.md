# Resource: `database_catalogs`

Registers a Lakebase Postgres database as a Unity Catalog catalog so its tables are queryable from Databricks.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#database_catalog

## Complete schema reference

Required fields: `database_instance_name`, `database_name`, `name`

```yaml
resources:
  database_catalogs:
    <database_catalog_name>:
      create_database_if_not_exists: <bool>  # bool
      database_instance_name: <string>  # REQUIRED | string | The name of the DatabaseInstance housing the database.
      database_name: <string>  # REQUIRED | string | The name of the database (in a instance) associated with the catalog.
      lifecycle:  # object | Lifecycle is a struct that contains the lifecycle settings for a resource. It co
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      name: <string>  # REQUIRED | string | The name of the catalog in UC.
```

## What to ask the user

- Which Lakebase database instance and database name?
- Should the bundle create the DB if missing?
