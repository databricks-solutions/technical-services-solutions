# Who can use which system.ai model service.
#
# List EVERY model service in system.ai with a fixed list. Do not build it from the
# databricks_ai_gateway_model_services data source: its list API can return an empty result,
# and an empty map makes Terraform revoke every grant.
# A model that is NOT in this list gets no direct grant. When account users lose EXECUTE on the
# schema (below), it closes for everyone, also for the break-glass group, and the plan shows only
# creates. This example lists 6 models: add all models of your metastore before you apply.
# The check block at the end warns about models that are not in the list.
# A model with [] is locked: only the break-glass group keeps access
# (databricks_grants needs at least one grant).
locals {
  model_groups = {
    "claude-haiku-4-5"  = ["data-scientists", "ml-engineers"]
    "claude-sonnet-4-6" = ["data-scientists", "ml-engineers"]
    "claude-opus-4-7"   = ["genai-power-users"]
    "gemma-3-12b"       = [] # locked
    "gpt-oss-120b"      = [] # locked
    "llama-4-maverick"  = [] # locked
  }
}

# One authoritative access list per model. Principals that are not listed (including the
# default "account users") are removed on apply, and grants added by hand are reverted.
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

# If account users have EXECUTE on the schema (directly or through ALL_PRIVILEGES), every model
# inherits it and a revoke on one model has no effect. This resource removes that EXECUTE.
# It sets the schema privileges of account users to EXACTLY the variable below: it also adds
# missing privileges and removes others, so copy today's list. The privileges differ per metastore.
# Never keep MANAGE or ALL_PRIVILEGES: with them, every user can grant themselves EXECUTE.
# It is applied after the per-model grants, so no allowed group loses access in between.
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

# Warns, and does not block, when system.ai has a model that is not in model_groups, for example
# a new model from Databricks. The data source is used only here: if it returns an empty result,
# the check passes and no grant changes.
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
