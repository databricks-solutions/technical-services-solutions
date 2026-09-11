variable "aws_account_id" {
  description = "AWS account ID"
  type = string
}

variable "databricks_account_id" {
  description = "Databricks account ID"
  type = string
}

variable "dev_databricks_host" {
  description = "Databricks workspace host for dev environment"
  type = string
}

variable "prod_databricks_host" {
  description = "Databricks workspace host for prod environment"
  type = string
}

variable "region" {
  description = "AWS region"
  type = string
}