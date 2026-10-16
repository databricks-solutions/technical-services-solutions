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

| What you manage | Terraform resource | Provider level | Tested here |
| --- | --- | --- | --- |
| Access to a model service (`system.ai` or your own) | [`databricks_grants`](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/grants) with `model_service` (recommended) or [`databricks_grant`](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/grant) | Workspace | Yes |
| Access to a model provider service or MCP service | The same resources, with `model_provider_service` or `mcp_service` | Workspace | Yes (`databricks_grants`) |
| Tag-based access, for example every Anthropic model | [`databricks_policy_info`](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/policy_info) with `POLICY_TYPE_GRANT` | Workspace | Yes |
| Your own services, with routing, fallback and rate limits | [`databricks_ai_gateway_model_service`](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/ai_gateway_model_service), [`databricks_ai_gateway_model_provider_service`](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/ai_gateway_model_provider_service), [`databricks_ai_gateway_mcp_service`](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/ai_gateway_mcp_service) | Workspace | Yes (custom provider, routing, MCP) |
| AI Gateway budgets | [`databricks_budget`](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/budget) with `BUDGET_RESOURCE_TYPE_UNITY_AI_GATEWAY` | Account | Import only |
| Existing grants | Write the config to match today's grants. No import needed. | — | Yes |
| Existing budgets | [Import blocks](https://developer.hashicorp.com/terraform/language/import/generating-configuration) or the [exporter](https://registry.terraform.io/providers/databricks/databricks/latest/docs/guides/experimental-exporter) | Account | Import blocks: yes |

The examples in this folder:

| Folder | What it holds |
| --- | --- |
| [`services/`](services) | Workspace level. Every Unity Gateway service is a Unity Catalog securable in a catalog schema, so one project holds them all: [`system_ai.tf`](services/system_ai.tf) (access to the `system.ai` model services), [`custom_services.tf`](services/custom_services.tf) (your own model provider, model and MCP services, with their grants) and an optional ABAC policy ([`abac_policy.tf.example`](services/abac_policy.tf.example)) |
| [`budgets/`](budgets) | Account level. A shared email budget and a per-user `BLOCK_USAGE` budget with a group override |

---

## Prerequisites

| Requirement | Details |
| --- | --- |
| Terraform | 1.5+ (import blocks) and provider `databricks/databricks` 1.136.0+ (`model_service` grants) |
| Identity for access | A service principal with `MANAGE` on schema `system.ai`. The metastore owner alone is not enough. A metastore admin grants it once: `databricks grants update schema system.ai --json '{"changes":[{"principal":"<sp-application-id>","add":["MANAGE"]}]}'` |
| Identity for your own services | `USE CATALOG`, `USE SCHEMA` and `CREATE SERVICE` on the schema, plus `CREATE CONNECTION` for an MCP connection |
| Identity for budgets | An account admin service principal. Budgets are account-level objects. |
| State | A remote backend with locking. Use separate state for `services/` (workspace level) and `budgets/` (account level). |

Services and grants are stored in the metastore, so one `services/` project with any workspace on that metastore covers all its workspaces.

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

- **List every model in `system.ai`, with a fixed list.** Do not build the list from the `databricks_ai_gateway_model_services` data source. In our tests its list API returned an empty result on 5 of 6 calls, and an empty `for_each` made Terraform revoke the grants. New models then come in through a pull request.
- **Keep a break-glass group on every model.** `databricks_grants` needs at least one grant (`Insufficient grant blocks`), and a locked model then has only that group.
- **Check the schema.** In some metastores, `account users` has `EXECUTE` on the schema `system.ai`. Every model inherits it, and a revoke on one model has no effect. `system_ai.tf` sets the schema grant of `account users` without `EXECUTE`, after the per-model grants exist:

```bash
databricks grants get schema system.ai
databricks grants get model_service system.ai.claude-sonnet-4-6
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

- Keep option 1 with the policy: only `databricks_grants` removes the default grant. Give the models only the break-glass group (`[]`), so the policy is the only way in. In our test, `databricks_grants` did not see the policy access as drift.
- Policies cannot grant `USE CATALOG` or `USE SCHEMA`. The groups still need them on `system` and `system.ai` (`account users` has them by default).
- Import an existing policy with `id = "SCHEMA,system.ai,<policy-name>"`.

## Option 4: Your own services

Create your own services in a schema you own ([`services/custom_services.tf`](services/custom_services.tf)). They live next to the `system.ai` grants in the same project:

| Resource | What it does | Clients call it with |
| --- | --- | --- |
| `databricks_ai_gateway_model_provider_service` | Stores the credential for an external provider and lists the models (`targets`) callers can use | Header `Databricks-Model-Provider-Service: <catalog>.<schema>.<name>` on `/ai-gateway/openai/v1/chat/completions` (or the provider's other managed paths) |
| `databricks_ai_gateway_model_service` | A stable name with routing, traffic split, fallback and `rate_limits`. Routes to provider services or Databricks models | `model = "<catalog>.<schema>.<name>"` on `/ai-gateway/mlflow/v1/chat/completions` |
| `databricks_connection` (`HTTP`, `parent = "schemas/..."`) + `databricks_ai_gateway_mcp_service` | Governs an external MCP server, with optional tool selection and `rate_limits` | `https://<workspace>/ai-gateway/mcp-services/<catalog>.<schema>.<name>` |

```hcl
resource "databricks_ai_gateway_model_provider_service" "chat_provider" {
  parent                    = "schemas/${var.catalog}.${var.schema}"
  model_provider_service_id = "chat_provider"
  config = {
    provider_type = "EXTERNAL_MODEL_PROVIDER_TYPE_CUSTOM"
    targets       = [{ model = "chat-model", native_api_types = ["openai/v1/chat/completions"] }]
    custom = {
      direct = {
        base_url = var.provider_base_url                # the FULL endpoint URL
        api_key  = { plaintext = var.provider_api_key } # sensitive variable
      }
    }
  }
}

resource "databricks_grants" "chat_provider" {
  model_provider_service = "${var.catalog}.${var.schema}.chat_provider"
  grant {
    principal  = "ai-app-developers"
    privileges = ["EXECUTE"]
  }
}
```

- **Access:** callers need `EXECUTE` on the service plus `USE CATALOG` and `USE SCHEMA`. End users do not need `USE CONNECTION` on the MCP connection. Use `databricks_grants` with `model_provider_service`, `model_service` or `mcp_service`, as in option 1.
- **Credentials:** pass the provider key with a sensitive variable (`TF_VAR_provider_api_key`), never in code. The key is also stored in the Terraform state, so keep the state in an encrypted remote backend. The provider also accepts a reference to a Unity Catalog secret (`secret_reference`) instead of `plaintext`; we did not test it.
- **Custom provider `base_url`:** Unity Gateway sends requests to this URL as it is and adds no path. Give the full endpoint, for example `https://api.example.com/v1/chat/completions`.
- **MCP connection:** create a schema-level `HTTP` connection. Do not set `is_mcp_connection` (schema-level connections reject it). Set `auth_scheme = "bearer"` for bearer auth, or every plan shows a diff.
- **Key and URL changes:** gateway replicas do not get `api_key` and `base_url` together. Each replica can take more than 2 minutes to get each value, in any order. During that time, a request can go to the new URL with the old key, or to the old URL with the new key. One good response does not show that all replicas have the change. To move a provider to a new URL, create a new provider service and point the model service to it. Never point a provider service that holds a real key at a URL you do not trust, even for a test. To test, use a provider service that only ever holds a dummy key.

## Budgets

Budgets are account-level objects: they need an account-level provider (`host = https://accounts.cloud.databricks.com` on AWS, `https://accounts.azuredatabricks.net` on Azure, `https://accounts.gcp.databricks.com` on GCP, plus `account_id`) and an account admin identity. [`budgets/budgets.tf`](budgets/budgets.tf) has two examples:

- a shared monthly budget that sends an email;
- a monthly cap for each user (`ALERT_CONFIGURATION_SCOPE_TYPE_PER_USER`) that blocks usage (`BLOCK_USAGE`), with a higher limit for one group (`principal_overrides`).

AI Gateway budgets also count usage from Databricks products that use the gateway, such as Genie.

---

## Bring an existing setup under Terraform

### Grants: no import, but the first plan must match today

`databricks_grants` needs no import: the first apply replaces the access list. On that first apply the plan shows only "create". It does not show which grants it will remove. So:

1. Read today's grants for the schema and every model: `databricks grants get schema system.ai` and `databricks grants get model_service system.ai.<model>`.
2. Write `local.model_groups` so that it gives the same groups to the same models.
3. Run `terraform plan -out=tf.plan` and compare each planned access list with step 1. The only expected addition is the break-glass group.
4. Apply that saved plan: `terraform apply tf.plan`. No user loses or gets access.

If `account users` has `EXECUTE` on the schema, move it down first, without a gap: give each model that must stay open `"account users"` in `model_groups`, apply (Terraform creates the per-model grants, then removes `EXECUTE` from the schema), then remove `"account users"` from the models that must be closed in a second pull request.

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
   - replace each numeric `principal_id` in `principal_overrides` with a data source, for example `data.databricks_group.genai_power_users.id`.
4. `terraform plan` must show `1 to import, 0 to add, 0 to change, 0 to destroy`. Apply, then remove the import block.

In our test, this round trip showed 0 changes, also after we removed the read-only fields.

**Option B: the Terraform exporter**

The exporter is a command in the provider binary (after `terraform init`, under `.terraform/providers/registry.terraform.io/databricks/databricks/<version>/<os_arch>/`):

```bash
export DATABRICKS_HOST=https://accounts.azuredatabricks.net
export DATABRICKS_ACCOUNT_ID=<account-id>
export DATABRICKS_CLIENT_ID=<sp-application-id>
export DATABRICKS_CLIENT_SECRET=<sp-secret>

./terraform-provider-databricks exporter -skip-interactive \
  -listing billing -services billing -native-import -directory budgets_export
```

- It writes `databricks_budget` and `databricks_budget_policy` resources, import blocks and a provider block.
- It has no name filter for budgets: it exports **every** budget and serverless budget policy in the account, which can take a long time on a large account. Delete what you do not want Terraform to manage.
- Clean the output as in step 3 of option A.

If you recreate a budget in Terraform instead of importing it, delete the old budget afterwards. Two `BLOCK_USAGE` budgets both block.

---

## Keep it safe

- **Never apply a plan with unexpected destroys.** A destroy of `databricks_grants` revokes every grant in it. In CI, save the plan (`terraform plan -out`), fail the job if `terraform show -json` lists a `delete` for `databricks_grants`, `databricks_grant` or `databricks_budget`, and apply only that saved plan. `prevent_destroy` is a second safeguard.
- **Keep one `databricks_grants` resource keyed by model.** If you move a model from one resource to another, the destroy fails (`permissions ... have to be []`). Use a `moved` block or `terraform state rm`.
- **To retire a model**, remove it from `model_groups` and run `terraform state rm 'databricks_grants.system_ai_models["<model>"]'` on purpose.
- **Stop changes by hand:** keep `MANAGE` on `system.ai` for the Terraform service principal only, and run `terraform plan -detailed-exitcode` every day to find drift (exit code 2).

## What we tested

On a test metastore with 21 `system.ai` model services, provider 1.136.0 and 1.137.0, October 2026:

| Behaviour | Result |
| --- | --- |
| `databricks_grants` on `model_service` | No import needed. Removes principals that are not listed, including `account users`. Reverts grants added by hand. |
| Revoke on one model | Takes effect in about 1–2 minutes. Other models are not affected. |
| Re-grant | Takes effect in about 50 seconds. |
| Call without access | HTTP 404 `'system.ai.<model>' does not exist`, not a permission error. |
| Terraform identity without `MANAGE` | Fails: `User does not have MANAGE on MODEL_SERVICE`. |
| ABAC GRANT policy, `ai.model_creator = anthropic` | Anthropic model opened after about 1.5 minutes. Other model stayed closed. Not shown in `databricks grants get`. |
| Budget import with import block and generated config | 0 changes. |
| `databricks_ai_gateway_model_provider_service` (custom), `_model_service` (routes to it), `_mcp_service` (schema-level HTTP connection) | Created in seconds. Real calls through the provider service and the model service returned 200; MCP `tools/list` returned 200. |
| `databricks_grants` on `model_provider_service`, `model_service`, `mcp_service` | Without `EXECUTE`: 404 `does not exist` (provider and model service), 403 `Not authorized to invoke MCP service` (MCP). Grant: MCP opened at once, the others in about 1.5 minutes. Revoke: MCP closed at once, the others in about 35 seconds. |
| Change of `api_key` / `base_url` on a provider service | Not applied together. Some requests used the new URL with the old key, others the old URL with the new key, for up to about 2.5 minutes. |

Not tested: budget enforcement (`BLOCK_USAGE`), exporter output for budgets, ABAC with a group (we used a service principal), provider types other than custom, `secret_reference`, fallback routing and `rate_limits`.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Insufficient grant blocks` | A model with no grants | Keep the break-glass group on every model |
| `User does not have MANAGE on MODEL_SERVICE` | The Terraform identity has no `MANAGE` | Grant `MANAGE` on `system.ai` |
| Plan wants to destroy many grants | The model list came from a data source that returned empty | Use a fixed list |
| Revoke on one model has no effect | `account users` has `EXECUTE` on the schema | Remove `EXECUTE` from the schema grant |
| `'system.ai.<model>' does not exist` | No `EXECUTE`, or the change is still propagating | Wait 1–2 minutes, then check the grants and policies |
| User has access, but `grants get` shows nothing | Access comes from an ABAC policy | `databricks policies list-policies SCHEMA system.ai` |
| MCP call returns JSON-RPC error `-32007 Not authorized to invoke MCP service` | No `EXECUTE` on the MCP service | Grant `EXECUTE` with `databricks_grants` and `mcp_service` |
| Provider error `Path must be of form /serving-endpoints/...` or another upstream 404 | `base_url` is a base path, not the full endpoint | Set the full endpoint URL |
| `Setting is_mcp_connection is not supported on schema-level connections` | `is_mcp_connection` set on the connection | Remove it; the MCP service does that job |
| `databricks_connection` shows a change on every plan | `auth_scheme` is missing from `options` | Add `auth_scheme = "bearer"` |

---

## Further Reading

- [Unity Gateway documentation](https://docs.databricks.com/aws/en/ai-gateway/)
- [Govern access to models with grant policies](https://docs.databricks.com/aws/en/ai-gateway/govern-access-to-models-with-grant-policies)
- [Unity Gateway budgets](https://docs.databricks.com/aws/en/ai-gateway/budgets)
- [Unity Gateway rate limits](https://docs.databricks.com/aws/en/ai-gateway/rate-limits)
- [Query model provider services](https://docs.databricks.com/aws/en/ai-gateway/query-model-provider-services) and [register an external MCP server](https://docs.databricks.com/aws/en/ai-gateway/register-mcp-service)
- [Terraform exporter guide](https://registry.terraform.io/providers/databricks/databricks/latest/docs/guides/experimental-exporter)
- [Terraform import blocks with generated configuration](https://developer.hashicorp.com/terraform/language/import/generating-configuration)
