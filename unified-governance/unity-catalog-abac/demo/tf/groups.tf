data "databricks_current_user" "me" {
}

resource "databricks_group" "group" {
  provider = databricks.accounts
  display_name = "abac_demo_group_1"
  force = true
}

resource "databricks_group_member" "group_member" {
  provider = databricks.accounts
  group_id = databricks_group.group.id
  member_id = data.databricks_current_user.me.id
}

locals {
  workspace_id  = var.cloud_provider == "azure" ? regex("adb-(\\d+)\\.", var.workspace_url)[0] : data.databricks_mws_workspaces.all[0].ids["${var.workspace_name}"]
}

resource "databricks_mws_permission_assignment" "workspace_access" {
  provider = databricks.accounts
  workspace_id = local.workspace_id
  principal_id = databricks_group.group.id
  permissions  = ["USER"]
}

data "databricks_mws_workspaces" "all" {
    count = var.cloud_provider == "azure" ? 0 : 1
    provider = databricks.accounts
}