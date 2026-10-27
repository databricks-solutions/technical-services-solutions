# =============================================================================
# outputs.tf - Output values after deployment
# =============================================================================
# Exposes workspace URL/ID for login and key Azure resource identifiers for
# automation, peering, or integration with other Terraform modules.
# =============================================================================

# =============================================================================
# Databricks Workspace Outputs
# =============================================================================

output "workspace_id" {
  description = "ID of the Databricks workspace"
  value       = azurerm_databricks_workspace.dp_workspace.workspace_id
}

output "workspace_url" {
  description = "URL of the Databricks workspace (format: adb-{workspaceId}.{random}.azuredatabricks.net)"
  value       = "https://${azurerm_databricks_workspace.dp_workspace.workspace_url}/"
}

# =============================================================================
# Resource Group Outputs
# =============================================================================

output "resource_group_name" {
  description = "Name of the data plane resource group"
  value       = local.dp_rg_name
}

output "resource_group_id" {
  description = "ID of the data plane resource group"
  value       = local.dp_rg_id
}

# =============================================================================
# Network Outputs
# =============================================================================

output "vnet_name" {
  description = "Name of the data plane virtual network"
  value       = azurerm_virtual_network.dp_vnet.name
}

output "vnet_id" {
  description = "ID of the data plane virtual network"
  value       = azurerm_virtual_network.dp_vnet.id
}

output "subnet_public_id" {
  description = "ID of the public subnet (Databricks public cluster nodes)"
  value       = azurerm_subnet.dp_public.id
}

output "subnet_private_id" {
  description = "ID of the private subnet (Databricks private cluster nodes)"
  value       = azurerm_subnet.dp_private.id
}

output "subnet_privatelink_id" {
  description = "ID of the Private Link subnet (control plane and DBFS private endpoints)"
  value       = azurerm_subnet.dp_plsubnet.id
}

# =============================================================================
# Serverless NCC Outputs
# =============================================================================

output "ncc_id" {
  description = "Network Connectivity Config ID (for serverless private endpoints)"
  value       = databricks_mws_network_connectivity_config.ncc.network_connectivity_config_id
}

# =============================================================================
# Unity Catalog Outputs
# =============================================================================

output "metastore_id" {
  description = "ID of the Unity Catalog metastore assigned to the workspace (null when none is assigned by this template)"
  value       = local.assign_metastore ? local.metastore_id : null
}

output "catalog_name" {
  description = "Name of the user-defined Unity Catalog catalog (null when new_catalog is false)"
  value       = one(databricks_catalog.uc[*].name)
}

output "external_location_name" {
  description = "Name of the Unity Catalog external location (null when new_catalog is false)"
  value       = one(databricks_external_location.uc[*].name)
}

output "external_location_url" {
  description = "URL of the Unity Catalog external location (null when new_catalog is false)"
  value       = one(databricks_external_location.uc[*].url)
}

output "storage_credential_name" {
  description = "Name of the Unity Catalog storage credential (null when new_catalog is false)"
  value       = one(databricks_storage_credential.uc[*].name)
}

output "uc_storage_account_name" {
  description = "Name of the storage account backing the Unity Catalog catalog (null when new_catalog is false)"
  value       = one(azurerm_storage_account.uc[*].name)
}

# =============================================================================
# Cluster Outputs
# =============================================================================

output "cluster_id" {
  description = "ID of the UC-compatible single-node cluster (null when create_cluster is false)"
  value       = one(databricks_cluster.uc_single_node[*].id)
}
