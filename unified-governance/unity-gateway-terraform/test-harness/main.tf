# Test harness: prove revoke, re-grant and ABAC behaviour on a TEST metastore you own.
# Two test models are closed to account users; every other model stays open the whole time.
# Run every apply through ./safe_apply.sh (saved plan, refuses any delete).
terraform {
  required_providers {
    databricks = { source = "databricks/databricks", version = ">= 1.136.0" }
  }
}

provider "databricks" { profile = var.profile }

variable "profile" {
  description = "CLI profile of a workspace on a TEST metastore. Never use a customer metastore."
  type        = string
}
variable "test_models" {
  default = ["system.ai.claude-opus-4-5", "system.ai.gemma-3-12b"] # one Anthropic, one not
}
variable "break_glass" {
  description = "Your own user name. Keeps a direct grant on the test models."
  type        = string
}
variable "test_sp_app_id" { type = string }
variable "enable_policy" { default = false }
variable "schema_privileges" {
  type    = list(string)
  default = ["READ_VOLUME", "SELECT", "USE_SCHEMA"]
}

# Every other model: account users keep EXECUTE as a direct grant (same access as before).
resource "databricks_grants" "open_models" {
  for_each      = setsubtract(toset(local.models), var.test_models) # fixed list, no data source
  model_service = each.key
  grant {
    principal  = "account users"
    privileges = ["EXECUTE"]
  }
}

# Test models: only the break-glass principal has a direct grant.
resource "databricks_grants" "test_models" {
  for_each      = toset(var.test_models)
  model_service = each.key
  grant {
    principal  = var.break_glass
    privileges = ["EXECUTE"]
  }
}

# Remove EXECUTE from account users on the schema after the direct grants exist.
resource "databricks_grant" "schema_account_users" {
  schema     = "system.ai"
  principal  = "account users"
  privileges = var.schema_privileges
  depends_on = [databricks_grants.open_models, databricks_grants.test_models]
}

resource "databricks_policy_info" "claude_models" {
  count                 = var.enable_policy ? 1 : 0
  name                  = "test-grant-claude-models"
  on_securable_type     = "SCHEMA"
  on_securable_fullname = "system.ai"
  policy_type           = "POLICY_TYPE_GRANT"
  for_securable_type    = "MODEL_SERVICE"
  to_principals         = [var.test_sp_app_id]
  when_condition        = "has_tag_value('ai.model_creator', 'anthropic')"
  grant = {
    privileges = ["EXECUTE"]
  }
}
