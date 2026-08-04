output "key_arn" {
  description = "ARN of the KMS key"
  value       = aws_kms_key.databricks_cmk.arn
  depends_on  = [time_sleep.wait_for_kms_policy]
}

output "key_id" {
  description = "ID of the KMS key"
  value       = aws_kms_key.databricks_cmk.key_id
  depends_on  = [time_sleep.wait_for_kms_policy]
}

