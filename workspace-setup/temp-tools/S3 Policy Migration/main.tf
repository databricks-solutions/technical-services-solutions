# --------------- Providers ---------------

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 4.16"
    }
    databricks = {
      source  = "databricks/databricks"
      version = ">= 1.16.0"
    }
  }
}

data "aws_caller_identity" "current" {}

provider "aws" {
  region = var.aws_region
}

# Account-level provider for service principal auth
provider "databricks" {
  alias         = "mws"
  host          = "https://accounts.cloud.databricks.com"
  account_id    = var.databricks_account_id
  client_id     = var.client_id
  client_secret = var.client_secret
}

# Workspace-level provider reusing the same account credentials
provider "databricks" {
  alias         = "workspace"
  host          = var.workspace_host
  client_id     = var.client_id
  client_secret = var.client_secret
}

# Module for workspace storage credentials
module "workspace_credentials" {
  source = "./modules/workspace_credentials"

  workspace_host = var.workspace_host
  client_id      = var.client_id
  client_secret  = var.client_secret
}

module "storage_bucket_policies" {
  source = "./modules/storage_bucket_policies"

  bucket_arns = module.workspace_credentials.external_location_bucket_arns
}

# Outputs
output "external_location_bucket_arns" {
  description = "External location bucket ARNs for workspace"
  value       = module.workspace_credentials.external_location_bucket_arns
}

output "storage_bucket_policies" {
  description = "S3 bucket policies associated with storage credentials"
  value       = module.storage_bucket_policies.bucket_policies
}

output "debug_external_location_names" {
  description = "Diagnostic list of external location names returned by the workspace"
  value       = module.workspace_credentials.debug_external_location_names
}

output "debug_external_location_urls" {
  description = "Diagnostic mapping of external location names to their storage URLs"
  value       = module.workspace_credentials.debug_external_location_urls
}

output "debug_external_location_bucket_arns_full" {
  description = "Diagnostic mapping of external locations to derived bucket ARNs prior to filtering"
  value       = module.workspace_credentials.debug_external_location_bucket_arns_full
}

output "debug_metastore_summary" {
  description = "Diagnostic summary of the workspace's current metastore assignment"
  value       = module.workspace_credentials.debug_metastore_summary
}

output "debug_input_bucket_arns" {
  description = "Diagnostic view of the bucket ARNs passed into the storage bucket policy module"
  value       = module.storage_bucket_policies.debug_input_bucket_arns
}

output "debug_bucket_name_map" {
  description = "Diagnostic mapping of identifiers to resolved bucket names"
  value       = module.storage_bucket_policies.debug_bucket_name_map
}
