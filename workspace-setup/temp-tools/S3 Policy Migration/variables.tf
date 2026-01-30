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

variable "workspace_host" {
  description = "Databricks workspace URL"
  type        = string
}

# Optional override to directly supply bucket ARNs when discovery from the
# workspace fails (e.g., due to permissions or empty responses).
variable "bucket_arns_override" {
  description = "Map of identifiers to S3 bucket ARNs to use instead of discovered external locations (optional)"
  type        = map(string)
  default     = {}
}

variable "debug" {
  description = "When true, emit diagnostic outputs to help troubleshoot discovery and filtering."
  type        = bool
  default     = false
}
