# =============================================================================
# pe_backend.tf - Private endpoint for Databricks control plane
# =============================================================================
# Creates a private endpoint in the Private Link subnet for the workspace
# control plane (UI/API). Traffic to the workspace URL goes over Private Link
# when private DNS (privatelink.azuredatabricks.net) is used.
# =============================================================================

resource "azurerm_private_endpoint" "dp_dpcp" {
  name                = "pep-${local.prefix}-dp-dpcp"
  location            = local.dp_rg_location
  resource_group_name = local.dp_rg_name
  subnet_id           = azurerm_subnet.dp_plsubnet.id

  # Connect to the Databricks workspace control plane (databricks_ui_api).
  private_service_connection {
    name                           = "ple-${local.prefix}-dp-dpcp"
    private_connection_resource_id = azurerm_databricks_workspace.dp_workspace.id
    is_manual_connection           = false
    subresource_names              = ["databricks_ui_api"]
  }

  # Auto-register private DNS (privatelink.azuredatabricks.net) for this endpoint.
  private_dns_zone_group {
    name                 = "pdnsgrp-${local.prefix}-dp-dpcp"
    private_dns_zone_ids = [azurerm_private_dns_zone.control_plane.id]
  }
}