# =============================================================================
# dns_zones.tf - Private DNS zones for control plane and DBFS
# =============================================================================
# Private DNS zones for Private Link: control plane (azuredatabricks.net) and
# DBFS storage (dfs/blob). Each zone is linked to the data plane VNet so
# private endpoints resolve to the correct private IPs.
# =============================================================================

# -----------------------------------------------------------------------------
# Control plane - Databricks UI/API private endpoint
# -----------------------------------------------------------------------------
resource "azurerm_private_dns_zone" "control_plane" {
  name                = "privatelink.azuredatabricks.net"
  resource_group_name = local.dp_rg_name
}

resource "azurerm_private_dns_zone_virtual_network_link" "control_plane" {
  name                  = "lnk-${local.prefix}-dp-control-plane"
  resource_group_name   = local.dp_rg_name
  private_dns_zone_name = azurerm_private_dns_zone.control_plane.name
  virtual_network_id    = azurerm_virtual_network.dp_vnet.id
}

# -----------------------------------------------------------------------------
# DBFS - workspace root storage (dfs and blob) private endpoints
# -----------------------------------------------------------------------------
resource "azurerm_private_dns_zone" "dbfs_dfs" {
  name                = "privatelink.dfs.core.windows.net"
  resource_group_name = local.dp_rg_name
}

resource "azurerm_private_dns_zone" "dbfs_blob" {
  name                = "privatelink.blob.core.windows.net"
  resource_group_name = local.dp_rg_name
}

resource "azurerm_private_dns_zone_virtual_network_link" "dbfs_dfs" {
  name                  = "lnk-${local.prefix}-dp-dbfs-dfs"
  resource_group_name   = local.dp_rg_name
  private_dns_zone_name = azurerm_private_dns_zone.dbfs_dfs.name
  virtual_network_id    = azurerm_virtual_network.dp_vnet.id
}

resource "azurerm_private_dns_zone_virtual_network_link" "dbfs_blob" {
  name                  = "lnk-${local.prefix}-dp-dbfs-blob"
  resource_group_name   = local.dp_rg_name
  private_dns_zone_name = azurerm_private_dns_zone.dbfs_blob.name
  virtual_network_id    = azurerm_virtual_network.dp_vnet.id
}



