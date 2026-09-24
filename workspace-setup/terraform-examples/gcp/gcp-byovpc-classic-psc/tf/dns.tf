######################################################
# Private DNS for Backend PSC
#
# The classic compute plane must resolve the Databricks
# control-plane hostnames to the PRIVATE PSC endpoint IPs
# (not the public IPs). We create a private Cloud DNS zone
# for gcp.databricks.com in the VPC host project and add the
# backend A records:
#
#   <workspace_id>.gcp.databricks.com      -> REST API endpoint IP
#   dp-<workspace_id>.gcp.databricks.com   -> REST API endpoint IP
#   tunnel.<region>.gcp.databricks.com     -> SCC relay endpoint IP
#
# The per-region "tunnel" record is shared by all workspaces
# in the region; the per-workspace records are unique.
######################################################

locals {
  # Extracts e.g. "8296020533331897.7" from the workspace URL.
  workspace_id = regex("[0-9]+\\.[0-9]+", databricks_mws_workspaces.databricks_workspace.workspace_url)
}

resource "google_dns_managed_zone" "databricks_private_zone" {
  count       = var.create_private_dns ? 1 : 0
  project     = var.google_project_name
  name        = var.private_zone_name
  dns_name    = var.dns_name
  description = "Databricks backend PSC private DNS zone"
  visibility  = "private"

  private_visibility_config {
    networks {
      network_url = google_compute_network.databricks_vpc.id
    }
  }
}

# <workspace_id>.gcp.databricks.com -> REST API endpoint IP
resource "google_dns_record_set" "workspace_url" {
  count        = var.create_private_dns ? 1 : 0
  project      = var.google_project_name
  managed_zone = google_dns_managed_zone.databricks_private_zone[0].name
  name         = "${local.workspace_id}.${var.dns_name}"
  type         = "A"
  ttl          = 300
  rrdatas      = [google_compute_address.rest_api_ip.address]
}

# dp-<workspace_id>.gcp.databricks.com -> REST API endpoint IP
resource "google_dns_record_set" "workspace_dp" {
  count        = var.create_private_dns ? 1 : 0
  project      = var.google_project_name
  managed_zone = google_dns_managed_zone.databricks_private_zone[0].name
  name         = "dp-${local.workspace_id}.${var.dns_name}"
  type         = "A"
  ttl          = 300
  rrdatas      = [google_compute_address.rest_api_ip.address]
}

# tunnel.<region>.gcp.databricks.com -> SCC relay endpoint IP
resource "google_dns_record_set" "relay_tunnel" {
  count        = var.create_private_dns ? 1 : 0
  project      = var.google_project_name
  managed_zone = google_dns_managed_zone.databricks_private_zone[0].name
  name         = "tunnel.${var.google_region}.${var.dns_name}"
  type         = "A"
  ttl          = 300
  rrdatas      = [google_compute_address.relay_ip.address]
}
