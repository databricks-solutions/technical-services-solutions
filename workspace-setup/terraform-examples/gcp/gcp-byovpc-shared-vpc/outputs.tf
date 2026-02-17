######################################################
# Outputs
######################################################
output "workspace_url" {
  value = databricks_mws_workspaces.databricks_workspace.workspace_url
}

output "metastore_assignment" {
  value       = var.metastore_id != "" ? databricks_metastore_assignment.this[0].metastore_id : "No metastore ID provided - Databricks will auto-create one for the first workspace in the region, or assign manually for subsequent workspaces"
  description = "The metastore ID assigned to the workspace (only when metastore_id is provided)"
}
