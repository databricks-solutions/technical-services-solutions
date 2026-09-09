provider "azurerm" {
  subscription_id = var.azure_subscription_id
  tenant_id       = var.tenant_id
  features {}
}

# Databricks auth is auto-detected: Azure CLI (`az login`) for interactive use, or a
# service principal via ARM_CLIENT_ID / ARM_CLIENT_SECRET / ARM_TENANT_ID (or the
# DATABRICKS_AZURE_* equivalents) for CI/CD. `auth_type` is intentionally not pinned
# so both work; set ARM_* env vars for automation.
provider "databricks" {
  host            = azurerm_databricks_workspace.this.workspace_url
  azure_tenant_id = var.tenant_id
}

provider "databricks" {
  alias           = "accounts"
  host            = "https://accounts.azuredatabricks.net"
  account_id      = var.databricks_account_id
  azure_tenant_id = var.tenant_id
}