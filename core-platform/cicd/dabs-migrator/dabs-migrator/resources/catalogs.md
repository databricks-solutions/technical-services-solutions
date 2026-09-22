# Resource: `catalogs`

Unity Catalog catalogs.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#catalog

## Complete schema reference

Required fields: `name`

```yaml
resources:
  catalogs:
    <catalog_name>:
      comment: <string>  # string | User-provided free-form text description.
      connection_name: <string>  # string | The name of the connection to an external data source.
      custom_max_retention_hours: <int>  # int | Custom maximum retention period in hours for the catalog
      grants:  # array[object] | The Unity Catalog privileges to grant to principals on this securable.
        -
          principal: <string>  # string | The principal (user email address or group name).
          privileges:  # array[string] | The privileges assigned to the principal.
            - <value>
      lifecycle:  # object | Settings that control the deployment lifecycle of the resource, such as preventi
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      managed_encryption_settings:  # object | Control CMK encryption for managed catalog data
        azure_encryption_settings:  # object | optional Azure settings - only required if an Azure CMK is used.
          azure_cmk_access_connector_id: <string>  # string
          azure_cmk_managed_identity_id: <string>  # string
          azure_tenant_id: <string>  # REQUIRED | string
        azure_key_vault_key_id: <string>  # string | the AKV URL in Azure, null otherwise.
        customer_managed_key_id: <string>  # string | the CMK uuid in AWS and GCP, null otherwise.
      name: <string>  # REQUIRED | string | Name of catalog.
      options:  # map[string, string] | A map of key-value properties attached to the securable.
        <key>: <value>
      properties:  # map[string, string] | A map of key-value properties attached to the securable.
        <key>: <value>
      provider_name: <string>  # string | The name of delta sharing provider.
      share_name: <string>  # string | The name of the share under the share provider.
      storage_root: <string>  # string | Storage root URL for managed tables within catalog.
```

## What to ask the user

- Managed location (storage root) or default?
- Initial grants?
