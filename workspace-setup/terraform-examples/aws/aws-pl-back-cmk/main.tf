locals {
  name = "${var.project}-${var.region}"

  # Determine which networking resources to use
  vpc_id            = var.create_new_vpc ? module.network[0].vpc_id : var.existing_vpc_id
  subnet_ids        = var.create_new_vpc ? module.network[0].subnet_ids : var.existing_subnet_ids
  vpce_workspace_id = var.create_new_vpc ? module.network[0].vpce_workspace_id : aws_vpc_endpoint.existing_vpc_workspace[0].id
  vpce_scc_id       = var.create_new_vpc ? module.network[0].vpce_scc_id : aws_vpc_endpoint.existing_vpc_scc[0].id

  # Determine workspace security group (avoid circular dependency by checking after creation)
  workspace_sg_id = (
    var.create_new_vpc ?
    module.network[0].workspace_sg_id :
    (var.existing_security_group_id != "" ?
      var.existing_security_group_id :
      aws_security_group.existing_vpc_workspace[0].id
    )
  )

  # Determine which CMK to use
  kms_key_arn = var.create_new_cmk ? module.cmk[0].key_arn : var.existing_cmk_arn
}

# ==================== NETWORK MODULE (Optional) ====================
module "network" {
  count                  = var.create_new_vpc ? 1 : 0
  source                 = "./modules/aws-network"
  project                = var.project
  region                 = var.region
  vpc_cidr               = var.vpc_cidr
  private_subnet_cidrs   = var.private_subnet_cidrs
  pl_service_names       = var.pl_service_names
  enable_extra_endpoints = var.enable_extra_endpoints
}

# ==================== RESOURCES FOR EXISTING VPC ====================
# If using existing VPC, we still need to create VPC endpoints and optionally security group

# Security group for existing VPC (only if not provided)
resource "aws_security_group" "existing_vpc_workspace" {
  count       = !var.create_new_vpc && var.existing_security_group_id == "" ? 1 : 0
  name        = "${var.project}-workspace-sg"
  description = "Databricks workspace SG"
  vpc_id      = var.existing_vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-workspace-sg" }
}

