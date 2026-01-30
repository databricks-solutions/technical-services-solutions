variable "workspace_host" {
  description = "Databricks workspace host URL"
  type        = string
}

variable "client_id" {
  description = "Databricks client ID"
  type        = string
  sensitive   = true
}

variable "client_secret" {
  description = "Databricks client secret"
  type        = string
  sensitive   = true
}
