output "storage_account_id" {
  description = "ID of the Azure storage account"
  value = var.create_storage_account ? azurerm_storage_account.this[0].id : data.azurerm_storage_account.this[0].id
}

output "storage_account_name" {
  description = "Name of the Azure storage account"
  value = var.create_storage_account ? azurerm_storage_account.this[0].name : data.azurerm_storage_account.this[0].name
}

output "storage_credential_id" {
  description = "ID of the storage credential in Unity Catalog"
  value = databricks_storage_credential.this.id
}