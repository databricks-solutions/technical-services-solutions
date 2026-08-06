# =============================================================================
# Databricks Workspace Outputs
# =============================================================================

output "databricks_workspace_id" {
  description = "IDs of the Databricks workspaces"
  value       = { for k, ws in azurerm_databricks_workspace.this : k => ws.id }
}

output "workspace_url" {
  value = { for k, ws in azurerm_databricks_workspace.this : k => "https://${ws.workspace_url}/" }
}

# =============================================================================
# Network Outputs
# =============================================================================

output "nat_gateway_public_ip" {
  description = "Public IPs of the NAT Gateways"
  value       = { for k, ip in azurerm_public_ip.this : k => ip.ip_address }
}

output "vnet_id" {
  description = "ID of the VNet used for the workspace"
  value       = local.vnet.id
}

output "private_subnet_id" {
  description = "IDs of the private subnets"
  value       = { for k, s in azurerm_subnet.private : k => s.id }
}

output "public_subnet_id" {
  description = "IDs of the public subnets"
  value       = { for k, s in azurerm_subnet.public : k => s.id }
}

output "nat_gateway_id" {
  description = "IDs of the NAT Gateways"
  value       = { for k, nat in azurerm_nat_gateway.this : k => nat.id }
}

output "security_group_id" {
  description = "IDs of the security groups"
  value       = { for k, nsg in azurerm_network_security_group.this : k => nsg.id }
}

# =============================================================================
# Other Azure Resources Outputs
# =============================================================================

output "managed_resource_group_id" {
  description = "Managed resource group IDs"
  value       = { for k, ws in azurerm_databricks_workspace.this : k => ws.managed_resource_group_id }
}