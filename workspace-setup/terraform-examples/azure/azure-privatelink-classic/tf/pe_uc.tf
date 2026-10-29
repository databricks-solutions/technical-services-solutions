# =============================================================================
# pe_uc.tf - Private endpoints for the Unity Catalog storage account
# =============================================================================
# Creates two private endpoints in the Private Link subnet for the catalog storage
# account (dfs and blob), registered in the same private DNS zones as DBFS
# (dns_zones.tf). Classic compute in the VNet resolves the storage account to these
# private IPs; public network access is disabled on it (unity_catalog.tf).
# =============================================================================

resource "azurerm_private_endpoint" "dp_ucpe_dfs" {
  count               = var.new_catalog ? 1 : 0
  name                = "pep-${local.prefix}-dp-uc-dfs"
  location            = local.dp_rg_location
  resource_group_name = local.dp_rg_name
  subnet_id           = azurerm_subnet.dp_plsubnet.id
  tags                = local.tags

  private_service_connection {
    name                           = "ple-${local.prefix}-dp-uc-dfs"
    private_connection_resource_id = azurerm_storage_account.uc[0].id
    is_manual_connection           = false
    subresource_names              = ["dfs"]
  }

  private_dns_zone_group {
    name                 = "pdnsgrp-${local.prefix}-dp-uc-dfs"
    private_dns_zone_ids = [azurerm_private_dns_zone.dbfs_dfs.id]
  }
}

resource "azurerm_private_endpoint" "dp_ucpe_blob" {
  count               = var.new_catalog ? 1 : 0
  name                = "pep-${local.prefix}-dp-uc-blob"
  location            = local.dp_rg_location
  resource_group_name = local.dp_rg_name
  subnet_id           = azurerm_subnet.dp_plsubnet.id
  tags                = local.tags

  private_service_connection {
    name                           = "ple-${local.prefix}-dp-uc-blob"
    private_connection_resource_id = azurerm_storage_account.uc[0].id
    is_manual_connection           = false
    subresource_names              = ["blob"]
  }

  private_dns_zone_group {
    name                 = "pdnsgrp-${local.prefix}-dp-uc-blob"
    private_dns_zone_ids = [azurerm_private_dns_zone.dbfs_blob.id]
  }
}
