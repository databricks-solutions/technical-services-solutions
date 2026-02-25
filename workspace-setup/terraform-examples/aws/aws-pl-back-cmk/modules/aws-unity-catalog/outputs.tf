output "metastore_bucket_name" {
  description = "Name of the Unity Catalog metastore bucket"
  value       = aws_s3_bucket.metastore.bucket
}

output "metastore_bucket_arn" {
  description = "ARN of the Unity Catalog metastore bucket"
  value       = aws_s3_bucket.metastore.arn
}

output "unity_catalog_role_arn" {
  description = "ARN of the Unity Catalog IAM role (with self-assuming enabled)"
  value       = aws_iam_role.unity_catalog.arn
}

output "unity_catalog_role_id" {
  description = "ID of the Unity Catalog IAM role"
  value       = aws_iam_role.unity_catalog.id
}

output "unity_catalog_role_name" {
  description = "Name of the Unity Catalog IAM role"
  value       = aws_iam_role.unity_catalog.name
}

output "trust_policy_updated" {
  description = "Indicates trust policy has been updated with self-assuming"
  value       = null_resource.add_self_assume_to_trust_policy.id
  depends_on  = [null_resource.add_self_assume_to_trust_policy]
}

