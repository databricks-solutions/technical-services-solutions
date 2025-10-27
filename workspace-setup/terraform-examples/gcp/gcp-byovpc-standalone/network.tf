data "google_client_openid_userinfo" "me" {}
data "google_client_config" "current" {}

# Random suffix for unique resource naming
resource "random_string" "databricks_suffix" {
  special = false
  upper   = false
  length  = 3
}

######################################################
# Google VPC, Subnet, Router, NAT
######################################################
resource "google_compute_network" "databricks_vpc" {
  name                    = "databricks-vpc-${random_string.databricks_suffix.result}"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "databricks_subnet" {
  name          = "databricks-subnet-${random_string.databricks_suffix.result}"
  ip_cidr_range = var.subnet_cidr
  region        = var.google_region
  network       = google_compute_network.databricks_vpc.id
}

resource "google_compute_router" "databricks_router" {
  name    = "databricks-router-${random_string.databricks_suffix.result}"
  region  = var.google_region
  network = google_compute_network.databricks_vpc.id
}

resource "google_compute_router_nat" "databricks_nat" {
  name                               = "databricks-nat-${random_string.databricks_suffix.result}"
  router                             = google_compute_router.databricks_router.name
  region                             = var.google_region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}


