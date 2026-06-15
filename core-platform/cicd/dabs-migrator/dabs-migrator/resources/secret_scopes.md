# Resource: `secret_scopes`

Databricks secret scopes (containers for secrets).

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#secret_scope

## Hard rules

- **Never** put secret values in YAML or source. The bundle creates the scope; populate values out-of-band via `databricks secrets put-secret` or your secret manager.
- Reference secrets at runtime as `{{secrets/<scope>/<key>}}` from job/pipeline configs.

## Complete schema reference

Required fields: `name`

```yaml
resources:
  secret_scopes:
    <secret_scope_name>:
      backend_type: DATABRICKS  # enum: DATABRICKS, AZURE_KEYVAULT | The backend type the scope will be created with. If not specified, will default
      keyvault_metadata:  # object | The metadata for the secret scope if the `backend_type` is `AZURE_KEYVAULT`
        dns_name: <string>  # REQUIRED | string | The DNS of the KeyVault
        resource_id: <string>  # REQUIRED | string | The resource id of the azure KeyVault that user wants to associate the scope wit
      lifecycle:  # object | Lifecycle is a struct that contains the lifecycle settings for a resource. It co
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      name: <string>  # REQUIRED | string | Scope name requested by the user. Scope names are unique.
      permissions:  # array[object] | The permissions to apply to the secret scope. Permissions are managed via secret
        -
          group_name: <string>  # string | The name of the group that has the permission set in level. This field translate
          level: READ  # REQUIRED | enum: READ, WRITE, MANAGE | The allowed permission for user, group, service principal defined for this permi
          service_principal_name: <string>  # string | The application ID of an active service principal. This field translates to a `p
          user_name: <string>  # string | The name of the user that has the permission set in level. This field translates
```

## What to ask the user

- Databricks-backed scope or external (Azure Key Vault)?
- Which principals get READ vs MANAGE?
