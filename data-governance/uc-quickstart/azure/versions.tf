terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.5"
    }
    databricks = {
      source = "databricks/databricks"
      version = "~> 1.84"
    }
  }
}
