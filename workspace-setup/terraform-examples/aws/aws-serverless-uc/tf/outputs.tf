# =============================================================================
# Databricks Workspace Outputs
# =============================================================================

output "workspace_id" {
  description = "ID of the Databricks workspace"
  value       = databricks_mws_workspaces.this.workspace_id
}

output "workspace_url" {
  description = "URL of the Databricks workspace"
  value       = databricks_mws_workspaces.this.workspace_url
}

output "workspace_name" {
  description = "Name of the Databricks workspace"
  value       = databricks_mws_workspaces.this.workspace_name
}

output "workspace_status" {
  description = "Status of the Databricks workspace"
  value       = databricks_mws_workspaces.this.workspace_status
}

# =============================================================================
# Unity Catalog Outputs
# =============================================================================

output "metastore_id" {
  description = "ID of the Unity Catalog metastore"
  value       = var.metastore_id == "" ? databricks_metastore.metastore[0].id : var.metastore_id
}

output "metastore_name" {
  description = "Name of the Unity Catalog metastore"
  value       = var.metastore_id == "" ? databricks_metastore.metastore[0].name : var.metastore_name
}

output "catalog_name" {
  description = "Name of the user-defined Unity Catalog catalog (null when new_catalog is false)"
  value       = one(databricks_catalog.uc_quickstart[*].name)
}

output "external_location_name" {
  description = "Name of the Unity Catalog external location (null when new_catalog is false)"
  value       = one(databricks_external_location.uc_external_location[*].name)
}

output "external_location_url" {
  description = "URL of the Unity Catalog external location (null when new_catalog is false)"
  value       = one(databricks_external_location.uc_external_location[*].url)
}

output "storage_credential_name" {
  description = "Name of the Unity Catalog storage credential (null when new_catalog is false)"
  value       = one(databricks_storage_credential.uc_storage_cred[*].name)
}
