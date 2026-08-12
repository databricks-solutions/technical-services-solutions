# Resource: `synced_database_tables`

Tables synced from a Databricks UC table to a Lakebase Postgres database.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#synced_database_table

## Complete schema reference

Required fields: `name`

```yaml
resources:
  synced_database_tables:
    <synced_database_table_name>:
      database_instance_name: <string>  # string | Name of the target database instance. This is required when creating synced data
      lifecycle:  # object | Settings that control the deployment lifecycle of the resource, such as preventi
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      logical_database_name: <string>  # string | Target Postgres database object (logical database) name for this table.
      name: <string>  # REQUIRED | string | Full three-part (catalog, schema, table) name of the table.
      spec:  # object | Specification of a synced database table.
        accelerated_sync: <bool>  # PRIVATE PREVIEW | bool | When true, enables accelerated sync mode for the initial data load.
        create_database_objects_if_missing: <bool>  # bool | If true, the synced table's logical database and schema resources in PG
        existing_pipeline_id: <string>  # string | At most one of existing_pipeline_id and new_pipeline_spec should be defined.
        new_pipeline_spec:  # object | At most one of existing_pipeline_id and new_pipeline_spec should be defined.
          budget_policy_id: <string>  # string | [Beta] Budget policy to set on the newly created pipeline.
          storage_catalog: <string>  # string | This field needs to be specified if the destination catalog is a managed postgre
          storage_schema: <string>  # string | This field needs to be specified if the destination catalog is a managed postgre
        primary_key_columns:  # array[string] | Primary Key columns to be used for data insert/update in the destination.
          - <value>
        scheduling_policy: CONTINUOUS  # enum: CONTINUOUS, TRIGGERED, SNAPSHOT | Scheduling policy of the underlying pipeline.
        source_table_full_name: <string>  # string | Three-part (catalog, schema, table) name of the source Delta table.
        timeseries_key: <string>  # string | Time series key to deduplicate (tie-break) rows with the same primary key.
        type_overrides:  # PRIVATE PREVIEW | array[object] | Override the default Delta->PG type mapping for specific columns.
          -
            column_name: <string>  # REQUIRED | PRIVATE PREVIEW | string | Name of the source column whose target PostgreSQL type should be overridden.
            pg_type: PG_SPECIFIC_TYPE_VECTOR  # REQUIRED | PRIVATE PREVIEW | enum: PG_SPECIFIC_TYPE_VECTOR | PostgreSQL-specific target type to use for the column.
            size: <int>  # PRIVATE PREVIEW | int | Size parameter for the target type. Required when pg_type is PG_SPECIFIC_TYPE_VE
```

## What to ask the user

- Source UC table?
- Target Lakebase database instance + logical database?
- Primary key column(s)?
- Continuous or triggered sync?
