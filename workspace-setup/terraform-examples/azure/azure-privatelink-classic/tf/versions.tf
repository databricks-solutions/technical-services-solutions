# =============================================================================
# versions.tf - Terraform and provider version constraints
# =============================================================================
# Pins minimum Terraform version and required providers. No provider
# configuration here; see providers.tf for Azure and external (az CLI) setup.
# =============================================================================

terraform {
  required_version = "~> 1.3"

  required_providers {
    # Azure API provider for auto-approving NCC private endpoint connections on storage.
    azapi = {
      source  = "Azure/azapi"
      version = "~> 1.0"
    }
    # Azure RM provider for resource group, VNet, workspace, NAT, private endpoints, DNS.
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 4.0.0, < 5.0"
    }
    # Databricks account-level provider for NCC (serverless private endpoints).
    databricks = {
      source  = "databricks/databricks"
      version = ">= 1.28.0, < 2.0"
    }
    # External data source for current Azure CLI user (Owner tag).
    external = {
      source  = "hashicorp/external"
      version = "~> 2.0"
    }
    # Delay between NCC rule creations so the account API is not overloaded (avoids timeout on second rule).
    time = {
      source  = "hashicorp/time"
      version = "~> 0.9"
    }
  }
}
