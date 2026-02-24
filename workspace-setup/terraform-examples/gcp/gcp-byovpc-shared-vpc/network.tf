data "google_client_openid_userinfo" "me" {}
data "google_client_config" "current" {}

# Random suffix for unique resource naming
resource "random_string" "databricks_suffix" {
  special = false
  upper   = false
  length  = 3
}

######################################################
# Reference Existing Shared / External VPC and Subnet
######################################################
data "google_compute_network" "existing_vpc" {
  name    = var.vpc_name
  project = var.vpc_network_project_id
}

data "google_compute_subnetwork" "existing_subnet" {
  name    = var.subnet_name
  region  = var.google_region
  project = var.vpc_network_project_id
}
