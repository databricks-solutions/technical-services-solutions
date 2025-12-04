output "bucket_policies" {
  description = "Map of storage credential identifiers to their corresponding S3 bucket policies"
  value = {
    for name, policy in data.aws_s3_bucket_policy.this :
    name => policy.policy
  }
}

output "debug_input_bucket_arns" {
  description = "Diagnostic map of bucket ARNs received by this module"
  value       = var.bucket_arns
}

output "debug_bucket_name_map" {
  description = "Diagnostic view of how bucket ARNs are translated into bucket names"
  value       = local.bucket_name_map
}
