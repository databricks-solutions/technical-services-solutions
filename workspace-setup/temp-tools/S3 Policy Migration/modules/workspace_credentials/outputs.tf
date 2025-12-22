# Output the bucket ARNs backing each external location
output "external_location_bucket_arns" {
  description = "External location bucket ARNs for the workspace"
  value = {
    for name, arn in local.external_location_bucket_arns :
    name => arn
    if arn != null
  }
}

output "debug_external_location_names" {
  description = "Diagnostic list of all external location names discovered in the workspace"
  value       = local.external_location_names
}

output "debug_external_location_urls" {
  description = "Diagnostic mapping of external location names to their storage URLs"
  value       = local.external_location_urls
}

output "debug_external_location_bucket_arns_full" {
  description = "Diagnostic mapping of external locations to derived bucket ARNs (including non-S3 locations as null)"
  value       = local.external_location_bucket_arns
}

output "debug_metastore_summary" {
  description = "Diagnostic view of the current workspace metastore assignment"
  value       = data.databricks_current_metastore.this
}

