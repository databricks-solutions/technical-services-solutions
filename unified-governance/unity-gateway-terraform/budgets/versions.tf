terraform {
  required_version = ">= 1.5"
  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = ">= 1.136.0"
    }
  }
  # Use a separate remote backend from the grants project.
}

# Budgets are account-level objects: authenticate as an ACCOUNT ADMIN service principal.
provider "databricks" {
  host       = var.account_host
  account_id = var.account_id
}

variable "account_host" {
  description = "https://accounts.cloud.databricks.com (AWS), https://accounts.azuredatabricks.net (Azure) or https://accounts.gcp.databricks.com (GCP)"
  type        = string
}

variable "account_id" {
  type = string
}
