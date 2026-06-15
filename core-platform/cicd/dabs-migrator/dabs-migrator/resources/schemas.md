# Resource: `schemas`

Unity Catalog schemas (databases) within a catalog.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#schema

## Complete schema reference

Required fields: `catalog_name`, `name`

```yaml
resources:
  schemas:
    <schema_name>:
      catalog_name: <string>  # REQUIRED | string | Name of parent catalog.
      comment: <string>  # string | User-provided free-form text description.
      grants:  # array[object]
        -
          principal: <string>  # string | The principal (user email address or group name).
          privileges:  # array[enum] | The privileges assigned to the principal.
            - <value>
      lifecycle:  # object | Lifecycle is a struct that contains the lifecycle settings for a resource. It co
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      name: <string>  # REQUIRED | string | Name of schema, relative to parent catalog.
      properties:  # map[string, string]
        <key>: <value>
      storage_root: <string>  # string | Storage root URL for managed tables within schema.
```

## What to ask the user

- Parent catalog?
- Initial grants?
