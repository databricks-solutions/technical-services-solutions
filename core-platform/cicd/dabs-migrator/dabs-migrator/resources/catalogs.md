# Resource: `catalogs`

Unity Catalog catalogs.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#catalog

## Complete schema reference

Required fields: `name`

```yaml
resources:
  catalogs:
    <catalog_name>:
      comment: <string>  # string
      connection_name: <string>  # string
      grants:  # array[object]
        -
          principal: <string>  # string | The principal (user email address or group name).
          privileges:  # array[enum] | The privileges assigned to the principal.
            - <value>
      lifecycle:  # object
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      managed_encryption_settings:  # PRIVATE PREVIEW | object | Control CMK encryption for managed catalog data
        azure_encryption_settings:  # object | optional Azure settings - only required if an Azure CMK is used.
          azure_cmk_access_connector_id: <string>  # string
          azure_cmk_managed_identity_id: <string>  # string
          azure_tenant_id: <string>  # REQUIRED | string
        azure_key_vault_key_id: <string>  # string | the AKV URL in Azure, null otherwise.
        customer_managed_key_id: <string>  # string | the CMK uuid in AWS and GCP, null otherwise.
      name: <string>  # REQUIRED | string
      options:  # map[string, string]
        <key>: <value>
      properties:  # map[string, string]
        <key>: <value>
      provider_name: <string>  # string
      share_name: <string>  # string
      storage_root: <string>  # string
```

## What to ask the user

- Managed location (storage root) or default?
- Initial grants?
