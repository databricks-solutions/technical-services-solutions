# =============================================================================
# Databricks Workspace Outputs
# =============================================================================

output "databricks_workspace_id" {
  description = "ID of the Databricks workspace"
  value       = azurerm_databricks_workspace.this.id
}

output "workspace_url" {
  description = "URL of the Databricks workspace"
  value       = "https://${azurerm_databricks_workspace.this.workspace_url}/"
}

output "cluster_id" {
  description = "ID of the UC-compatible single-node cluster (null when create_cluster is false)"
  value       = one(databricks_cluster.uc_single_node[*].id)
}

# =============================================================================
# Network Outputs
# =============================================================================

output "nat_gateway_public_ip" {
  description = "Public IP of the NAT Gateway (null when create_nat_gateway is false)"
  value       = one(azurerm_public_ip.this[*].ip_address)
}

output "vnet_id" {
  description = "ID of the VNet used for the workspace"
  value       = local.vnet.id
}

output "private_subnet_id" {
  description = "ID of the private subnet"
  value       = azurerm_subnet.private.id
}

output "public_subnet_id" {
  description = "ID of the public subnet"
  value       = azurerm_subnet.public.id
}

output "nat_gateway_id" {
  description = "ID of the NAT Gateway (null when create_nat_gateway is false)"
  value       = one(azurerm_nat_gateway.this[*].id)
}

output "security_group_id" {
  description = "ID of the security group used for the workspace"
  value       = azurerm_network_security_group.this.id
}

# =============================================================================
# Other Azure Resources Outputs
# =============================================================================


output "resource_group_name" {
  description = "Name of the workspace resource group"
  value       = local.resource_group_name
}

output "resource_group_id" {
  description = "ID of the workspace resource group"
  value       = local.resource_group_id
}

output "managed_resource_group_id" {
  description = "ID of the managed resource group"
  value       = azurerm_databricks_workspace.this.managed_resource_group_id
}

# =============================================================================
# Unity Catalog Outputs
# =============================================================================

output "metastore_id" {
  description = "ID of the Unity Catalog metastore assigned to the workspace (null when none is assigned by this template)"
  value       = local.assign_metastore ? local.metastore_id : null
}

output "external_location_name" {
  description = "Name of the Unity Catalog external location (null when new_catalog is false)"
  value       = one(databricks_external_location.db_ext_loc[*].name)
}

output "catalog_name" {
  description = "Name of the user-defined Unity Catalog catalog (null when new_catalog is false)"
  value       = one(databricks_catalog.uc_quickstart_sandbox[*].name)
}

output "storage_credential_name" {
  description = "Name of the Unity Catalog storage credential (null when new_catalog is false)"
  value       = one(databricks_storage_credential.db_uc_storage_cred[*].name)
}

output "uc_storage_account_name" {
  description = "Name of the storage account backing the Unity Catalog catalog (null when new_catalog is false)"
  value       = one(azurerm_storage_account.db_uc_catalog[*].name)
}
