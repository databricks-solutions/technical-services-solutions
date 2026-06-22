# =============================================================================
# Databricks Workspace Outputs
# =============================================================================

output "workspace_id" {
  description = "ID of the Databricks workspace"
  value       = databricks_mws_workspaces.this.workspace_id
}

output "workspace_url" {
  description = "URL of the Databricks workspace"
  value       = databricks_mws_workspaces.this.workspace_url
}

output "workspace_name" {
  description = "Name of the Databricks workspace"
  value       = databricks_mws_workspaces.this.workspace_name
}

output "workspace_status" {
  description = "Status of the Databricks workspace"
  value       = databricks_mws_workspaces.this.workspace_status
}

# =============================================================================
# Network Outputs
# =============================================================================

output "vpc_id" {
  description = "ID of the VPC used for the workspace"
  value       = var.vpc_id == "" ? module.vpc[0].vpc_id : var.vpc_id
}

output "private_subnet_ids" {
  description = "IDs of the private subnets"
  value       = var.vpc_id == "" ? module.vpc[0].private_subnets : var.subnet_ids
}

output "public_subnet_ids" {
  description = "IDs of the public subnets (if new VPC was created)"
  value       = var.vpc_id == "" ? module.vpc[0].public_subnets : []
}

output "nat_gateway_ids" {
  description = "IDs of the NAT Gateways (if new VPC was created)"
  value       = var.vpc_id == "" ? module.vpc[0].natgw_ids : []
}

output "security_group_ids" {
  description = "IDs of the security groups used for the workspace"
  value       = length(var.security_group_ids) > 0 ? var.security_group_ids : aws_security_group.databricks[*].id
}

# =============================================================================
# IAM and Storage Outputs
# =============================================================================

output "cross_account_role_arn" {
  description = "ARN of the cross-account IAM role"
  value       = aws_iam_role.cross_account_role.arn
}

output "root_s3_bucket_name" {
  description = "Name of the S3 bucket used for workspace root storage"
  value       = aws_s3_bucket.root_storage_bucket.bucket
}

output "root_s3_bucket_arn" {
  description = "ARN of the S3 bucket used for workspace root storage"
  value       = aws_s3_bucket.root_storage_bucket.arn
}

# =============================================================================
# Unity Catalog Outputs
# =============================================================================

output "metastore_id" {
  description = "ID of the Unity Catalog metastore"
  value       = var.metastore_id == "" ? databricks_metastore.metastore[0].id : var.metastore_id
}

output "metastore_name" {
  description = "Name of the Unity Catalog metastore"
  value       = var.metastore_id == "" ? databricks_metastore.metastore[0].name : var.metastore_name
}

output "catalog_name" {
  description = "Name of the user-defined Unity Catalog catalog (null when new_catalog is false)"
  value       = one(databricks_catalog.uc_quickstart[*].name)
}

output "external_location_name" {
  description = "Name of the Unity Catalog external location (null when new_catalog is false)"
  value       = one(databricks_external_location.uc_external_location[*].name)
}

output "external_location_url" {
  description = "URL of the Unity Catalog external location (null when new_catalog is false)"
  value       = one(databricks_external_location.uc_external_location[*].url)
}

output "storage_credential_name" {
  description = "Name of the Unity Catalog storage credential (null when new_catalog is false)"
  value       = one(databricks_storage_credential.uc_storage_cred[*].name)
}

# =============================================================================
# Cluster Outputs
# =============================================================================

output "cluster_name" {
  description = "Name of the UC single-node cluster (null when new_cluster is false)"
  value       = one(databricks_cluster.uc_single_node[*].cluster_name)
}

# =============================================================================
# Databricks Account Objects Outputs
# =============================================================================

output "credentials_id" {
  description = "ID of the Databricks credentials configuration"
  value       = databricks_mws_credentials.this.credentials_id
}

output "storage_configuration_id" {
  description = "ID of the Databricks storage configuration"
  value       = databricks_mws_storage_configurations.this.storage_configuration_id
}

output "network_id" {
  description = "ID of the Databricks network configuration"
  value       = databricks_mws_networks.this.network_id
}

