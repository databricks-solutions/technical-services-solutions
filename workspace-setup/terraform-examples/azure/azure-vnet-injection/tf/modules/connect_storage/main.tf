locals {
  access_connector_name = "${var.storage_account_name}_access_connector"
  storage_credential_name = "${var.storage_account_name}_storage_credential"
}

// Create a storage account to be used by catalog
resource "azurerm_storage_account" "this" {
  count = var.create_storage_account ? 1 : 0
  name                     = var.storage_account_name
  resource_group_name      = var.resource_group
  location                 = var.location
  tags                     = var.tags
  account_tier             = "Standard"
  account_replication_type = "LRS"
  is_hns_enabled           = true
}

data "azurerm_storage_account" "this" {
  count = var.create_storage_account ? 0 : 1
  name = var.storage_account_name
  resource_group_name = var.resource_group
}

resource "azurerm_databricks_access_connector" "this" {
  name                = local.access_connector_name
  resource_group_name = var.resource_group
  location            = var.location
  identity {
    type = "SystemAssigned"
  }
}

// Assign the Storage Blob Data Contributor role to managed identity to allow unity catalog to access the storage
resource "azurerm_role_assignment" "this" {
  scope                = var.create_storage_account ? azurerm_storage_account.this[0].id : data.azurerm_storage_account.this[0].id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_databricks_access_connector.this.identity[0].principal_id
}

resource "databricks_storage_credential" "this" {
  name = local.storage_credential_name
  azure_managed_identity {
    access_connector_id = azurerm_databricks_access_connector.this.id
  }
  comment = "Managed identity credential managed by TF"
  depends_on = [
    azurerm_role_assignment.this
  ]
}