provider "azurerm" {
  subscription_id = var.azure_subscription_id
  tenant_id = var.tenant_id
  features {}
}

provider "databricks" {
  host = azurerm_databricks_workspace.this.workspace_url
  azure_tenant_id = var.tenant_id
}

provider "databricks" {
  alias      = "accounts"
  host       = "https://accounts.azuredatabricks.net"
  account_id = var.databricks_account_id
  azure_tenant_id = var.tenant_id
}