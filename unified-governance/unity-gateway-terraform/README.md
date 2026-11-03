# Unity Gateway Playbook: Manage Unity Gateway Resources with Terraform

This playbook shows the options to manage Unity Gateway resources with Terraform:

- **Access**: who can use which model service, for example `system.ai.claude-sonnet-4-6`, with Unity Catalog grants or ABAC GRANT policies.
- **Services**: your own model services, model provider services and MCP services, with routing and rate limits.
- **Budgets**: monthly AI Gateway limits that send an email or block usage.
- **Existing resources**: how to bring access and budgets that exist today under Terraform.

> **Business scenario:** Your platform team removed the default access to the `system.ai` models and gave `EXECUTE` to selected groups by hand. You also created budgets in the account console. Now you want Terraform to own both, so that every change goes through a pull request and changes made by hand are reverted.

> Unity Gateway changes fast. For current features, release status and limits, use the docs linked in [Further Reading](#further-reading). The summaries here can get old.

---

## Options at a glance

| What you manage | Terraform resource | Provider level |
| --- | --- | --- |
| Access to a model service (`system.ai` or your own) | [`databricks_grants`](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/grants) with `model_service` (recommended) or [`databricks_grant`](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/grant) | Workspace |
| Access to a model provider service or MCP service | The same resources, with `model_provider_service` or `mcp_service` | Workspace |
| Tag-based access, for example every Anthropic model | [`databricks_policy_info`](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/policy_info) with `POLICY_TYPE_GRANT` | Workspace |
| Your own services, with routing, fallback and rate limits | [`databricks_ai_gateway_model_service`](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/ai_gateway_model_service), [`databricks_ai_gateway_model_provider_service`](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/ai_gateway_model_provider_service), [`databricks_ai_gateway_mcp_service`](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/ai_gateway_mcp_service) | Workspace |
| AI Gateway budgets | [`databricks_budget`](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/budget) with `BUDGET_RESOURCE_TYPE_UNITY_AI_GATEWAY` | Account |
| Existing grants | Write the config to match today's grants. No import needed. | — |
| Existing budgets | [Import blocks](https://developer.hashicorp.com/terraform/language/import/generating-configuration) or the [exporter](https://registry.terraform.io/providers/databricks/databricks/latest/docs/guides/experimental-exporter) | Account |

The examples in this folder:

| Folder | What it holds |
| --- | --- |
| [`services/`](services) | Workspace level. Every Unity Gateway service is a Unity Catalog securable in a catalog schema, so one project holds them all: [`system_ai.tf`](services/system_ai.tf) (access to the `system.ai` model services), [`custom_services.tf`](services/custom_services.tf) (your own model provider, model and MCP services, with their grants) and an optional ABAC policy ([`abac_policy.tf.example`](services/abac_policy.tf.example)) |
| [`budgets/`](budgets) | Account level. A shared email budget and a per-user `BLOCK_USAGE` budget with a group override |

---

## Prerequisites

| Requirement | Details |
| --- | --- |
| Terraform | 1.5+ (import and check blocks) and provider `databricks/databricks` `~> 1.136` (schema-level `databricks_connection` for the MCP service). In your own repo, commit the `.terraform.lock.hcl` that `terraform init` creates, so that every run uses the same provider version and checksums. This examples repo does not track lock files. |
| Identity for access | A service principal with `MANAGE` on schema `system.ai`. The metastore owner alone is not enough. A metastore admin grants it once: `databricks grants update schema system.ai --json '{"changes":[{"principal":"<sp-application-id>","add":["MANAGE"]}]}'` |
| Identity for your own services | `USE CATALOG`, `USE SCHEMA` and `CREATE SERVICE` on the schema, `CREATE CONNECTION` for the MCP connection, and `READ_SECRET` on the provider key secret. This identity owns the services. Give no user `MANAGE` on the services, their schema or their catalog. |
| Identity for budgets | An account admin service principal, used only for `budgets/`. Account admin is a very powerful role: keep it separate from the services identity. |
| CI authentication | Workload identity federation (OIDC) for both service principals. No personal access tokens and no long-lived client secrets. |
| State | A remote backend with locking and encryption, and access for the pipeline identity only: the state holds the MCP bearer token. Use separate state for `services/` (workspace level) and `budgets/` (account level). |

Services and grants are stored in the metastore, so one `services/` project with any workspace on that metastore covers all its workspaces.

### Inputs

| Folder | Variable | What to set |
| --- | --- | --- |
| `services/` | `workspace_url` | Any workspace on the metastore |
| | `break_glass_group` | Small admin group that keeps `EXECUTE` on every model |
| | `account_users_schema_privileges` | Today's privileges of `account users` on `system.ai` minus `EXECUTE`, `MANAGE` and `ALL_PRIVILEGES`, with `USE_SCHEMA`, or `null` (see [option 1](#option-1-direct-grants-with-databricks_grants-recommended)) |
| | `catalog`, `schema` | Where your own services live (`schema` defaults to `ai_services`) |
| | `provider_base_url`, `provider_api_key_secret` | HTTPS endpoint of the external provider, and the full name of the Unity Catalog secret that holds its key (see [option 4](#option-4-your-own-services)) |
| | `ai_users_group` | Group that can call your model service and MCP service |
| | `mcp_server_url`, `mcp_server_base_path`, `mcp_bearer_token`, `mcp_tools` | An MCP server that you trust, its path (default `/mcp`), its token (pass it with `TF_VAR_mcp_bearer_token`), and the tools to expose |
| `budgets/` | `account_host`, `account_id` | Account console host of your cloud (see [Budgets](#budgets)) and account ID |
| | `budget_alert_email` | Email address for the shared budget alert |
| | `budget_workspace_ids` | Workspaces the budgets count and block. `[]` means all workspaces |

---

## Option 1: Direct grants with `databricks_grants` (recommended)

One `databricks_grants` resource is the full access list of one model service. It removes principals that are not listed, including the default `account users`, and reverts grants added by hand. For several models, use `for_each` over a map of model → groups ([`services/system_ai.tf`](services/system_ai.tf)):

```hcl
locals {
  model_groups = {
    "claude-sonnet-4-6" = ["data-scientists", "ml-engineers"]
    "claude-opus-4-7"   = ["genai-power-users"]
    "gemma-3-12b"       = [] # locked
  }
}

resource "databricks_grants" "system_ai_models" {
  for_each      = local.model_groups
  model_service = "system.ai.${each.key}"

  dynamic "grant" {
    for_each = toset(concat([var.break_glass_group], each.value))
    content {
      principal  = grant.value
      privileges = ["EXECUTE"]
    }
  }

  lifecycle {
    prevent_destroy = true # a destroy revokes every grant in the resource
  }
}
```

- **List every model in `system.ai`, with a fixed list.** Do not build the list from the `databricks_ai_gateway_model_services` data source. Its list API can return an empty result, and an empty `for_each` makes Terraform revoke the grants. New models then come in through a pull request.
- **A model that is not in the list closes for everyone.** It has no direct grant. When `account users` loses `EXECUTE` on the schema (see **Check the schema** below), nobody can use it, also not the break-glass group, and the plan shows only "create". The example in `system_ai.tf` lists 6 models: add all models of your metastore before you apply.
- **Keep a break-glass group on every model.** `databricks_grants` needs at least one grant (`Insufficient grant blocks`), and a locked model then has only that group.

Add a `check` block that warns about models that are not in `model_groups`, for example a new model from Databricks. It only warns and never changes a grant, so an empty result from the data source is safe here:

```hcl
check "all_system_ai_models_listed" {
  data "databricks_ai_gateway_model_services" "system_ai" {
    parent = "schemas/system.ai"
  }

  assert {
    condition = length(setsubtract(
      [for s in data.databricks_ai_gateway_model_services.system_ai.model_services : trimprefix(s.name, "model-services/system.ai.")],
      keys(local.model_groups),
    )) == 0
    error_message = "Models not in model_groups: ${join(", ", sort(setsubtract(
      [for s in data.databricks_ai_gateway_model_services.system_ai.model_services : trimprefix(s.name, "model-services/system.ai.")],
      keys(local.model_groups),
    )))}. Without the schema EXECUTE of account users, they are closed for everyone."
  }
}
```

**Check the schema.** In many metastores, `account users` has `EXECUTE` on the schema `system.ai`, directly or through `ALL_PRIVILEGES`, and the models have no direct grants. Every model inherits it, and a revoke on one model has no effect. Read today's grants:

```bash
databricks grants get schema system.ai
databricks grants get model_service system.ai.claude-sonnet-4-6
```

Then remove that `EXECUTE` after the per-model grants exist. `databricks_grant` sets the schema privileges of `account users` to exactly its list: it also adds missing privileges and removes others. Copy today's privileges of `account users`, minus `EXECUTE`, `MANAGE` and `ALL_PRIVILEGES`. The privileges differ per metastore. If `account users` has `MANAGE` or `ALL_PRIVILEGES` on `system.ai`, every user can grant themselves `EXECUTE`: remove them (a validation rejects them). `ALL_PRIVILEGES` includes `USE_SCHEMA` without listing it, so replace it with the privileges that users need, at least `USE_SCHEMA`. Without `USE_SCHEMA`, no user can use any model in `system.ai`, and a second validation requires it. If `account users` has none of these three, set the variable to `null`, and the project does not change the schema grant:

```hcl
variable "account_users_schema_privileges" {
  description = "Today's privileges of account users on schema system.ai (databricks grants get schema system.ai) minus EXECUTE, MANAGE and ALL_PRIVILEGES, and with USE_SCHEMA. ALL_PRIVILEGES includes USE_SCHEMA without listing it: replace it with the privileges users need. Set null if account users have none of EXECUTE, MANAGE and ALL_PRIVILEGES on the schema: then this project does not change the schema grant. Set it before the first apply."
  type        = list(string)

  validation {
    condition     = var.account_users_schema_privileges == null ? true : length(setintersection(var.account_users_schema_privileges, ["EXECUTE", "MANAGE", "ALL_PRIVILEGES"])) == 0
    error_message = "Remove EXECUTE, MANAGE and ALL_PRIVILEGES: with them, account users keep access to every model or can grant it to themselves."
  }

  validation {
    condition     = var.account_users_schema_privileges == null ? true : contains(var.account_users_schema_privileges, "USE_SCHEMA")
    error_message = "Keep USE_SCHEMA: without it, no user can use any model in system.ai."
  }
}

resource "databricks_grant" "system_ai_schema_account_users" {
  count      = var.account_users_schema_privileges == null ? 0 : 1
  schema     = "system.ai"
  principal  = "account users"
  privileges = var.account_users_schema_privileges
  depends_on = [databricks_grants.system_ai_models]

  lifecycle {
    prevent_destroy = true # a destroy revokes all account users privileges on system.ai
  }
}
```

## Option 2: One principal with `databricks_grant`

`databricks_grant` manages the privileges of **one** principal on one securable, and ignores all other principals. Use it when another team owns the rest of the access list. For example, `system_ai.tf` uses it for the `account users` grant on the schema, so other schema grants stay as they are. For model services it is a weak choice: it does not remove the default grant unless you add a resource for it, and it does not see a grant that someone adds by hand for another principal.

## Option 3: Tag-based access with an ABAC GRANT policy

Databricks tags each `system.ai` model with `ai.model_creator` (for example `anthropic`) and `ai.model_family` (for example `claude-sonnet`). One policy on the schema can give `EXECUTE` on every model with a tag ([`services/abac_policy.tf.example`](services/abac_policy.tf.example)):

```hcl
resource "databricks_policy_info" "claude_models" {
  name                  = "grant-claude-models"
  on_securable_type     = "SCHEMA"
  on_securable_fullname = "system.ai"
  policy_type           = "POLICY_TYPE_GRANT"
  for_securable_type    = "MODEL_SERVICE"
  to_principals         = ["data-scientists", "ml-engineers"]
  when_condition        = "has_tag_value('ai.model_creator', 'anthropic')"
  grant = {
    privileges = ["EXECUTE"]
  }
}
```

| | Direct grants (option 1) | ABAC GRANT policy |
| --- | --- | --- |
| New model from Databricks | Closed until you add it in a pull request | Opens at once if it has the tag |
| Removes the default grant | Yes | No: policies only add access |
| Shown in `databricks grants get` | Yes | No: read the policies (`databricks policies list-policies SCHEMA system.ai`) |

- Keep option 1 with the policy: only `databricks_grants` removes the default grant. Give the models only the break-glass group (`[]`), so the policy is the only way in. `databricks_grants` does not see the policy access as drift.
- Use only the Databricks system tags (`ai.*`) in `when_condition`. With a tag that users can set, anyone with `APPLY TAG` can open access.
- A policy opens new models with no review. If each new model must be approved first, use option 1 alone.
- Policies cannot grant `USE CATALOG` or `USE SCHEMA`. The groups still need them on `system` and `system.ai` (`account users` has them by default).
- Import an existing policy with `id = "SCHEMA,system.ai,<policy-name>"`.

## Option 4: Your own services

Create your own services in a schema you own ([`services/custom_services.tf`](services/custom_services.tf)). They live next to the `system.ai` grants in the same project:

| Resource | What it does | Clients call it with |
| --- | --- | --- |
| `databricks_ai_gateway_model_provider_service` | Points to the credential for an external provider and lists the models (`targets`) | Only with `EXECUTE` on it, which this example does not grant: header `Databricks-Model-Provider-Service: <catalog>.<schema>.<name>` on `/ai-gateway/openai/v1/chat/completions` |
| `databricks_ai_gateway_model_service` | A stable name with routing, traffic split, fallback and `rate_limits`. Routes to provider services or Databricks models | `model = "<catalog>.<schema>.<name>"` on `/ai-gateway/mlflow/v1/chat/completions` |
| `databricks_connection` (`HTTP`, `parent = "schemas/..."`) + `databricks_ai_gateway_mcp_service` | Governs an external MCP server, with a tool allowlist (`include_tool_selectors`) and optional `rate_limits` | `https://<workspace>/ai-gateway/mcp-services/<catalog>.<schema>.<name>` |

Store the provider key in a Unity Catalog secret. A secret owner creates it outside Terraform, so the key is not in the Terraform state, the plan or the CI logs. The key goes through stdin, not the command line:

```bash
read -rs PROVIDER_API_KEY # paste the key; it is not shown and not saved in the shell history
printf '{"name":"provider_key","catalog_name":"<catalog>","schema_name":"<schema>","value":"%s"}' "$PROVIDER_API_KEY" \
  | databricks secrets-uc create-secret --json @/dev/stdin
unset PROVIDER_API_KEY

# The owner of the provider service (the Terraform service principal) needs READ_SECRET. Callers need nothing on the secret.
databricks grants update secret <catalog>.<schema>.provider_key \
  --json '{"changes":[{"principal":"<terraform-sp-application-id>","add":["READ_SECRET"]}]}'
```

Terraform gets only the name of the secret:

```hcl
resource "databricks_ai_gateway_model_provider_service" "chat_provider" {
  parent                    = "schemas/${var.catalog}.${var.schema}"
  model_provider_service_id = "chat_provider"
  config = {
    provider_type = "EXTERNAL_MODEL_PROVIDER_TYPE_CUSTOM"
    targets       = [{ model = "chat-model", native_api_types = ["openai/v1/chat/completions"] }]
    custom = {
      direct = {
        base_url = var.provider_base_url # the FULL https:// endpoint URL
        api_key  = { secret_reference = { name = "secrets/${var.provider_api_key_secret}" } } # form secrets/<catalog>.<schema>.<secret>
      }
    }
  }
}

resource "databricks_grants" "chat" {
  model_service = "${var.catalog}.${var.schema}.chat"
  grant {
    principal  = var.ai_users_group
    privileges = ["EXECUTE"] # on the model service only, not on the provider service
  }
}
```

- **Access:** callers need `EXECUTE` on the model service or the MCP service, `USE CATALOG` and `USE SCHEMA`, and workspace access (the `workspace-consume` entitlement is enough). A model service caller needs no privilege on the provider service. Do not grant `EXECUTE` on the provider service: callers would then skip the model service and its rate limits. Do not grant `USE CONNECTION` on the MCP connection: callers would then use its token without the MCP service.
- **Provider key:** do not use `api_key = { plaintext = ... }`. Terraform then stores the key in clear text in the state and in saved plans. If the owner of the provider service loses `READ_SECRET`, the provider stops for all callers.
- **Who can change a service:** anyone with `MANAGE` on a provider service, its schema or its catalog can change `base_url`, and the gateway then sends the key to the new URL. Keep ownership and `MANAGE` with the Terraform service principal, and check them with `databricks grants get schema <catalog>.<schema>`.
- **Custom provider `base_url`:** Unity Gateway sends requests to this URL as it is and adds no path. Give the full HTTPS endpoint, for example `https://api.example.com/v1/chat/completions`. The provider gets the prompts and the responses: approve it for the data that your users send.
- **MCP server:** register only a server that you trust. It gets every tool call and its arguments, and its answers go to the model, so treat them as untrusted input (prompt injection). List the tools to expose in `mcp_tools`: an empty `include_tool_selectors` list exposes all tools.
- **MCP connection:** create a schema-level `HTTP` connection. Do not set `is_mcp_connection` (schema-level connections reject it). Do not set `auth_scheme`: the API rejects it on create but adds it on read, so `custom_services.tf` ignores only that key (`ignore_changes = [options["auth_scheme"]]`). The bearer token is stored in the connection and in the Terraform state.
- **Key and URL changes:** gateway replicas do not get a new `api_key` and `base_url` at the same time. For a few minutes, a request can go to the new URL with the old key, or to the old URL with the new key. One good response does not show that all replicas have the change. To move a provider to a new URL, create a new provider service and point the model service to it. Never point a provider service that holds a real key at a URL you do not trust, even for a test. To test, use a provider service that only ever holds a dummy key.

## Budgets

Budgets are account-level objects: they need an account-level provider (`host = https://accounts.cloud.databricks.com` on AWS, `https://accounts.azuredatabricks.net` on Azure, `https://accounts.gcp.databricks.com` on GCP, plus `account_id`) and an account admin identity. [`budgets/budgets.tf`](budgets/budgets.tf) has two examples:

- a shared monthly budget that sends an email;
- a monthly cap for each user (`ALERT_CONFIGURATION_SCOPE_TYPE_PER_USER`) that blocks usage (`BLOCK_USAGE`), with a higher limit for one group (`principal_overrides`):

```hcl
resource "databricks_budget" "ai_gateway_per_user" {
  display_name  = "ai-gateway-monthly-per-user"
  resource_type = "BUDGET_RESOURCE_TYPE_UNITY_AI_GATEWAY"

  # Without workspace IDs, the budget blocks users in every workspace of the account.
  dynamic "filter" {
    for_each = length(var.budget_workspace_ids) > 0 ? [1] : []
    content {
      workspace_id {
        operator = "IN"
        values   = var.budget_workspace_ids
      }
    }
  }

  alert_configurations {
    time_period        = "MONTH"
    trigger_type       = "CUMULATIVE_SPENDING_EXCEEDED"
    quantity_type      = "LIST_PRICE_DOLLARS_USD"
    quantity_threshold = "100"
    scope_type         = "ALERT_CONFIGURATION_SCOPE_TYPE_PER_USER"

    # An override must be higher than quantity_threshold. Write it with two decimals, as the
    # API returns it: "300" shows a diff on every plan.
    principal_overrides {
      principal_id       = data.databricks_group.genai_power_users.id
      override_threshold = "300.00"
    }

    action_configurations {
      action_type = "BLOCK_USAGE"
    }
  }
}
```

- **Start with one workspace.** With `budget_workspace_ids = []`, a `BLOCK_USAGE` budget blocks users in every workspace of the account. Try a new budget with one workspace ID first.
- **An override can only raise the limit.** The API rejects an override that is not greater than `quantity_threshold`.
- **Write `override_threshold` with two decimals**, for example `"300.00"`. The API stores two decimals and the provider compares the text, so `"300"` shows a change on every plan. The example in the provider docs uses `"300"`.
- A blocked user gets HTTP 403 `PERMISSION_DENIED`: `Budget "<name>" (<id>) has reached its limit of $<amount>`. Enforcement is near real-time and uses an estimate of the cost (see [Unity Gateway budgets](https://docs.databricks.com/aws/en/ai-gateway/budgets)). A budget is a cost control, not a security boundary.

AI Gateway budgets also count usage from Databricks products that use the gateway, such as Genie.

---

## Bring an existing setup under Terraform

### Grants: no import, but the first plan must match today

`databricks_grants` needs no import: the first apply replaces the access list. On that first apply the plan shows only "create". It does not show which grants it will remove. So:

1. Read today's grants for the schema and every model: `databricks grants get schema system.ai` and `databricks grants get model_service system.ai.<model>`.
2. Set `account_users_schema_privileges` to today's privileges of `account users` on the schema minus `EXECUTE`, `MANAGE` and `ALL_PRIVILEGES`, and with `USE_SCHEMA` (replace `ALL_PRIVILEGES` with the privileges users need). Set it to `null` if `account users` has none of these three.
3. Write `local.model_groups` so that every model in `system.ai` keeps the groups that can use it today. Access from the schema counts: if `account users` has `EXECUTE` or `ALL_PRIVILEGES` on the schema, add `"account users"` to every model that must stay open. Terraform then creates the per-model grants first and removes `EXECUTE` from the schema after them, so there is no gap.
4. Run `terraform plan -out=tf.plan` and compare each planned access list with step 1. The only expected addition is the break-glass group.
5. Apply that saved plan: `terraform apply tf.plan`. No user loses or gets access to a model. The one intended change: `account users` loses `MANAGE` and `ALL_PRIVILEGES` on the schema, if it had them.
6. To close models for `account users`, remove `"account users"` from them in a second pull request.

The [Terraform exporter](https://registry.terraform.io/providers/databricks/databricks/latest/docs/guides/experimental-exporter) does not help here: it skips the `system` catalog, so it exports no `system.ai` grants.

### Budgets: import

An import changes nothing in the account. Terraform only starts to track the budget.

**Option A: import blocks (recommended, you select the budgets)**

```hcl
# 1. Find the IDs: databricks account budgets list -o json
#    (keep the budgets with resource_type = BUDGET_RESOURCE_TYPE_UNITY_AI_GATEWAY)
import {
  to = databricks_budget.ai_gateway_per_user
  id = "<account_id>|<budget_configuration_id>"
}
```

```bash
# 2. Terraform reads the live budget and writes its configuration
terraform plan -generate-config-out=generated.tf
```

3. Clean `generated.tf`, then move it into `budgets.tf`:
   - remove the read-only fields `account_id`, `budget_configuration_id`, `create_time`, `update_time`, `alert_configuration_id` and `action_configuration_id`;
   - replace each numeric `principal_id` in `principal_overrides` with a data source, for example `data.databricks_group.genai_power_users.id`;
   - write each `override_threshold` with two decimals, for example `"500.00"` (the generated config can have `jsonencode(500)`; see [Budgets](#budgets)).
4. `terraform plan` must show `1 to import, 0 to add, 0 to change, 0 to destroy`. Apply, then remove the import block.

Known provider issue [#5978](https://github.com/databricks/terraform-provider-databricks/issues/5978): the API returns alerts, actions and principal overrides in its own order, and the provider compares them by position. If a budget has more than one alert, or an alert has more than one action or override, a plan can show changes that you did not make, and an apply can fail with `Action type cannot be updated`. The API returns the same order on every read, so keep these blocks in the order of `generated.tf`. The open provider PR [#6100](https://github.com/databricks/terraform-provider-databricks/pull/6100) fixes this issue and the `override_threshold` format.

**Option B: the Terraform exporter**

The exporter is a command in the provider binary (after `terraform init`, under `.terraform/providers/registry.terraform.io/databricks/databricks/<version>/<os_arch>/`):

```bash
# An account-level CLI profile (host + account_id) with OAuth login. Do not put a client secret in the shell.
export DATABRICKS_CONFIG_PROFILE=<account-profile>

./terraform-provider-databricks exporter -skip-interactive \
  -listing billing -services billing -native-import -directory budgets_export
```

- It writes `databricks_budget` and `databricks_budget_policy` resources, import blocks and a provider block.
- It has no name filter for budgets: it exports **every** budget and serverless budget policy in the account, which can take a long time on a large account. Delete what you do not want Terraform to manage.
- The output holds alert emails and principal IDs, and `budgets_export/` is in `.gitignore`. Clean it as in step 3 of option A, and move only the cleaned config into `budgets.tf`.

If you recreate a budget in Terraform instead of importing it, delete the old budget afterwards. Two `BLOCK_USAGE` budgets both block.

---

## Keep it safe

- **Never apply a plan with unexpected destroys.** A destroy of `databricks_grants` revokes every grant in it. In CI, save the plan (`terraform plan -out`), fail the job if `terraform show -json` lists a `delete` for `databricks_grants`, `databricks_grant` or `databricks_budget`, and apply only that saved plan. `prevent_destroy` is a second safeguard.
- **Treat plans as secrets.** A saved plan and the `terraform show -json` output hold sensitive values in clear text, for example the MCP bearer token. Keep them inside the job, and never publish them as build artifacts or in logs.
- **Keep one `databricks_grants` resource keyed by model.** If you move a model from one resource to another, the destroy fails (`permissions ... have to be []`). Use a `moved` block or `terraform state rm`.
- **To retire a model**, remove it from `model_groups` and run `terraform state rm 'databricks_grants.system_ai_models["<model>"]'` on purpose.
- **Stop changes by hand:** keep `MANAGE` on `system.ai` and on the services schema for the Terraform service principal only, and run `terraform plan -detailed-exitcode` every day to find drift (exit code 2). Drift detection only covers the resources in the state: also check who has `MANAGE` on the schema and catalog.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Insufficient grant blocks` | A model with no grants | Keep the break-glass group on every model |
| `User does not have MANAGE on MODEL_SERVICE` | The Terraform identity has no `MANAGE` | Grant `MANAGE` on `system.ai` |
| Plan wants to destroy many grants | The model list came from a data source that returned empty | Use a fixed list |
| Warning `Models not in model_groups: ...` | `system.ai` has a model that is not in the list, for example a new one | Add it to `model_groups`, with `[]` to keep it locked |
| Revoke on one model has no effect | `account users` has `EXECUTE` or `ALL_PRIVILEGES` on the schema | Remove them from the schema grant (`account_users_schema_privileges`) |
| `'system.ai.<model>' does not exist` | No `EXECUTE`, or the change is still propagating | Wait a few minutes, then check the grants and policies |
| User has access, but `grants get` shows nothing | Access comes from an ABAC policy | `databricks policies list-policies SCHEMA system.ai` |
| MCP call returns JSON-RPC error `-32007 Not authorized to invoke MCP service` | No `EXECUTE` on the MCP service | Grant `EXECUTE` with `databricks_grants` and `mcp_service` |
| MCP call returns JSON-RPC error `-32003 Tool not allowed by MCP service configuration` | The tool is not in `mcp_tools` (`include_tool_selectors`) | Add the tool only if users need it |
| `secret_reference must be of the form secrets/{catalog}.{schema}.{leaf}` | The secret name has no `secrets/` prefix | Use `secrets/<catalog>.<schema>.<secret>` |
| `Model Service returned error with status code 401` | The provider rejected the key from the secret | Check the value in the secret, and that the provider service owner has `READ_SECRET` |
| HTTP 403 `This API is disabled for users without the databricks-sql-access or workspace-access or workspace-consume entitlement` | The caller has no workspace entitlement | Give the caller `workspace-consume` |
| Provider error `Path must be of form /serving-endpoints/...` or another upstream 404 | `base_url` is a base path, not the full endpoint | Set the full endpoint URL |
| `Setting is_mcp_connection is not supported on schema-level connections` | `is_mcp_connection` set on the connection | Remove it; the MCP service does that job |
| `CONNECTION_HTTP_BEARER does not support the following option(s): auth_scheme` | `auth_scheme` set in `options` | Remove it |
| `databricks_connection` shows a change in `options` on every plan | The API adds `auth_scheme` on read | `lifecycle { ignore_changes = [options["auth_scheme"]] }`, as in `custom_services.tf` |
| `databricks_budget` shows `override_threshold = "500.00" -> "500"` on every plan | The API returns two decimals, and the provider compares the text | Write `"500.00"` |
| HTTP 403 `PERMISSION_DENIED` `Budget "<name>" (<id>) has reached its limit` | A `BLOCK_USAGE` budget blocks the user | Raise the threshold, give the user a higher override, or delete the budget |
| `Override threshold ... must be greater than the alert's default threshold` | The override is lower than `quantity_threshold` | Overrides only raise a limit. Lower `quantity_threshold`, and give the higher limit as the override |

---

## Further Reading

- [Unity Gateway documentation](https://docs.databricks.com/aws/en/ai-gateway/)
- [Govern access to models with grant policies](https://docs.databricks.com/aws/en/ai-gateway/govern-access-to-models-with-grant-policies)
- [Unity Gateway budgets](https://docs.databricks.com/aws/en/ai-gateway/budgets)
- [Unity Gateway rate limits](https://docs.databricks.com/aws/en/ai-gateway/rate-limits)
- [Query model provider services](https://docs.databricks.com/aws/en/ai-gateway/query-model-provider-services) and [register an external MCP server](https://docs.databricks.com/aws/en/ai-gateway/register-mcp-service)
- [Terraform exporter guide](https://registry.terraform.io/providers/databricks/databricks/latest/docs/guides/experimental-exporter)
- [Terraform import blocks with generated configuration](https://developer.hashicorp.com/terraform/language/import/generating-configuration)
