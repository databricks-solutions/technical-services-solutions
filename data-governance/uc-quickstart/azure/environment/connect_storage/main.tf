locals {
  access_connector_name = "${var.storage_account_name}_access_connector"
  storage_credential_name = "${var.storage_account_name}_storage_credential"
}


// STORAGE ACCOUNT RESOURCE GROUP
// Existing resource group for the storage account
data "azurerm_resource_group" "storage_account_resource_group" {
  name = var.storage_account_resource_group
}

// STORAGE ACCOUNT
// Create a new storage account if create_storage_account is true, otherwise use the existing storage account
resource "azurerm_storage_account" "this" {
  count = var.create_storage_account ? 1 : 0
  name                     = var.storage_account_name
  resource_group_name      = var.storage_account_resource_group
  location                 = var.location
  tags                     = var.tags
  account_tier             = "Standard"
  account_replication_type = "LRS"
  is_hns_enabled           = true
}

// Use the existing storage account if create_storage_account is false
data "azurerm_storage_account" "this" {
  count = var.create_storage_account ? 0 : 1
  name = var.storage_account_name
  resource_group_name = var.storage_account_resource_group
}

// ACCESS CONNECTOR
// Create a new access connector
resource "azurerm_databricks_access_connector" "this" {
  name                = local.access_connector_name
  resource_group_name = var.storage_account_resource_group
  location            = var.location
  identity {
    type = "SystemAssigned"
  }
  tags = var.tags
}

// ROLE ASSIGNMENTS
// Minimum role assignment to allow Databricks to access the storage account
resource "azurerm_role_assignment" "storage_blob_data_contributor" {
  scope                = var.create_storage_account ? azurerm_storage_account.this[0].id : data.azurerm_storage_account.this[0].id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_databricks_access_connector.this.identity[0].principal_id
}

//Additional role assignments to allow Databricks to access the storage account for file events
resource "azurerm_role_assignment" "storage_account_contributor" {
  count = var.enable_file_events ? 1 : 0
  scope                = var.create_storage_account ? azurerm_storage_account.this[0].id : data.azurerm_storage_account.this[0].id
  role_definition_name = "Storage Account Contributor"
  principal_id         = azurerm_databricks_access_connector.this.identity[0].principal_id
}

resource "azurerm_role_assignment" "storage_queue_data_contributor" {
  count = var.enable_file_events ? 1 : 0
  scope                = var.create_storage_account ? azurerm_storage_account.this[0].id : data.azurerm_storage_account.this[0].id
  role_definition_name = "Storage Queue Data Contributor"
  principal_id         = azurerm_databricks_access_connector.this.identity[0].principal_id
}

resource "azurerm_role_assignment" "eventgrid_eventsubscription_contributor" {
  count = var.enable_file_events ? 1 : 0
  scope                = data.azurerm_resource_group.storage_account_resource_group.id
  role_definition_name = "EventGrid EventSubscription Contributor"
  principal_id         = azurerm_databricks_access_connector.this.identity[0].principal_id
}

resource "azurerm_role_assignment" "eventgrid_data_contributor" {
  count = var.enable_file_events ? 1 : 0
  scope                = data.azurerm_resource_group.storage_account_resource_group.id
  role_definition_name = "EventGrid Data Contributor"
  principal_id         = azurerm_databricks_access_connector.this.identity[0].principal_id
}

// STORAGE CREDENTIAL
// Create a new storage credential in Unity Catalog
resource "databricks_storage_credential" "this" {
  provider = databricks.workspace
  name = local.storage_credential_name
  azure_managed_identity {
    access_connector_id = azurerm_databricks_access_connector.this.id
  }
  comment = "Managed identity credential managed by TF"
  depends_on = [
    azurerm_role_assignment.storage_blob_data_contributor,
    azurerm_role_assignment.storage_account_contributor,
    azurerm_role_assignment.storage_queue_data_contributor,
    azurerm_role_assignment.eventgrid_eventsubscription_contributor
  ]
}