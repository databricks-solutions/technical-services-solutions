variable "google_service_account_email" {
  description = "Email of the Google Service Account used by providers"
  type        = string
}
variable "google_project_name" {
  description = "GCP project ID where resources will be created"
  type        = string
}
variable "google_region" {
  description = "GCP region for resources (e.g., us-central1)"
  type        = string
}
variable "databricks_account_id" {
  description = "Databricks Account ID"
  type        = string
}
variable "databricks_account_console_url" {
  description = "Databricks Accounts host URL (e.g., https://accounts.gcp.databricks.com)"
  type        = string
}
variable "databricks_workspace_name" {
  description = "Name for the Databricks workspace"
  type        = string
}
variable "databricks_admin_user" {
  description = "Admin user email to add to the workspace (must exist at Account level)"
  type        = string
}

variable "subnet_cidr" {
  description = "CIDR block for the Databricks subnet"
  type        = string
}


