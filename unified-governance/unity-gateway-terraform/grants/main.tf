# One authoritative grant list per model, from local.model_grants in access.tf.
# Principals not listed are removed on apply, and drift is reverted on the next apply.
resource "databricks_grants" "system_ai_models" {
  for_each      = local.model_grants
  model_service = "system.ai.${each.key}"

  dynamic "grant" {
    for_each = length(each.value) > 0 ? each.value : tomap({ (var.break_glass_group) = ["EXECUTE"] })
    content {
      principal  = grant.key
      privileges = grant.value
    }
  }

  # Destroying a databricks_grants resource revokes every grant in it.
  # To retire a model: remove it from access.tf AND run `terraform state rm` on purpose.
  lifecycle {
    prevent_destroy = true
  }
}

# account users on the system.ai schema: keep the listed privileges, never EXECUTE.
resource "databricks_grant" "system_ai_schema_account_users" {
  schema     = "system.ai"
  principal  = "account users"
  privileges = local.account_users_schema_privileges

  depends_on = [databricks_grants.system_ai_models]

  lifecycle {
    prevent_destroy = true # destroy would revoke ALL account users privileges on system.ai
    precondition {
      condition     = !contains(local.account_users_schema_privileges, "EXECUTE")
      error_message = "account users must not have EXECUTE on system.ai: every model inherits it."
    }
  }
}
