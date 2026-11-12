# Workspace resource group: created when create_resource_group is true, otherwise looked up.
resource "azurerm_resource_group" "this" {
  count    = var.create_resource_group ? 1 : 0
  name     = var.resource_group_name
  location = var.location
  tags     = var.tags
}

data "azurerm_resource_group" "this" {
  count = var.create_resource_group ? 0 : 1
  name  = var.resource_group_name
}

locals {
  # When reusing a resource group, its region drives the workspace and every regional resource.
  resource_group_name     = var.create_resource_group ? azurerm_resource_group.this[0].name : data.azurerm_resource_group.this[0].name
  resource_group_id       = var.create_resource_group ? azurerm_resource_group.this[0].id : data.azurerm_resource_group.this[0].id
  resource_group_location = var.create_resource_group ? azurerm_resource_group.this[0].location : data.azurerm_resource_group.this[0].location
}

locals {
  # Prefix for Azure resource names, following the Azure CAF pattern <abbreviation>-<prefix>[-suffix]:
  # https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ready/azure-best-practices/resource-abbreviations
  prefix = var.resource_prefix
  # Databricks workspace name and managed resource group: explicit values, or derived from resource_prefix.
  workspace_name              = var.workspace_name != "" ? var.workspace_name : "dbw-${var.resource_prefix}"
  managed_resource_group_name = var.managed_resource_group_name != "" ? var.managed_resource_group_name : "mrg-dbw-${var.resource_prefix}"
  # DBFS root storage account name. Azure allows 3-24 chars, lowercase alphanumeric only.
  # Keep only [a-z0-9] from resource_prefix, then take first 20 chars after "dbfs".
  dbfsname = var.root_storage_name != "" ? var.root_storage_name : "dbfs${substr(join("", regexall("[a-z0-9]", lower(var.resource_prefix))), 0, 20)}"
}
