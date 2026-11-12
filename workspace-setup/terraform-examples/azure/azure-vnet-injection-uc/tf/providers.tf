# Current Azure client config. The tenant is taken from the logged-in identity (az login or ARM_* variables),
# so no tenant ID input is needed. Set ARM_TENANT_ID if the default tenant of your CLI session is not the right one.
data "azurerm_client_config" "current" {
}

provider "azurerm" {
  subscription_id = var.azure_subscription_id
  features {}
}

# auth_type not pinned so Azure CLI and service-principal (ARM_*) auth both work.
provider "databricks" {
  host            = azurerm_databricks_workspace.this.workspace_url
  azure_tenant_id = data.azurerm_client_config.current.tenant_id
}

provider "databricks" {
  alias           = "accounts"
  host            = "https://accounts.azuredatabricks.net"
  account_id      = var.databricks_account_id
  azure_tenant_id = data.azurerm_client_config.current.tenant_id
}
