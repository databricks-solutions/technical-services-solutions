variable "root_bucket_name" { type = string }

variable "cross_account_role_arn" {
  type        = string
  description = "ARN of the Databricks cross-account IAM role"
}

variable "kms_key_arn" {
  type        = string
  description = "ARN of the KMS key for S3 encryption"
}
