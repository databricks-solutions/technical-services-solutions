output "bucket_policies" {
  description = "Map of storage credential identifiers to their corresponding S3 bucket policies"
  value       = local.bucket_policies
}

