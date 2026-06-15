# Resource: `volumes`

Unity Catalog volumes (file storage).

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#volume

## Complete schema reference

Required fields: `catalog_name`, `name`, `schema_name`

```yaml
resources:
  volumes:
    <volume_name>:
      catalog_name: <string>  # REQUIRED | string | The name of the catalog where the schema and the volume are
      comment: <string>  # string | The comment attached to the volume
      grants:  # array[object]
        -
          principal: <string>  # string | The principal (user email address or group name).
          privileges:  # array[enum] | The privileges assigned to the principal.
            - <value>
      lifecycle:  # object | Lifecycle is a struct that contains the lifecycle settings for a resource. It co
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      name: <string>  # REQUIRED | string | The name of the volume
      schema_name: <string>  # REQUIRED | string | The name of the schema where the volume is
      storage_location: <string>  # string | The storage location on the cloud
      volume_type: MANAGED  # enum: MANAGED, EXTERNAL
```

## What to ask the user

- MANAGED (Databricks-owned storage) or EXTERNAL (BYO cloud path)?
- If EXTERNAL: which `external_location` is the parent?
