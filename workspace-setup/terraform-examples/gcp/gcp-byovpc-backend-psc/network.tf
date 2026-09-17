data "google_client_openid_userinfo" "me" {}
data "google_client_config" "current" {}

# Random suffix for unique Databricks-side resource naming
resource "random_string" "databricks_suffix" {
  special = false
  upper   = false
  length  = 3
}

######################################################
# Reference Existing (BYO / Shared) VPC and Subnets
# Nothing here is created — the VPC and subnets are
# referenced as-is and left untouched on destroy.
######################################################
data "google_compute_network" "existing_vpc" {
  name    = var.vpc_name
  project = var.vpc_network_project_id
}

# Subnet used by the Databricks GCE nodes.
data "google_compute_subnetwork" "node_subnet" {
  name    = var.subnet_name
  region  = var.google_region
  project = var.vpc_network_project_id
}

# Subnet in which the two backend PSC endpoint internal IPs are allocated.
data "google_compute_subnetwork" "psc_subnet" {
  name    = var.psc_subnet_name
  region  = var.google_region
  project = var.vpc_network_project_id
}
