provider "azurerm" {
  features {}
}

provider "databricks" {
  alias                       = "dev_workspace"
  host                        = var.dev_workspace_host
  azure_tenant_id             = var.azure_tenant_id
}

provider "databricks" {
  alias                       = "prod_workspace"
  host                        = var.prod_workspace_host
  azure_tenant_id             = var.azure_tenant_id
}

provider "databricks" {
  alias               = "account"
  host                = "https://accounts.azuredatabricks.net"
  account_id          = var.databricks_account_id
  azure_tenant_id     = var.azure_tenant_id
}