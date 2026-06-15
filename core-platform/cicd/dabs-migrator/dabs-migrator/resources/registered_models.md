# Resource: `registered_models`

Unity Catalog registered models (preferred over legacy `models`).

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#registered_model

## Complete schema reference

```yaml
resources:
  registered_models:
    <registered_model_name>:
      aliases:  # array[object]
        -
          alias_name: <string>  # string | Name of the alias, e.g. 'champion' or 'latest_stable'
          catalog_name: <string>  # string
          id: <string>  # string
          model_name: <string>  # string
          schema_name: <string>  # string
          version_num: <int>  # int | Integer version number of the model version to which this alias points.
      browse_only: <bool>  # bool
      catalog_name: <string>  # string | The name of the catalog where the schema and the registered model reside
      comment: <string>  # string | The comment attached to the registered model
      created_at: <int>  # int
      created_by: <string>  # string
      full_name: <string>  # string
      grants:  # array[object]
        -
          principal: <string>  # string | The principal (user email address or group name).
          privileges:  # array[enum] | The privileges assigned to the principal.
            - <value>
      lifecycle:  # object | Lifecycle is a struct that contains the lifecycle settings for a resource. It co
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      metastore_id: <string>  # string
      name: <string>  # string | The name of the registered model
      owner: <string>  # string
      schema_name: <string>  # string | The name of the schema where the registered model resides
      storage_location: <string>  # string | The storage location on the cloud under which model version data files are store
      updated_at: <int>  # int
      updated_by: <string>  # string
```

## What to ask the user

- Catalog and schema?
- Who needs EXECUTE (inference) vs MANAGE?
