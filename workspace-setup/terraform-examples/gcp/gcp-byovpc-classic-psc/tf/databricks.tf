######################################################
# Register the two backend PSC endpoints with Databricks
# (Account console: Security > VPC endpoints)
######################################################

# REST API endpoint registration (rest_api role in the network config)
resource "databricks_mws_vpc_endpoint" "rest_api" {
  depends_on        = [google_compute_forwarding_rule.rest_api_psc_ep]
  provider          = databricks.accounts
  account_id        = var.databricks_account_id
  vpc_endpoint_name = "dbx-backend-rest-${random_string.databricks_suffix.result}"

  gcp_vpc_endpoint_info {
    project_id        = var.google_project_name
    psc_endpoint_name = var.workspace_pe_name
    endpoint_region   = var.google_region
  }
}

# SCC relay endpoint registration (dataplane_relay role in the network config)
resource "databricks_mws_vpc_endpoint" "relay" {
  depends_on        = [google_compute_forwarding_rule.relay_psc_ep]
  provider          = databricks.accounts
  account_id        = var.databricks_account_id
  vpc_endpoint_name = "dbx-backend-relay-${random_string.databricks_suffix.result}"

  gcp_vpc_endpoint_info {
    project_id        = var.google_project_name
    psc_endpoint_name = var.relay_pe_name
    endpoint_region   = var.google_region
  }
}

######################################################
# Private Access Settings
# One PAS object can be shared by multiple workspaces in
# the same region. For a backend-only deployment, public
# access is typically left enabled (front-end/user access
# is not restricted by PSC here).
######################################################
resource "databricks_mws_private_access_settings" "pas" {
  provider                     = databricks.accounts
  private_access_settings_name = "dbx-pas-${random_string.databricks_suffix.result}"
  region                       = var.google_region
  public_access_enabled        = var.public_access_enabled
  private_access_level         = "ACCOUNT"
}

######################################################
# Databricks BYO VPC Network Configuration
# References the existing VPC/subnet and wires in the two
# backend PSC endpoints.
######################################################
resource "databricks_mws_networks" "databricks_network" {
  provider     = databricks.accounts
  account_id   = var.databricks_account_id
  network_name = "dbx-nwt-${random_string.databricks_suffix.result}"

  gcp_network_info {
    network_project_id = var.google_project_name
    vpc_id             = google_compute_network.databricks_vpc.name
    subnet_id          = google_compute_subnetwork.node_subnet.name
    subnet_region      = var.google_region
  }

  vpc_endpoints {
    dataplane_relay = [databricks_mws_vpc_endpoint.relay.vpc_endpoint_id]
    rest_api        = [databricks_mws_vpc_endpoint.rest_api.vpc_endpoint_id]
  }
}

######################################################
# Databricks Workspace (backend PSC)
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

  network_id                 = databricks_mws_networks.databricks_network.network_id
  private_access_settings_id = databricks_mws_private_access_settings.pas.private_access_settings_id
}

######################################################
# Assign Existing Unity Catalog Metastore to Workspace
# Only created when metastore_id is provided.
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

resource "databricks_group_member" "admin_member" {
  provider  = databricks.workspace
  group_id  = data.databricks_group.admins.id
  member_id = databricks_user.admin.id
}
