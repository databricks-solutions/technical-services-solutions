# =============================================================================
# azure.tf - Data plane resource group
# =============================================================================
# Creates or references the Azure resource group for data plane resources (VNet,
# workspace, NAT, private endpoints). Other modules use local.dp_rg_name, etc.
# =============================================================================

# Data plane resource group. Only created when create_data_plane_resource_group is true.
resource "azurerm_resource_group" "dp_rg" {
  count    = var.create_data_plane_resource_group ? 1 : 0
  name     = "rg-${local.prefix}-dp"
  location = var.location
  tags     = local.tags
}

# Reference to existing resource group when create_data_plane_resource_group is false.
data "azurerm_resource_group" "dp_rg" {
  count = var.create_data_plane_resource_group ? 0 : 1
  name  = var.existing_data_plane_resource_group_name
}
