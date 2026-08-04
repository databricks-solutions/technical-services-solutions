terraform {
  required_version = "~> 1.3"


  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.50"
    }
    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.84"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

