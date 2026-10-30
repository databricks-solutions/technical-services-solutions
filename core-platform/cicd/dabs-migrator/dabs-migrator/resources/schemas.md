# Resource: `schemas`

Unity Catalog schemas (databases) within a catalog.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#schema

## Destroy protection

Always set `lifecycle.prevent_destroy: true` on migrated schemas. Once bound, the bundle owns the schema — running `databricks bundle destroy`, removing this YAML entry, or renaming the resource key will **delete the original schema and all tables, volumes, and views inside it**.

```yaml
resources:
  schemas:
    my_schema:
      lifecycle:
        prevent_destroy: true
      # ... rest of config
```

To intentionally destroy a bound schema: set `prevent_destroy: false`, run `databricks bundle deploy`, then `databricks bundle destroy`.

> ⚠️ **Never rename a bound resource's key.** A key rename is treated as delete + create by the bundle and will delete the original schema and its contents.

## Complete schema reference

Required fields: `catalog_name`, `name`

```yaml
resources:
  schemas:
    <schema_name>:
      catalog_name: <string>  # REQUIRED | string | Name of parent catalog.
      comment: <string>  # string | User-provided free-form text description.
      custom_max_retention_hours: <int>  # int | Custom maximum retention period in hours for the schema.
      grants:  # array[object] | The Unity Catalog privileges to grant to principals on this securable.
        -
          principal: <string>  # string | The principal (user email address or group name).
          privileges:  # array[string] | The privileges assigned to the principal.
            - <value>
      lifecycle:  # object | Settings that control the deployment lifecycle of the resource, such as preventi
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      name: <string>  # REQUIRED | string | Name of schema, relative to parent catalog.
      properties:  # map[string, string] | A map of key-value properties attached to the securable.
        <key>: <value>
      storage_root: <string>  # string | Storage root URL for managed tables within schema.
```

## What to ask the user

- Parent catalog?
- Initial grants?
