provider "google" {
  project = var.google_project_name
  region  = var.google_region
}

provider "databricks" {
  alias                  = "accounts"
  host                   = var.databricks_account_console_url
  google_service_account = var.google_service_account_email
}

provider "databricks" {
  alias                  = "workspace"
  host                   = databricks_mws_workspaces.databricks_workspace.workspace_url
  google_service_account = var.google_service_account_email
}


