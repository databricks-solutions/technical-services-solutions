variable "google_service_account_email" {
  description = "Email of the Google Service Account used by providers"
  type        = string
}
variable "google_project_name" {
  description = "GCP project ID where the Databricks workspace will be created (service project)"
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
variable "databricks_workspace_name" {
  description = "Name for the Databricks workspace"
  type        = string
}
variable "databricks_admin_user" {
  description = "Admin user email to add to the workspace (must exist at Account level)"
  type        = string
}

variable "vpc_network_project_id" {
  description = "GCP project ID where the shared/existing VPC resides (host project). Set to the same value as google_project_name if the VPC is in the same project."
  type        = string
}

variable "vpc_name" {
  description = "Name of the existing VPC network to use"
  type        = string
}

variable "subnet_name" {
  description = "Name of the existing subnet within the VPC to use"
  type        = string
}

variable "metastore_id" {
  description = "Existing Unity Catalog metastore ID. If empty, no metastore assignment is made (Databricks auto-creates one for the first workspace in a region). If provided, the existing metastore is assigned to the workspace."
  type        = string
  default     = ""
}
