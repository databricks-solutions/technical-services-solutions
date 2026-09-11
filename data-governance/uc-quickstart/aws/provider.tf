provider "aws" {
  region = var.region
}

provider "databricks" {
  alias = "dev_workspace"
  host = var.dev_databricks_host
}

provider "databricks" {
  alias = "prod_workspace"
  host = var.prod_databricks_host
}

provider "databricks" {
  alias = "account"
  host = "https://accounts.cloud.databricks.com"
  account_id = var.databricks_account_id
}