# Security group for VPC endpoints in existing VPC
resource "aws_security_group" "existing_vpc_vpce" {
  count       = !var.create_new_vpc ? 1 : 0
  name        = "${var.project}-vpce-sg"
  description = "Security group for VPC endpoints (PL back-end)"
  vpc_id      = var.existing_vpc_id

  ingress {
    from_port = 443
    to_port   = 443
    protocol  = "tcp"
    security_groups = [
      var.existing_security_group_id != "" ?
      var.existing_security_group_id :
      aws_security_group.existing_vpc_workspace[0].id
    ]
  }

  ingress {
    from_port = 6666
    to_port   = 6666
    protocol  = "tcp"
    security_groups = [
      var.existing_security_group_id != "" ?
      var.existing_security_group_id :
      aws_security_group.existing_vpc_workspace[0].id
    ]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-vpce-sg" }

  depends_on = [aws_security_group.existing_vpc_workspace]
}

# VPC Endpoint for Databricks Workspace REST APIs in existing VPC
resource "aws_vpc_endpoint" "existing_vpc_workspace" {
  count               = !var.create_new_vpc ? 1 : 0
  vpc_id              = var.existing_vpc_id
  service_name        = var.pl_service_names.workspace
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [var.existing_subnet_ids[0]]
  security_group_ids  = [aws_security_group.existing_vpc_vpce[0].id]
  private_dns_enabled = true
  tags                = { Name = "${var.project}-vpce-workspace" }
}

# VPC Endpoint for SCC Relay in existing VPC
resource "aws_vpc_endpoint" "existing_vpc_scc" {
  count               = !var.create_new_vpc ? 1 : 0
  vpc_id              = var.existing_vpc_id
  service_name        = var.pl_service_names.scc
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [var.existing_subnet_ids[length(var.existing_subnet_ids) > 1 ? 1 : 0]]
  security_group_ids  = [aws_security_group.existing_vpc_vpce[0].id]
  private_dns_enabled = true
  tags                = { Name = "${var.project}-vpce-scc" }
}

# ==================== IAM MODULE ====================
module "iam" {
  source      = "./modules/aws-iam"
  project     = var.project
  account_id  = var.databricks_account_id
  external_id = var.databricks_crossaccount_role_external_id
}

# ==================== CMK MODULE (Optional) ====================
module "cmk" {
  count                  = var.create_new_cmk ? 1 : 0
  source                 = "./modules/aws-cmk"
  project_name           = var.project
  cross_account_role_arn = module.iam.cross_account_role_arn
}

# ==================== STORAGE MODULE ====================
module "storage" {
  source                 = "./modules/aws-storage"
  root_bucket_name       = var.root_bucket_name
  cross_account_role_arn = module.iam.cross_account_role_arn
  kms_key_arn            = local.kms_key_arn
}

# ==================== UNITY CATALOG MODULE ====================
module "unity_catalog" {
  source                 = "./modules/aws-unity-catalog"
  prefix                 = var.project
  region                 = var.region
  databricks_account_id  = var.databricks_account_id
  cross_account_role_arn = module.iam.cross_account_role_arn
  kms_key_arn            = local.kms_key_arn
}

# ==================== DATABRICKS ACCOUNT-LEVEL RESOURCES ====================
# Register KMS CMK as an encryption key configuration usable for both Managed Services & Storage
resource "databricks_mws_customer_managed_keys" "cmk" {
  provider   = databricks.mws
  account_id = var.databricks_account_id
  aws_key_info {
    key_arn = local.kms_key_arn
  }
  use_cases = ["MANAGED_SERVICES", "STORAGE"]

  # Ensure KMS key policy is ready before Databricks validates
  depends_on = [module.cmk]
}

# Register the two VPC endpoints (workspace & SCC relay) with Databricks
resource "databricks_mws_vpc_endpoint" "workspace" {
  provider            = databricks.mws
  account_id          = var.databricks_account_id
  vpc_endpoint_name   = "${local.name}-workspace-vpce"
  aws_vpc_endpoint_id = local.vpce_workspace_id
  region              = var.region
}

resource "databricks_mws_vpc_endpoint" "scc" {
  provider            = databricks.mws
  account_id          = var.databricks_account_id
  vpc_endpoint_name   = "${local.name}-scc-vpce"
  aws_vpc_endpoint_id = local.vpce_scc_id
  region              = var.region
}

# Create the customer-managed VPC network configuration with back-end PrivateLink bindings
resource "databricks_mws_networks" "net" {
  provider           = databricks.mws
  account_id         = var.databricks_account_id
  network_name       = "${local.name}-net"
  vpc_id             = local.vpc_id
  subnet_ids         = local.subnet_ids
  security_group_ids = [local.workspace_sg_id]

  # Back-end PrivateLink association (workspace REST + SCC relay)
  vpc_endpoints {
    rest_api        = [databricks_mws_vpc_endpoint.workspace.vpc_endpoint_id]
    dataplane_relay = [databricks_mws_vpc_endpoint.scc.vpc_endpoint_id]
  }
}

# Private Access Settings (PAS) to enforce private connectivity
resource "databricks_mws_private_access_settings" "pas" {
  provider                     = databricks.mws
  private_access_settings_name = "${local.name}-pas"
  region                       = var.region
  public_access_enabled        = true # Set to false after Unity Catalog setup
}

# Wait for IAM propagation
resource "time_sleep" "wait_for_iam" {
  create_duration = "60s"

  depends_on = [module.iam]
}

# Credentials config (cross-account role Databricks will assume)
resource "databricks_mws_credentials" "creds" {
  provider         = databricks.mws
  credentials_name = "${local.name}-creds"
  role_arn         = module.iam.cross_account_role_arn

  depends_on = [time_sleep.wait_for_iam]
}

# Wait for bucket configuration to propagate
resource "time_sleep" "wait_for_bucket" {
  create_duration = "60s"

  depends_on = [module.storage, databricks_mws_credentials.creds]
}

# Storage config (root bucket)
resource "databricks_mws_storage_configurations" "storage" {
  provider                   = databricks.mws
  account_id                 = var.databricks_account_id
  storage_configuration_name = "${local.name}-storage"
  bucket_name                = module.storage.root_bucket

  depends_on = [
    time_sleep.wait_for_bucket
  ]
}

# Wait before workspace creation to ensure all configurations are propagated
resource "time_sleep" "wait_before_workspace" {
  create_duration = "30s"

  depends_on = [
    databricks_mws_credentials.creds,
    databricks_mws_storage_configurations.storage,
    databricks_mws_networks.net
  ]
}

# Finally, create the workspace
resource "databricks_mws_workspaces" "ws" {
  provider        = databricks.mws
  account_id      = var.databricks_account_id
  workspace_name  = "${local.name}-ws"

  aws_region               = var.region
  credentials_id           = databricks_mws_credentials.creds.credentials_id
  storage_configuration_id = databricks_mws_storage_configurations.storage.storage_configuration_id
  network_id               = databricks_mws_networks.net.network_id

  private_access_settings_id = databricks_mws_private_access_settings.pas.private_access_settings_id

  managed_services_customer_managed_key_id = databricks_mws_customer_managed_keys.cmk.customer_managed_key_id
  storage_customer_managed_key_id          = databricks_mws_customer_managed_keys.cmk.customer_managed_key_id

  depends_on = [time_sleep.wait_before_workspace]
}

# ---------- Unity Catalog ----------
# Wait for workspace to be ready
resource "time_sleep" "wait_for_workspace" {
  create_duration = "30s"

  depends_on = [databricks_mws_workspaces.ws]
}

# Create Unity Catalog metastore (account-level)
resource "databricks_metastore" "this" {
  provider      = databricks.mws
  name          = "${local.name}-metastore"
  region        = var.region
  storage_root  = "s3://${module.unity_catalog.metastore_bucket_name}/"
  force_destroy = true

  depends_on = [time_sleep.wait_for_workspace]
}

# Assign metastore to workspace (account-level)
resource "databricks_metastore_assignment" "this" {
  provider     = databricks.mws
  metastore_id = databricks_metastore.this.id
  workspace_id = databricks_mws_workspaces.ws.workspace_id
}

# Wait for metastore assignment
resource "time_sleep" "wait_for_metastore" {
  create_duration = "30s"

  depends_on = [databricks_metastore_assignment.this]
}

# Create storage credential for Unity Catalog (workspace-level)
resource "databricks_storage_credential" "unity_catalog" {
  provider = databricks.workspace
  name     = "${local.name}-unity-catalog-credential"

  aws_iam_role {
    role_arn = module.unity_catalog.unity_catalog_role_arn
  }

  depends_on = [time_sleep.wait_for_metastore]
}

# Wait for IAM and S3 permissions to propagate
# This includes time for the IAM role's self-assuming capability to be ready
resource "time_sleep" "wait_for_storage_credential" {
  create_duration = "60s"

  depends_on = [
    databricks_storage_credential.unity_catalog,
    module.unity_catalog
  ]
  
  # Ensure trust policy update is complete before external location
  triggers = {
    trust_policy_updated = module.unity_catalog.trust_policy_updated
  }
}

# Create external location for Unity Catalog
# The IAM role is updated with self-assuming capability before this runs
resource "databricks_external_location" "unity_catalog" {
  provider        = databricks.workspace
  name            = "${local.name}-unity-catalog-external"
  url             = "s3://${module.unity_catalog.metastore_bucket_name}/"
  credential_name = databricks_storage_credential.unity_catalog.id
  force_destroy   = true

  depends_on = [
    time_sleep.wait_for_storage_credential
  ]
}
