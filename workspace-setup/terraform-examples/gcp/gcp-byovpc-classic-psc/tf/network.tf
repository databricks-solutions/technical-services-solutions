data "google_client_openid_userinfo" "me" {}
data "google_client_config" "current" {}

# Random suffix for unique resource naming
resource "random_string" "databricks_suffix" {
  special = false
  upper   = false
  length  = 3
}

locals {
  use_existing_vpc = var.vpc_name != ""
  network_project  = var.vpc_network_project_id != "" ? var.vpc_network_project_id : var.google_project_name
}

######################################################
# Optional existing VPC / node subnet
######################################################
data "google_compute_network" "existing_vpc" {
  count   = local.use_existing_vpc ? 1 : 0
  name    = var.vpc_name
  project = local.network_project
}

data "google_compute_subnetwork" "existing_node_subnet" {
  count   = local.use_existing_vpc ? 1 : 0
  name    = var.subnet_name
  region  = var.google_region
  project = local.network_project
}

######################################################
# VPC, Subnets, Router, NAT
#
# New-VPC mode creates the VPC and node subnet.
# Existing-VPC mode reuses them and still creates a dedicated
# PSC subnet (plus optional Cloud NAT) in that VPC.
######################################################
resource "google_compute_network" "databricks_vpc" {
  count                   = local.use_existing_vpc ? 0 : 1
  name                    = "dbx-psc-vpc-${random_string.databricks_suffix.result}"
  project                 = var.google_project_name
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "node_subnet" {
  count                    = local.use_existing_vpc ? 0 : 1
  name                     = "dbx-node-subnet-${random_string.databricks_suffix.result}"
  project                  = var.google_project_name
  region                   = var.google_region
  network                  = google_compute_network.databricks_vpc[0].id
  ip_cidr_range            = var.subnet_cidr
  private_ip_google_access = true
}

locals {
  vpc_id           = local.use_existing_vpc ? data.google_compute_network.existing_vpc[0].id : google_compute_network.databricks_vpc[0].id
  vpc_name         = local.use_existing_vpc ? data.google_compute_network.existing_vpc[0].name : google_compute_network.databricks_vpc[0].name
  node_subnet_name = local.use_existing_vpc ? data.google_compute_subnetwork.existing_node_subnet[0].name : google_compute_subnetwork.node_subnet[0].name
}

resource "google_compute_subnetwork" "psc_subnet" {
  name                     = "dbx-psc-subnet-${random_string.databricks_suffix.result}"
  project                  = local.network_project
  region                   = var.google_region
  network                  = local.vpc_id
  ip_cidr_range            = var.psc_subnet_cidr
  private_ip_google_access = true

  lifecycle {
    precondition {
      condition     = var.vpc_name == "" || var.subnet_name != ""
      error_message = "Set subnet_name when reusing an existing VPC (vpc_name)."
    }
  }
}

resource "google_compute_router" "databricks_router" {
  count   = var.create_nat_gateway ? 1 : 0
  name    = "dbx-router-${random_string.databricks_suffix.result}"
  project = local.network_project
  region  = var.google_region
  network = local.vpc_id
}

resource "google_compute_router_nat" "databricks_nat" {
  count                              = var.create_nat_gateway ? 1 : 0
  name                               = "dbx-nat-${random_string.databricks_suffix.result}"
  project                            = local.network_project
  router                             = google_compute_router.databricks_router[0].name
  region                             = var.google_region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}
