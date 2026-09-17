terraform {
  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = ">=1.24.0"
    }
    google = {
      source = "hashicorp/google"
    }
    random = {
      source = "hashicorp/random"
    }
  }
}
