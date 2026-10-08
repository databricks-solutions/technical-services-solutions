######################################################
# Backend Private Service Connect Endpoints
#
# Backend PSC uses TWO consumer endpoints, both living in
# the PSC subnet:
#
#   1. REST API endpoint  -> workspace service attachment
#      (plproxy-psc-endpoint-all-ports). Data plane -> control
#      plane REST APIs.
#   2. SCC relay endpoint -> relay service attachment
#      (ngrok-psc-endpoint). Data plane -> secure cluster
#      connectivity (SCC) relay.
#
# Each endpoint is an internal IP + a forwarding rule whose
# target is the Databricks-published service attachment URI.
# load_balancing_scheme MUST be "" when target is a service
# attachment.
######################################################

# --- Backend REST API endpoint (workspace / control plane) ---
resource "google_compute_address" "rest_api_ip" {
  name         = "${var.workspace_pe_name}-ip"
  project      = var.google_project_name
  region       = var.google_region
  subnetwork   = google_compute_subnetwork.psc_subnet.id
  address_type = "INTERNAL"
}

resource "google_compute_forwarding_rule" "rest_api_psc_ep" {
  name                  = var.workspace_pe_name
  project               = var.google_project_name
  region                = var.google_region
  network               = google_compute_network.databricks_vpc.id
  ip_address            = google_compute_address.rest_api_ip.id
  target                = var.workspace_service_attachment
  load_balancing_scheme = "" # Required to be "" when target is a service attachment URI.
}

# --- Backend SCC relay endpoint ---
resource "google_compute_address" "relay_ip" {
  name         = "${var.relay_pe_name}-ip"
  project      = var.google_project_name
  region       = var.google_region
  subnetwork   = google_compute_subnetwork.psc_subnet.id
  address_type = "INTERNAL"
}

resource "google_compute_forwarding_rule" "relay_psc_ep" {
  name                  = var.relay_pe_name
  project               = var.google_project_name
  region                = var.google_region
  network               = google_compute_network.databricks_vpc.id
  ip_address            = google_compute_address.relay_ip.id
  target                = var.relay_service_attachment
  load_balancing_scheme = "" # Required to be "" when target is a service attachment URI.
}
