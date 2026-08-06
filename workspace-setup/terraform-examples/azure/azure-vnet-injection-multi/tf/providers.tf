provider "azurerm" {
  subscription_id = var.azure_subscription_id
  tenant_id       = var.tenant_id
  features {}
}

provider "databricks" {
  alias           = "accounts"
  host            = "https://accounts.azuredatabricks.net"
  account_id      = var.databricks_account_id
  azure_tenant_id = var.tenant_id
}