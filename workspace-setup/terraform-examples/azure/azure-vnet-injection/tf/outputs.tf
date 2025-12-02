# =============================================================================
# Databricks Workspace Outputs
# =============================================================================

output "databricks_workspace_id" {
  description = "ID of the Databricks workspace"
  value = azurerm_databricks_workspace.this.id
}

output "workspace_url" {
  description = "URL of the Databricks workspace"
  value = "https://${azurerm_databricks_workspace.this.workspace_url}/"
}

# =============================================================================
# Network Outputs
# =============================================================================

output "nat_gateway_public_ip" {
  description = "Public IP of the NAT Gateway"
  value       = azurerm_public_ip.this.ip_address
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
  description = "ID of the NAT Gateway"
  value       = azurerm_nat_gateway.this.id
}

output "security_group_id" {
  description = "ID of the security group used for the workspace"
  value       = azurerm_network_security_group.this.id
}

# =============================================================================
# Other Azure Resources Outputs
# =============================================================================


output "managed_resource_group_id" {
  description = "ID of the managed resource group"
  value       = azurerm_databricks_workspace.this.managed_resource_group_id
}

