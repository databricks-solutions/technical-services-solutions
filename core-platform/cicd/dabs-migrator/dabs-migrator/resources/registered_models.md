# Resource: `registered_models`

Unity Catalog registered models (preferred over legacy `models`).

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#registered_model

## Complete schema reference

```yaml
resources:
  registered_models:
    <registered_model_name>:
      aliases:  # array[object] | List of aliases associated with the registered model
        -
          alias_name: <string>  # string | Name of the alias, e.g. 'champion' or 'latest_stable'
          catalog_name: <string>  # string | The name of the catalog containing the model version
          id: <string>  # string | The unique identifier of the alias
          model_name: <string>  # string | The name of the parent registered model of the model version, relative to parent
          schema_name: <string>  # string | The name of the schema containing the model version, relative to parent catalog
          version_num: <int>  # int | Integer version number of the model version to which this alias points.
      browse_only: <bool>  # bool | Indicates whether the principal is limited to retrieving metadata for the associ
      catalog_name: <string>  # string | The name of the catalog where the schema and the registered model reside
      comment: <string>  # string | The comment attached to the registered model
      created_at: <int>  # int | Creation timestamp of the registered model in milliseconds since the Unix epoch
      created_by: <string>  # string | The identifier of the user who created the registered model
      full_name: <string>  # string | The three-level (fully qualified) name of the registered model
      grants:  # array[object] | The Unity Catalog privileges to grant to principals on this securable.
        -
          principal: <string>  # string | The principal (user email address or group name).
          privileges:  # array[string] | The privileges assigned to the principal.
            - <value>
      lifecycle:  # object | Settings that control the deployment lifecycle of the resource, such as preventi
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      metastore_id: <string>  # string | The unique identifier of the metastore
      name: <string>  # string | The name of the registered model
      owner: <string>  # string | The identifier of the user who owns the registered model
      schema_name: <string>  # string | The name of the schema where the registered model resides
      storage_location: <string>  # string | The storage location on the cloud under which model version data files are store
      updated_at: <int>  # int | Last-update timestamp of the registered model in milliseconds since the Unix epo
      updated_by: <string>  # string | The identifier of the user who updated the registered model last time
```

## What to ask the user

- Catalog and schema?
- Who needs EXECUTE (inference) vs MANAGE?
