# =============================================================================
# providers.tf - Azure and Databricks provider configuration
# =============================================================================
# Azure RM: subscription via var.az_subscription; auth via Azure CLI or ARM_* env.
# Databricks account: for NCC (serverless private endpoints); requires account_id
# and Azure auth (same tenant). See variables for databricks_account_id.
# =============================================================================

# Authenticate using Azure CLI: https://learn.microsoft.com/en-us/cli/azure/authenticate-azure-cli
# Run `az login` for interactive login, or use environment variables for service principal:
# export ARM_CLIENT_ID=CLIENT_ID
# export ARM_CLIENT_SECRET=CLIENT_SECRET
# export ARM_TENANT_ID=TENANT_ID
# export ARM_SUBSCRIPTION_ID=SUBSCRIPTION_ID

provider "azurerm" {
  features {}
  subscription_id = var.az_subscription
}

provider "azapi" {
}

# Account-level provider for NCC (network connectivity config) and private endpoint rules.
# Auth: Azure CLI (az login) or Azure service principal (ARM_* or DATABRICKS_AZURE_*).
provider "databricks" {
  alias           = "account"
  host            = "https://accounts.azuredatabricks.net"
  account_id      = var.databricks_account_id
  azure_tenant_id = data.azurerm_client_config.current.tenant_id
  # NCC private-endpoint rule creation can sit on the account API longer than the default (~65s idle).
  http_timeout_seconds = 300
}

# Workspace-level provider for Unity Catalog objects (storage credential, external location, catalog)
# and the optional cluster. The workspace is reachable over the public network (no front-end Private Link).
provider "databricks" {
  alias           = "workspace"
  host            = "https://${azurerm_databricks_workspace.dp_workspace.workspace_url}"
  azure_tenant_id = data.azurerm_client_config.current.tenant_id
}
