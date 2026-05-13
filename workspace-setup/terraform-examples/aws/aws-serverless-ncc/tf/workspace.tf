################################################################################
# 2. Workspace
################################################################################

# Optional lookup of an existing workspace by name (when neither
# create_new_workspace nor existing_workspace_id are set).
data "databricks_mws_workspaces" "existing_by_name" {
  count    = (!var.create_new_workspace && var.existing_workspace_id == null && var.existing_workspace_name != null) ? 1 : 0
  provider = databricks.account
}

# Create a new serverless workspace.
resource "databricks_mws_workspaces" "serverless_workspace" {
  count = var.create_new_workspace ? 1 : 0

  provider       = databricks.account
  account_id     = var.databricks_account_id
  workspace_name = var.workspace_name
  aws_region     = var.region
  compute_mode   = "SERVERLESS"
}

# Resolve workspace_id from the appropriate source:
#   1. If create_new_workspace=true,  use the just-created workspace's ID.
#   2. Else if existing_workspace_id is set, use it directly.
#   3. Else, look up by existing_workspace_name in the by_name data source.
locals {
  resolved_existing_workspace_id = var.existing_workspace_id != null ? var.existing_workspace_id : (
    length(data.databricks_mws_workspaces.existing_by_name) > 0
    ? lookup(data.databricks_mws_workspaces.existing_by_name[0].ids, var.existing_workspace_name, null)
    : null
  )

  workspace_id = var.create_new_workspace ? databricks_mws_workspaces.serverless_workspace[0].workspace_id : local.resolved_existing_workspace_id
}

# Look up the user that should be made workspace admin. Errors at apply time
# if the email isn't a real Databricks account user.
data "databricks_user" "workspace_admin" {
  provider  = databricks.account
  user_name = var.workspace_admin_email
}

# Assign the user as workspace ADMIN. Depends on NCC binding + metastore
# assignment so we don't activate the user before the workspace is fully
# wired up.
resource "databricks_mws_permission_assignment" "workspace_admin" {
  provider     = databricks.account
  workspace_id = local.workspace_id
  principal_id = data.databricks_user.workspace_admin.id
  permissions  = ["ADMIN"]

  depends_on = [
    databricks_mws_ncc_binding.ncc_binding,
    databricks_metastore_assignment.this
  ]
}
