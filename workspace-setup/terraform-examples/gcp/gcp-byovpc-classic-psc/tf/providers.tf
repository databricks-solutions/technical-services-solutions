# Google provider for the project that holds the VPC, PSC endpoints, DNS, and
# the Databricks data plane (GCE) / DBFS storage.
provider "google" {
  project = var.google_project_name
  region  = var.google_region
}

# Databricks Account-level provider — used to register VPC endpoints, create
# the network / private access settings objects, and create the workspace.
provider "databricks" {
  alias                  = "accounts"
  host                   = "https://accounts.gcp.databricks.com"
  google_service_account = var.google_service_account_email
  account_id             = var.databricks_account_id
}

# Databricks Workspace-level provider — used to manage in-workspace resources
# (admin user, group membership) after the workspace is created.
provider "databricks" {
  alias                  = "workspace"
  host                   = databricks_mws_workspaces.databricks_workspace.workspace_url
  google_service_account = var.google_service_account_email
}
