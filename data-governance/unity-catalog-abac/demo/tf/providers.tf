provider "databricks" {
  host = var.workspace_url
}

locals {
  account_host = var.cloud_provider == "azure" ? "https://accounts.azuredatabricks.net" : (var.cloud_provider == "aws" ? "https://accounts.cloud.databricks.com" : "https://accounts.gcp.databricks.com")
}

provider "databricks" {
  alias      = "accounts"
  host       = local.account_host
  account_id = var.databricks_account_id
  profile = "account"
  auth_type = "databricks-cli"
}