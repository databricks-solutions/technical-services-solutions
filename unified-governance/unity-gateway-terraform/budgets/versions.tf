terraform {
  required_version = ">= 1.5"
  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.136" # 1.136 or later 1.x
      # In your own repo, commit the .terraform.lock.hcl that terraform init creates, so that every
      # run uses the same provider version and checksums.
    }
  }
  # Use a separate remote backend from the services project.
}

# Budgets are account-level objects: authenticate as an ACCOUNT ADMIN service principal. Account
# admin is a very powerful role: use this identity only for this project, in its own pipeline,
# with workload identity federation (OIDC) instead of a long-lived client secret.
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
