# Resource: `postgres_roles`

Lakebase Postgres role — a Databricks-managed identity (user, service principal, or group) mapped to a Postgres role on a branch. One YAML per role under `resources/postgres_roles/<name>.yml`.

Docs: https://docs.databricks.com/aws/en/dev-tools/bundles/resources#postgres_role

## Complete schema reference

Required fields: `parent`, `role_id`

```yaml
resources:
  postgres_roles:
    <postgres_role_name>:
      attributes:  # object | The desired API-exposed Postgres role attributes to associate with the role.
        bypassrls: <bool>  # bool | [Beta]
        createdb: <bool>  # bool | [Beta]
        createrole: <bool>  # bool | [Beta]
      auth_method: NO_LOGIN  # enum: NO_LOGIN, PG_PASSWORD_SCRAM_SHA_256, LAKEBASE_OAUTH_V1 | How the role is authenticated when connecting to Postgres. If left unspecified,
      identity_type: USER  # enum: USER, SERVICE_PRINCIPAL, GROUP | The type of the Databricks managed identity that this Role represents. Leave emp
      lifecycle:  # object | Settings that control the deployment lifecycle of the resource, such as preventi
        prevent_destroy: <bool>  # bool | Lifecycle setting to prevent the resource from being destroyed.
      membership_roles:  # array[string] | Standard roles that this role is a member of.
        - <value>
      parent: <string>  # REQUIRED | string | The branch where this role is created. Format projects/{project_id}/branches/{br
      postgres_role: <string>  # string | The name of the Postgres role. Required when creating the role.
      role_id: <string>  # REQUIRED | string | The user-specified role ID; becomes the final component of the role's resource n
```

## What to ask the user

- Which identity does the role represent (user / service principal / group)?
- Authentication method (`NO_LOGIN`, `PG_PASSWORD_SCRAM_SHA_256`, `LAKEBASE_OAUTH_V1`)?
- Role attributes (`createdb`, `createrole`, `bypassrls`) and any membership roles?
