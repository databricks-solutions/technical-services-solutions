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

  # Use discovered external locations when available; allow manual override if
  # discovery returns empty (e.g., due to permissions).
  bucket_arns = length(var.bucket_arns_override) > 0 ? var.bucket_arns_override : module.workspace_credentials.external_location_bucket_arns
}

# Outputs
output "external_location_bucket_arns" {
  description = "External location bucket ARNs for workspace"
  value       = var.debug ? module.workspace_credentials.external_location_bucket_arns : null
}

output "storage_bucket_policies" {
  description = "S3 bucket policies associated with storage credentials"
  value       = var.debug ? module.storage_bucket_policies.bucket_policies : null
}

output "storage_bucket_policies_filtered" {
  description = "Filtered S3 bucket policies containing Databricks-related or network guardrail statements"
  # Only print when there is work to do (non-empty) or when debug is enabled.
  value = (
    var.debug || length(module.storage_bucket_policies.bucket_policies_filtered) > 0
  ) ? module.storage_bucket_policies.bucket_policies_filtered : null
}

output "debug" {
  description = "Diagnostic outputs (set var.debug=true to enable)"
  value = var.debug ? {
    external_location_names            = module.workspace_credentials.debug_external_location_names
    external_location_urls             = module.workspace_credentials.debug_external_location_urls
    external_location_bucket_arns_full = module.workspace_credentials.debug_external_location_bucket_arns_full
    metastore_summary                  = module.workspace_credentials.debug_metastore_summary
    input_bucket_arns                  = module.storage_bucket_policies.debug_input_bucket_arns
    bucket_name_map                    = module.storage_bucket_policies.debug_bucket_name_map
  } : null
}
