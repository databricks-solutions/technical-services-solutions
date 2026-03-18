// Wait on Credential Due to Race Condition
// https://kb.databricks.com/en_US/terraform/failed-credential-validation-checks-error-with-terraform 
resource "null_resource" "previous" {}

resource "time_sleep" "wait_30_seconds" {
  depends_on = [null_resource.previous]

  create_duration = "30s"
}

resource "databricks_mws_storage_configurations" "this" {
  provider           = databricks.mws
  account_id         = var.databricks_account_id
  storage_configuration_name = "${var.prefix}-storage"
  bucket_name      = aws_s3_bucket.root_storage_bucket.bucket
}

# Backend REST VPC Endpoint Configuration
resource "databricks_mws_vpc_endpoint" "backend_rest" {
  provider            = databricks.mws
  account_id          = var.databricks_account_id
  aws_vpc_endpoint_id = aws_vpc_endpoint.backend_rest.id
  vpc_endpoint_name   = "${var.resource_prefix}-vpce-backend-${var.vpc_id == "" ? module.vpc[0].vpc_id : var.vpc_id}"
  region              = var.region
}

# Backend SCC Relay VPC Endpoint Configuration
resource "databricks_mws_vpc_endpoint" "backend_relay" {
  provider            = databricks.mws
  account_id          = var.databricks_account_id
  aws_vpc_endpoint_id = aws_vpc_endpoint.backend_relay.id
  vpc_endpoint_name   = "${var.resource_prefix}-vpce-relay-${var.vpc_id == "" ? module.vpc[0].vpc_id : var.vpc_id}"
  region              = var.region
}

# Network Configuration
resource "databricks_mws_networks" "this" {
  provider           = databricks.mws
  account_id         = var.databricks_account_id
  network_name       = "${var.prefix}-network"
  security_group_ids = [aws_security_group.sg.id]
  subnet_ids         = length(var.subnet_ids) > 0 ? var.subnet_ids : module.vpc[0].private_subnets
  vpc_id             = var.vpc_id == "" ? module.vpc[0].vpc_id : var.vpc_id
  vpc_endpoints {
    dataplane_relay = [databricks_mws_vpc_endpoint.backend_relay.vpc_endpoint_id]
    rest_api        = [databricks_mws_vpc_endpoint.backend_rest.vpc_endpoint_id]
  }
}

# Private Access Setting Configuration
resource "databricks_mws_private_access_settings" "pas" {
  provider                     = databricks.mws
  private_access_settings_name = "${var.prefix}-PAS"
  region                       = var.region
  public_access_enabled        = true
  private_access_level         = "ACCOUNT"
}


resource "databricks_mws_credentials" "this" {
  provider         = databricks.mws
  role_arn         = aws_iam_role.cross_account_role.arn
  credentials_name = "${var.prefix}-creds"
  depends_on       = [time_sleep.wait_30_seconds]
}

resource "databricks_mws_workspaces" "this" {
  provider                   = databricks.mws
  account_id                 = var.databricks_account_id
  aws_region                 = var.region
  workspace_name             = "${var.prefix}-ws"
  credentials_id             = databricks_mws_credentials.this.credentials_id
  storage_configuration_id   = databricks_mws_storage_configurations.this.storage_configuration_id
  network_id                 = databricks_mws_networks.this.network_id
  private_access_settings_id = databricks_mws_private_access_settings.pas.private_access_settings_id
  pricing_tier               = "ENTERPRISE"
  depends_on                 = [databricks_mws_networks.this]
}

resource "time_sleep" "wait_2_minutes" {
  depends_on      = [databricks_mws_workspaces.this]
  create_duration = "120s"
}

