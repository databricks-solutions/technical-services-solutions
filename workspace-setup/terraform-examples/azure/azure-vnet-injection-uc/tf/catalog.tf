module "uc_catalog" {
  source = "../modules/uc-catalog"

  providers = {
    azurerm    = azurerm
    databricks = databricks
  }

  access_connector_name   = "${var.workspace_name}-uc-mi"
  resource_group          = azurerm_resource_group.this.name
  location                = azurerm_resource_group.this.location
  storage_account_name    = var.uc_storage_name
  storage_container_name  = "${var.workspace_name}-uc-container"
  storage_credential_name = "${var.workspace_name}-uc-cred"
  external_location_name  = "${var.workspace_name}-ext-loc"
  catalog_name            = var.workspace_name
  tags                    = var.tags
}
