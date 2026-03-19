# =============================================================================
# pe_dbfs.tf - Private endpoints for DBFS (workspace root storage)
# =============================================================================
# Creates two private endpoints in the Private Link subnet for the workspace
# root storage account: one for dfs (Data Lake Storage Gen2) and one for blob.
# Ensures DBFS traffic stays on the private link when used from the VNet.
# =============================================================================

# Private endpoint for the DFS (Data Lake Storage Gen2) subresource of the root storage account.
resource "azurerm_private_endpoint" "dp_dbfspe_dfs" {
  name                = "pep-${local.prefix}-dp-dbfs-dfs"
  location            = local.dp_rg_location
  resource_group_name = local.dp_rg_name
  subnet_id           = azurerm_subnet.dp_plsubnet.id

  private_service_connection {
    name                           = "ple-${local.prefix}-dp-dbfs-dfs"
    private_connection_resource_id = join("", [azurerm_databricks_workspace.dp_workspace.managed_resource_group_id, "/providers/Microsoft.Storage/storageAccounts/${local.dbfsname}"])
    is_manual_connection           = false
    subresource_names              = ["dfs"]
  }

  private_dns_zone_group {
    name                 = "pdnsgrp-${local.prefix}-dp-dfs"
    private_dns_zone_ids = [azurerm_private_dns_zone.dbfs_dfs.id]
  }
}

# Private endpoint for the Blob subresource of the root storage account.
resource "azurerm_private_endpoint" "dp_dbfspe_blob" {
  name                = "pep-${local.prefix}-dp-dbfs-blob"
  location            = local.dp_rg_location
  resource_group_name = local.dp_rg_name
  subnet_id           = azurerm_subnet.dp_plsubnet.id

  private_service_connection {
    name                           = "ple-${local.prefix}-dp-dbfs-blob"
    private_connection_resource_id = join("", [azurerm_databricks_workspace.dp_workspace.managed_resource_group_id, "/providers/Microsoft.Storage/storageAccounts/${local.dbfsname}"])
    is_manual_connection           = false
    subresource_names              = ["blob"]
  }

  private_dns_zone_group {
    name                 = "pdnsgrp-${local.prefix}-dp-blob"
    private_dns_zone_ids = [azurerm_private_dns_zone.dbfs_blob.id]
  }
}
