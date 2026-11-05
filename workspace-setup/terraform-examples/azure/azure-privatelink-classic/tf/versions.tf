# =============================================================================
# versions.tf - Terraform and provider version constraints
# =============================================================================
# Pins minimum Terraform version and required providers. No provider
# configuration here; see providers.tf for Azure and Databricks setup.
# =============================================================================

terraform {
  required_version = "~> 1.3"

  required_providers {
    # Azure API provider for auto-approving NCC private endpoint connections on storage.
    azapi = {
      source  = "Azure/azapi"
      version = ">= 2.0.0, < 3.0"
    }
    # Azure RM provider for resource group, VNet, workspace, NAT, private endpoints, DNS, UC storage.
    # >= 4.50 for azurerm_storage_container.storage_account_id (management-plane container creation).
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 4.50.0, < 5.0"
    }
    # Databricks provider: account-level (NCC, metastore) and workspace-level (Unity Catalog objects).
    databricks = {
      source  = "databricks/databricks"
      version = ">= 1.84.0, < 2.0"
    }
    # Delay between NCC rule creations so the account API is not overloaded (avoids timeout on second rule).
    time = {
      source  = "hashicorp/time"
      version = "~> 0.9"
    }
  }
}
