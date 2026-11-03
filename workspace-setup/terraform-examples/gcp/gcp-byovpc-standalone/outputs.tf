######################################################
# Outputs
######################################################
output "workspace_url" {
  value = databricks_mws_workspaces.databricks_workspace.workspace_url
}

output "metastore_id" {
  value       = var.metastore_id == "" ? databricks_metastore.this[0].id : var.metastore_id
  description = "Unity Catalog metastore ID assigned to the workspace"
}


