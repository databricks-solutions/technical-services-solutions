# =============================================================================
# azure.tf - Workspace resource group
# =============================================================================
# Creates or references the Azure resource group for the workspace and its Private
# Link resources (workspace, access connectors, storage, private endpoints, private
# DNS zones). Other files use local.dp_rg_name, etc. Networking can live in a
# different group: see vnet_resource_group_name in network.tf.
# =============================================================================

# Workspace resource group. Only created when create_resource_group is true.
resource "azurerm_resource_group" "dp_rg" {
  count    = var.create_resource_group ? 1 : 0
  name     = var.resource_group_name
  location = var.location
  tags     = local.tags
}

# Reference to the existing resource group when create_resource_group is false.
data "azurerm_resource_group" "dp_rg" {
  count = var.create_resource_group ? 0 : 1
  name  = var.resource_group_name
}
