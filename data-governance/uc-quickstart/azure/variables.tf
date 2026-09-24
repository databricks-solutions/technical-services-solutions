variable "azure_tenant_id" {
    type = string
    description = "Azure tenant ID"
}

variable "databricks_account_id" {
    type = string
    description = "Databricks account ID"
}

variable "dev_workspace_host" {
    type = string
    description = "Databricks workspace host for dev environment"
}

variable "prod_workspace_host" {
    type = string
    description = "Databricks workspace host for prod environment"
}