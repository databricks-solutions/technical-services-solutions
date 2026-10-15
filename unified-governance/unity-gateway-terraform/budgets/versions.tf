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
  type    = string
  default = "https://accounts.azuredatabricks.net"
}

variable "account_id" {
  type = string
}
