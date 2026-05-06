# =============================================================================
# main.tf - Shared locals and data sources
# =============================================================================
# Defines locals used across all modules: prefix (from resource_prefix),
# dbfsname (root storage account name), optional tags (from var.tags only), and RG name/id/location.
# Resource group itself is in azure.tf.
#
# Naming: All Azure resources use the pattern <abbreviation>-${local.prefix}-dp[-suffix]
# per Microsoft CAF: https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ready/azure-best-practices/resource-abbreviations
# (e.g. rg=resource group, vnet=virtual network, pip=public IP, ng=NAT gateway, nsg=NSG, snet=subnet, dbw=Databricks workspace, pep=private endpoint).
# =============================================================================

# Current Azure client config (tenant, subscription, etc.) for reference.
data "azurerm_client_config" "current" {
}

locals {
  # Prefix for Azure resource names (VNet, NSG, subnets). From var.resource_prefix.
  prefix = var.resource_prefix
  # DBFS root storage account name. Azure allows 3-24 chars, lowercase alphanumeric only.
  # Keep only [a-z0-9] from resource_prefix, then take first 20 chars after "dbfs".
  dbfsname = "dbfs${substr(join("", regexall("[a-z0-9]", lower(var.resource_prefix))), 0, 20)}"
  # Tags only when set in var.tags.
  tags = var.tags
  # Resource group: use created RG or existing one (name, id, location).
  # When using an existing RG, location must come from the data source only.
  dp_rg_name     = var.create_data_plane_resource_group ? azurerm_resource_group.dp_rg[0].name : data.azurerm_resource_group.dp_rg[0].name
  dp_rg_id       = var.create_data_plane_resource_group ? azurerm_resource_group.dp_rg[0].id : data.azurerm_resource_group.dp_rg[0].id
  dp_rg_location = var.create_data_plane_resource_group ? azurerm_resource_group.dp_rg[0].location : data.azurerm_resource_group.dp_rg[0].location
}
