# --------------- Providers ---------------

terraform {
  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = ">= 1.16.0"
    }
  }
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

# Outputs
output "debug_external_location_bucket_arns" {
  description = "Debug: external location bucket ARNs for workspace (null when debug=false)"
  value       = var.debug ? module.workspace_credentials.external_location_bucket_arns : null
}

output "s3_bucket_arns_requiring_policy_update" {
  description = "Guidance: S3 bucket ARNs backing external locations. Customers should update these bucket policies."
  value       = distinct(values(module.workspace_credentials.external_location_bucket_arns))
}

output "debug" {
  description = "Diagnostic output (null when debug=false)"
  value = var.debug ? {
    external_location_names            = module.workspace_credentials.debug_external_location_names
    external_location_urls             = module.workspace_credentials.debug_external_location_urls
    external_location_bucket_arns_full = module.workspace_credentials.debug_external_location_bucket_arns_full
    external_location_bucket_arns      = module.workspace_credentials.external_location_bucket_arns
    metastore_summary                  = module.workspace_credentials.debug_metastore_summary
  } : null
}

