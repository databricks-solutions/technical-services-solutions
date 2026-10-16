# Who can use which system.ai model service.
#
# List EVERY model service in system.ai with a fixed list. Do not build it from the
# databricks_ai_gateway_model_services data source: its list API can return an empty result,
# and an empty map makes Terraform revoke every grant.
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

# If account users have EXECUTE on the schema, every model inherits it and a revoke on one
# model has no effect. This keeps their other schema privileges, without EXECUTE.
# It is applied after the per-model grants, so no allowed group loses access in between.
resource "databricks_grant" "system_ai_schema_account_users" {
  schema     = "system.ai"
  principal  = "account users"
  privileges = ["READ_VOLUME", "SELECT", "USE_SCHEMA"]
  depends_on = [databricks_grants.system_ai_models]

  lifecycle {
    prevent_destroy = true # a destroy revokes all account users privileges on system.ai
  }
}
