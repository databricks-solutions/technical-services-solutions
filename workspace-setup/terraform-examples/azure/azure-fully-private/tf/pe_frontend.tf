# =============================================================================
# pe_frontend.tf - Browser authentication private endpoint (front-end Private Link)
# =============================================================================
# Creates the browser_authentication private endpoint used for SSO callbacks
# when users reach the workspace over front-end Private Link. Only created when
# var.use_frontend_private_link is true.
#
# Only one browser_authentication endpoint is supported per region per private
# DNS zone; it serves every workspace in that region that uses the zone.
# =============================================================================

resource "azurerm_private_endpoint" "pe_frontend" {
  count               = var.use_frontend_private_link ? 1 : 0
  name                = "pep-${local.prefix}-browser-auth"
  location            = local.dp_rg_location
  resource_group_name = local.dp_rg_name
  subnet_id           = azurerm_subnet.dp_plsubnet.id
  tags                = local.tags

  # Connect to the Databricks workspace for SSO callbacks (browser_authentication).
  private_service_connection {
    name                           = "ple-${local.prefix}-browser-auth"
    private_connection_resource_id = azurerm_databricks_workspace.dp_workspace.id
    is_manual_connection           = false
    subresource_names              = ["browser_authentication"]
  }

  # Auto-register <region>.pl-auth in private DNS (privatelink.azuredatabricks.net).
  private_dns_zone_group {
    name                 = "pdnsgrp-${local.prefix}-dp-browser-auth"
    private_dns_zone_ids = [azurerm_private_dns_zone.control_plane.id]
  }

  # Avoid concurrent private endpoint operations on the same workspace.
  depends_on = [azurerm_private_endpoint.dp_dpcp]
}
