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
  description = "Diagnostic list of external location names returned by the workspace"
  value       = local.external_location_names
}

output "debug_external_location_urls" {
  description = "Diagnostic map of external location names to their storage URLs"
  value = {
    for name, location in data.databricks_external_location.by_name :
    name => location.url
  }
}

output "debug_external_location_bucket_arns_full" {
  description = "Diagnostic map of external locations to derived bucket ARNs (null when the location is not backed by S3)"
  value       = local.external_location_bucket_arns
}

output "debug_metastore_summary" {
  description = "Diagnostic summary of the workspace's current metastore assignment"
  value       = try(data.databricks_current_metastore.this.metastore_info[0], null)
}

