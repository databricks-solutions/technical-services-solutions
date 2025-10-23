######################################################
# Databricks BYO VPC Network Configuration
######################################################
resource "databricks_mws_networks" "databricks_network" {
  provider     = databricks.accounts
  account_id   = var.databricks_account_id
  network_name = "dbx-nwt-${random_string.databricks_suffix.result}"

  gcp_network_info {
    network_project_id = var.google_project_name
    vpc_id             = google_compute_network.databricks_vpc.name
    subnet_id          = google_compute_subnetwork.databricks_subnet.name
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


