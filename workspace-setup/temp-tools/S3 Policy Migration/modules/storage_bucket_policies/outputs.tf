output "bucket_policies" {
  description = "Map of storage credential identifiers to their corresponding S3 bucket policies"
  value = {
    for name, policy in data.aws_s3_bucket_policy.this :
    name => policy.policy
  }
}

output "bucket_policies_filtered" {
  description = "Filtered subset of bucket policies that include Databricks or network guardrail statements"
  value       = local.bucket_policies_filtered
}

output "debug_input_bucket_arns" {
  description = "Diagnostic view of the bucket ARNs provided to this module"
  value       = var.bucket_arns
}

output "debug_bucket_name_map" {
  description = "Diagnostic mapping of identifiers to resolved bucket names"
  value       = local.bucket_name_map
}
