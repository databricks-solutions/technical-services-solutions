######################################################
# Outputs
######################################################
output "workspace_url" {
  value       = databricks_mws_workspaces.databricks_workspace.workspace_url
  description = "URL of the created Databricks workspace."
}

output "workspace_id" {
  value       = databricks_mws_workspaces.databricks_workspace.workspace_id
  description = "Databricks workspace ID."
}

output "vpc_name" {
  value       = google_compute_network.databricks_vpc.name
  description = "Name of the created VPC network."
}

output "node_subnet_name" {
  value       = google_compute_subnetwork.node_subnet.name
  description = "Name of the created Databricks node subnet."
}

output "psc_subnet_name" {
  value       = google_compute_subnetwork.psc_subnet.name
  description = "Name of the created PSC endpoint subnet."
}

output "rest_api_psc_status" {
  value       = google_compute_forwarding_rule.rest_api_psc_ep.psc_connection_status
  description = "PSC connection status of the backend REST API endpoint (expected: ACCEPTED)."
}

output "relay_psc_status" {
  value       = google_compute_forwarding_rule.relay_psc_ep.psc_connection_status
  description = "PSC connection status of the backend SCC relay endpoint (expected: ACCEPTED)."
}

output "rest_api_endpoint_ip" {
  value       = google_compute_address.rest_api_ip.address
  description = "Internal IP of the backend REST API PSC endpoint."
}

output "relay_endpoint_ip" {
  value       = google_compute_address.relay_ip.address
  description = "Internal IP of the backend SCC relay PSC endpoint."
}

output "metastore_assignment" {
  value       = var.metastore_id != "" ? databricks_metastore_assignment.this[0].metastore_id : "If this is your first workspace in the region, Databricks will have auto-created a metastore. If you have 'Automatically assign new workspaces to this metastore' enabled, metastore will be auto-assigned. Else you will have a workspace with no metastore assigned"
  description = "The metastore ID assigned to the workspace (only when metastore_id is provided)."
}
