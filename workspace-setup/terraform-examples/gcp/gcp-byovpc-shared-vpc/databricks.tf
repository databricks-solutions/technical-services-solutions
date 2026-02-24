######################################################
# Databricks BYO VPC Network Configuration
# Uses an existing shared/external VPC and subnet
######################################################
resource "databricks_mws_networks" "databricks_network" {
  provider     = databricks.accounts
  account_id   = var.databricks_account_id
  network_name = "dbx-nwt-${random_string.databricks_suffix.result}"

  gcp_network_info {
    network_project_id = var.vpc_network_project_id
    vpc_id             = data.google_compute_network.existing_vpc.name
    subnet_id          = data.google_compute_subnetwork.existing_subnet.name
    subnet_region      = var.google_region
  }
}

######################################################
# Databricks Workspace
######################################################
resource "databricks_mws_workspaces" "databricks_workspace" {
  provider       = databricks.accounts
  account_id     = var.databricks_account_id
  workspace_name = var.databricks_workspace_name
  location       = var.google_region

  cloud_resource_container {
    gcp {
      project_id = var.google_project_name
    }
  }

  network_id = databricks_mws_networks.databricks_network.network_id
}

######################################################
# Assign Existing Unity Catalog Metastore to Workspace
# Only created when metastore_id is provided
######################################################
resource "databricks_metastore_assignment" "this" {
  count        = var.metastore_id != "" ? 1 : 0
  provider     = databricks.accounts
  depends_on   = [databricks_mws_workspaces.databricks_workspace]
  workspace_id = databricks_mws_workspaces.databricks_workspace.workspace_id
  metastore_id = var.metastore_id
}

######################################################
# Add Admin User
######################################################
data "databricks_group" "admins" {
  depends_on   = [databricks_mws_workspaces.databricks_workspace]
  provider     = databricks.workspace
  display_name = "admins"
}

resource "databricks_user" "admin" {
  depends_on = [databricks_mws_workspaces.databricks_workspace]
  provider   = databricks.workspace
  user_name  = var.databricks_admin_user
}
