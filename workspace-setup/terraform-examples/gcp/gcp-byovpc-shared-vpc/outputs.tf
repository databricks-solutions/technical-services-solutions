######################################################
# Outputs
######################################################
output "workspace_url" {
  value = databricks_mws_workspaces.databricks_workspace.workspace_url
}

output "metastore_assignment" {
  value       = var.metastore_id != "" ? databricks_metastore_assignment.this[0].metastore_id : "If this is your first workspace in the region, Databricks will have auto-created a metastore. If you have 'Automatically assign new workspaces to this metastore' enabled, metastore will be auto-assigned. Else you will have a workspace with no metastore assigned"
  description = "The metastore ID assigned to the workspace (only when metastore_id is provided)"
}
