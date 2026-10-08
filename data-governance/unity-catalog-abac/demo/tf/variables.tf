variable "workspace_url" {
  description = "The URL of the Databricks workspace"
  type = string
}

variable "databricks_account_id" {
  description = "The ID of the Databricks account"
  type = string
}

variable "cloud_provider" {
  description = "The cloud provider"
  type = string
  validation {
    condition = contains(["azure", "aws", "gcp"], var.cloud_provider)
    error_message = "Invalid cloud provider. Valid values are azure, aws, gcp."
  }
}

variable "workspace_name" {
  description = "The name of the workspace - required for AWS and GCP workspaces"
  type = string
}

variable "catalog_name" {
  description = "The name of the catalog"
  type = string
}

variable "schema_name" {
  description = "The name of the schema"
  type = string
  default = "abac_demo"
}