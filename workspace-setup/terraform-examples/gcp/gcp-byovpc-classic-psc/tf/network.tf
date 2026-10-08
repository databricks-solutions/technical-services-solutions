data "google_client_openid_userinfo" "me" {}
data "google_client_config" "current" {}

# Random suffix for unique resource naming
resource "random_string" "databricks_suffix" {
  special = false
  upper   = false
  length  = 3
}

######################################################
# VPC, Subnets, Router, NAT (created by this module)
#
# - databricks_vpc : custom-mode VPC for the workspace
# - node_subnet    : primary subnet for the Databricks GCE data plane
# - psc_subnet     : subnet holding the two backend PSC endpoint IPs
# - router + NAT   : egress for nodes (which have no public IPs under SCC)
######################################################
resource "google_compute_network" "databricks_vpc" {
  name                    = "dbx-psc-vpc-${random_string.databricks_suffix.result}"
  project                 = var.google_project_name
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "node_subnet" {
  name                     = "dbx-node-subnet-${random_string.databricks_suffix.result}"
  project                  = var.google_project_name
  region                   = var.google_region
  network                  = google_compute_network.databricks_vpc.id
  ip_cidr_range            = var.subnet_cidr
  private_ip_google_access = true
}

resource "google_compute_subnetwork" "psc_subnet" {
  name                     = "dbx-psc-subnet-${random_string.databricks_suffix.result}"
  project                  = var.google_project_name
  region                   = var.google_region
  network                  = google_compute_network.databricks_vpc.id
  ip_cidr_range            = var.psc_subnet_cidr
  private_ip_google_access = true
}

resource "google_compute_router" "databricks_router" {
  count   = var.create_nat_gateway ? 1 : 0
  name    = "dbx-router-${random_string.databricks_suffix.result}"
  project = var.google_project_name
  region  = var.google_region
  network = google_compute_network.databricks_vpc.id
}

resource "google_compute_router_nat" "databricks_nat" {
  count                              = var.create_nat_gateway ? 1 : 0
  name                               = "dbx-nat-${random_string.databricks_suffix.result}"
  project                            = var.google_project_name
  router                             = google_compute_router.databricks_router[0].name
  region                             = var.google_region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}
