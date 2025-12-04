# ---------------- Databricks Account ----------------

variable "databricks_account_id" {
  description = "Databricks account id"
  type        = string
  sensitive   = true
}

variable "client_id" {
  description = "Databricks client id"
  type        = string
  sensitive   = true
}

variable "client_secret" {
  description = "Databricks client secret"
  type        = string
  sensitive   = true
}

variable "aws_region" {
  description = "AWS region to use for S3 API calls"
  type        = string
  default     = "us-east-1"
}

variable "workspace_host" {
  description = "Databricks workspace URL"
  type        = string
}
