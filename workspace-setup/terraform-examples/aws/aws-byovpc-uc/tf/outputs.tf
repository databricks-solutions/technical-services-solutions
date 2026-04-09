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
  value       = module.vpc.vpc_id
}

output "private_subnet_ids" {
  description = "IDs of the private subnets"
  value       = module.vpc.private_subnets
}

output "public_subnet_ids" {
  description = "IDs of the public subnets"
  value       = module.vpc.public_subnets
}

output "nat_gateway_ids" {
  description = "IDs of the NAT Gateways"
  value       = module.vpc.natgw_ids
}

output "security_group_id" {
  description = "ID of the security group used for the workspace"
  value       = length(var.security_group_ids) > 0 ? var.security_group_ids[0] : module.vpc.default_security_group_id
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
  description = "Name of the default Unity Catalog catalog"
  value       = databricks_catalog.uc_quickstart.name
}

output "external_location_name" {
  description = "Name of the Unity Catalog external location"
  value       = databricks_external_location.uc_external_location.name
}

output "external_location_url" {
  description = "URL of the Unity Catalog external location"
  value       = databricks_external_location.uc_external_location.url
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

