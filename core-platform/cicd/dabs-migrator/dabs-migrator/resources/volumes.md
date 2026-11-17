# Resource: `volumes`

Unity Catalog volumes (file storage).

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#volume

## Migration: environment isolation

Applies the environment-value hard rules in `SKILL.md`. A live read returns the source environment's values. Put them only in the source target's `targets.<target>.variables`; every other target, and `dev` in particular, gets its own value. Never leave a literal from the live read in the fields below.

| Field | Use |
|---|---|
| `catalog_name`, `schema_name` | `${var.catalog}`, `${var.schema}` |
| `storage_location` (external volumes) | a per-target variable. Never point a dev volume at the production storage path |

## Complete schema reference

Required fields: `catalog_name`, `name`, `schema_name`

```yaml
resources:
  volumes:
    <volume_name>:
      catalog_name: <string>  # REQUIRED | string | The name of the catalog where the schema and the volume are
      comment: <string>  # string | The comment attached to the volume
      grants:  # array[object] | The Unity Catalog privileges to grant to principals on this securable.
        -
          principal: <string>  # string | The principal (user email address or group name).
          privileges:  # array[string] | The privileges assigned to the principal.
            - <value>
      lifecycle:  # object | Settings that control the deployment lifecycle of the resource, such as preventi
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      name: <string>  # REQUIRED | string | The name of the volume
      schema_name: <string>  # REQUIRED | string | The name of the schema where the volume is
      storage_location: <string>  # string | The storage location on the cloud
      volume_type: MANAGED  # enum: MANAGED, EXTERNAL | The type of the volume. An external volume is located in the specified external
```

## What to ask the user

- MANAGED (Databricks-owned storage) or EXTERNAL (BYO cloud path)?
- If EXTERNAL: which `external_location` is the parent?
