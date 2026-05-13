output "workspace_id" {
  description = "Resolved workspace ID, either newly created or existing"
  value       = local.workspace_id
}

output "ncc_id" {
  description = "Network Connectivity Configuration ID"
  value       = databricks_mws_network_connectivity_config.ncc.network_connectivity_config_id
}

output "ncc_name" {
  description = "Network Connectivity Configuration name"
  value       = databricks_mws_network_connectivity_config.ncc.name
}

output "private_endpoint_rule_id" {
  description = "Private endpoint rule ID if created"
  value       = var.create_private_endpoint_rule ? databricks_mws_ncc_private_endpoint_rule.aws_private_endpoint[0].rule_id : null
}

output "created_workspace_url" {
  description = "Workspace URL when a new workspace is created"
  value       = var.create_new_workspace ? databricks_mws_workspaces.serverless_workspace[0].workspace_url : null
}

output "metastore_id" {
  description = "Resolved metastore ID"
  value       = local.resolved_metastore_id
}
output "s3_private_endpoint_rule_id" {
  value = databricks_mws_ncc_private_endpoint_rule.s3.rule_id
}

output "s3_vpc_endpoint_id" {
  value = databricks_mws_ncc_private_endpoint_rule.s3.vpc_endpoint_id
}

output "s3_private_endpoint_connection_state" {
  value = databricks_mws_ncc_private_endpoint_rule.s3.connection_state
}

output "s3_private_endpoint_enabled" {
  value = databricks_mws_ncc_private_endpoint_rule.s3.enabled
}

output "storage_credential_name" {
  value = databricks_storage_credential.external.name
}

output "external_location_name" {
  value = databricks_external_location.this.name
}

output "external_location_url" {
  value = databricks_external_location.this.url
}

output "uc_iam_role_arn" {
  value = aws_iam_role.external_data_access.arn
}