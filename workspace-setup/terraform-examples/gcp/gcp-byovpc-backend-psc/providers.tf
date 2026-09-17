# Google provider for the service (consumer) project — where the Databricks
# data plane (GCE) and DBFS storage live.
provider "google" {
  project = var.google_project_name
  region  = var.google_region
}

# Google provider aliased to the VPC host project. PSC endpoints and the
# private DNS zone are created here. For a same-project (non-shared) VPC,
# set vpc_network_project_id equal to google_project_name and this points
# at the same project.
provider "google" {
  alias   = "vpc_host"
  project = var.vpc_network_project_id
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
