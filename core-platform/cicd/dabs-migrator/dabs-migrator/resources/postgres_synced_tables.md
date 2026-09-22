# Resource: `postgres_synced_tables`

Lakebase Postgres synced table — continuously (or on a schedule) syncs a Unity Catalog source table into a Lakebase Postgres database. One YAML per synced table under `resources/postgres_synced_tables/<name>.yml`.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#postgres_synced_table

## Complete schema reference

Required fields: `synced_table_id`

```yaml
resources:
  postgres_synced_tables:
    <postgres_synced_table_name>:
      accelerated_sync: <bool>  # bool
      branch: <string>  # string
      create_database_objects_if_missing: <bool>  # bool
      existing_pipeline_id: <string>  # string
      lifecycle:  # object | Settings that control the deployment lifecycle of the resource, such as preventi
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      new_pipeline_spec:  # object
        budget_policy_id: <string>  # string | [Beta] Budget policy to set on the newly created pipeline.
        storage_catalog: <string>  # string | [Beta] UC catalog for the pipeline to store intermediate files (checkpoints, eve
        storage_schema: <string>  # string | [Beta] UC schema for the pipeline to store intermediate files (checkpoints, even
      postgres_database: <string>  # string
      primary_key_columns:  # array[string]
        - <value>
      scheduling_policy: CONTINUOUS  # enum: CONTINUOUS, TRIGGERED, SNAPSHOT | Scheduling policy of the synced table's underlying pipeline.
      source_table_full_name: <string>  # string
      synced_table_id: <string>  # REQUIRED | string
      timeseries_key: <string>  # string
      type_overrides:  # array[object]
        -
          column_name: <string>  # REQUIRED | PRIVATE PREVIEW | string | Name of the source column whose target PostgreSQL type should be overridden.
          pg_type: PG_SPECIFIC_TYPE_VECTOR  # REQUIRED | PRIVATE PREVIEW | enum: PG_SPECIFIC_TYPE_VECTOR | PostgreSQL-specific target type to use for the column.
          size: <int>  # PRIVATE PREVIEW | int | Size parameter for the target type. Required when pg_type is PG_SPECIFIC_TYPE_VE
```

## What to ask the user

- Source UC table (`source_table_full_name`) and primary key column(s)?
- Scheduling policy — `CONTINUOUS`, `TRIGGERED`, or `SNAPSHOT`?
- Reuse an `existing_pipeline_id` or create a new pipeline (`new_pipeline_spec`)?
