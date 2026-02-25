# ==================== WORKSPACE OUTPUTS ====================
output "workspace_url" {
  value       = databricks_mws_workspaces.ws.workspace_url
  description = "Databricks workspace URL"
}

output "workspace_id" {
  value       = databricks_mws_workspaces.ws.workspace_id
  description = "Workspace ID"
}

output "workspace_deployment_name" {
  value       = databricks_mws_workspaces.ws.deployment_name
  description = "Workspace deployment name"
}

# ==================== NETWORKING OUTPUTS ====================
output "vpc_id" {
  value       = local.vpc_id
  description = "VPC ID (created or existing)"
}

output "subnet_ids" {
  value       = local.subnet_ids
  description = "Subnet IDs (created or existing)"
}

output "workspace_security_group_id" {
  value       = local.workspace_sg_id
  description = "Workspace security group ID (created or existing)"
}

output "vpc_endpoint_workspace_id" {
  value       = local.vpce_workspace_id
  description = "VPC endpoint ID for Databricks workspace"
}

output "vpc_endpoint_scc_id" {
  value       = local.vpce_scc_id
  description = "VPC endpoint ID for SCC relay"
}

# ==================== ENCRYPTION OUTPUTS ====================
output "kms_key_arn" {
  value       = local.kms_key_arn
  description = "KMS key ARN (created or existing)"
  sensitive   = false
}

output "customer_managed_key_id" {
  value       = databricks_mws_customer_managed_keys.cmk.customer_managed_key_id
  description = "Databricks customer managed key ID"
}

# ==================== UNITY CATALOG OUTPUTS ====================
output "metastore_id" {
  value       = databricks_metastore.this.id
  description = "Unity Catalog metastore ID"
}

output "metastore_bucket" {
  value       = module.unity_catalog.metastore_bucket_name
  description = "Unity Catalog metastore S3 bucket name"
}

output "unity_catalog_role_arn" {
  value       = module.unity_catalog.unity_catalog_role_arn
  description = "Unity Catalog IAM role ARN"
}

output "unity_catalog_role_name" {
  value       = module.unity_catalog.unity_catalog_role_name
  description = "Unity Catalog IAM role name (for post-deploy self-assume setup)"
}

# ==================== IAM OUTPUTS ====================
output "cross_account_role_arn" {
  value       = module.iam.cross_account_role_arn
  description = "Cross-account IAM role ARN"
}

output "root_bucket_name" {
  value       = module.storage.root_bucket
  description = "Workspace root S3 bucket name"
}

# ==================== CONFIGURATION INFO ====================
output "deployment_mode" {
  value = {
    vpc_created = var.create_new_vpc
    cmk_created = var.create_new_cmk
  }
  description = "Shows whether resources were created (true) or existing resources were used (false)"
}

