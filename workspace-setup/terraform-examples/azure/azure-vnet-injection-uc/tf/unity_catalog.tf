// Create azure managed identity to be used by Databricks storage credential
resource "azurerm_databricks_access_connector" "db_mi" {
  name                = "${var.workspace_name}-uc-mi"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  identity {
    type = "SystemAssigned"
  }
}

// Create a storage account to be used by catalog
resource "azurerm_storage_account" "db_uc_catalog" {
  name                     = var.uc_storage_name
  resource_group_name      = azurerm_resource_group.this.name
  location                 = azurerm_resource_group.this.location
  tags                     = var.tags
  account_tier             = "Standard"
  account_replication_type = "LRS"
  is_hns_enabled           = true
}

// Create a container in storage account to be used by unity catalog metastore as root storage
resource "azurerm_storage_container" "db_uc_catalog" {
  name                  = "${var.workspace_name}-uc-container"
  storage_account_name  = azurerm_storage_account.db_uc_catalog.name
  container_access_type = "private"
}

// Assign the Storage Blob Data Contributor role to managed identity to allow unity catalog to access the storage
resource "azurerm_role_assignment" "db_mi_data_contributor" {
  scope                = azurerm_storage_account.db_uc_catalog.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_databricks_access_connector.db_mi.identity[0].principal_id
}

// Create Databricks Storage Credential
resource "databricks_storage_credential" "db_uc_storage_cred" {
  name = "${var.workspace_name}-uc-cred"
  azure_managed_identity {
    access_connector_id = azurerm_databricks_access_connector.db_mi.id
  }
  comment = "Managed identity credential managed by TF"
  depends_on = [
    azurerm_role_assignment.db_mi_data_contributor
  ]
}

// Create Databricks External Location
resource "databricks_external_location" "db_ext_loc" {
  name = "${var.workspace_name}-ext-loc"
  url = format("abfss://%s@%s.dfs.core.windows.net",
    azurerm_storage_container.db_uc_catalog.name,
    azurerm_storage_account.db_uc_catalog.name)
  credential_name = databricks_storage_credential.db_uc_storage_cred.id
  comment         = "Managed by TF"
  depends_on = [
    databricks_storage_credential.db_uc_storage_cred,
    azurerm_role_assignment.db_mi_data_contributor
  ]
  force_destroy = false
}

// Create Databricks Catalog
resource "databricks_catalog" "uc_quickstart_sandbox" {
  name = var.workspace_name
  storage_root = format(
    "abfss://%s@%s.dfs.core.windows.net",
    azurerm_storage_container.db_uc_catalog.name,
    azurerm_storage_account.db_uc_catalog.name
  )
  depends_on = [
    databricks_external_location.db_ext_loc
  ]
  force_destroy = false
}
