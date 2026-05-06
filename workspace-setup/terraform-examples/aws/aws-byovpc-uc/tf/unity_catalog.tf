# Delay after IAM policy is attached so AWS / UC propagation can settle before
# Databricks validates S3 read on external location creation.
resource "time_sleep" "wait_60_seconds" {
  depends_on      = [aws_iam_policy_attachment.unity_catalog_attach]
  create_duration = "60s"
}

locals {
  uc_iam_role         = "${var.resource_prefix}-catalog"
  uc_catalog_name_us  = replace(var.prefix, "-", "_")
  catalog_bucket_name = "${var.resource_prefix}-catalog-storage-${random_string.catalog_bucket_suffix.result}"

  # Resolved UC object names (optional vars default to "" in variables.tf; prefix-based defaults cannot live in variable defaults)
  uc_catalog_name            = var.catalog_name != "" ? var.catalog_name : "${var.prefix}-catalog"
  uc_external_location_name  = var.external_location_name != "" ? var.external_location_name : "${var.resource_prefix}-external-location"
  uc_storage_credential_name = var.storage_credential_name != "" ? var.storage_credential_name : "${var.resource_prefix}-storage-credential"
}

resource "random_string" "catalog_bucket_suffix" {
  length  = 8
  special = false
  upper   = false
}

# Storage Credential (created before role): https://registry.terraform.io/providers/databricks/databricks/latest/docs/guides/unity-catalog#configure-external-locations-and-credentials
resource "databricks_storage_credential" "uc_storage_cred" {
  provider = databricks.workspace
  name     = local.uc_storage_credential_name
  aws_iam_role {
    role_arn = "arn:aws:iam::${var.aws_account_id}:role/${local.uc_iam_role}"
  }
  depends_on = [databricks_metastore_assignment.this]
}

# Unity Catalog Trust Policy - Data Source
data "databricks_aws_unity_catalog_assume_role_policy" "unity_catalog" {
  provider              = databricks.workspace
  aws_account_id        = var.aws_account_id
  aws_partition         = "aws"
  role_name             = local.uc_iam_role
  unity_catalog_iam_arn = "arn:aws:iam::414351767826:role/unity-catalog-prod-UCMasterRole-14S5ZJVKOTYTL"
  external_id           = databricks_storage_credential.uc_storage_cred.aws_iam_role[0].external_id
}

# Unity Catalog Policy - Data Source
data "databricks_aws_unity_catalog_policy" "unity_catalog" {
  provider       = databricks.workspace
  aws_account_id = var.aws_account_id
  aws_partition  = "aws"
  bucket_name    = local.catalog_bucket_name
  role_name      = local.uc_iam_role
}

# Unity Catalog Policy
resource "aws_iam_policy" "unity_catalog" {
  name   = "${var.prefix}-catalog-policy"
  policy = data.databricks_aws_unity_catalog_policy.unity_catalog.json
}

# Unity Catalog Role
resource "aws_iam_role" "unity_catalog" {
  name               = local.uc_iam_role
  assume_role_policy = data.databricks_aws_unity_catalog_assume_role_policy.unity_catalog.json
}

# Unity Catalog Policy Attachment
resource "aws_iam_policy_attachment" "unity_catalog_attach" {
  name       = "${var.prefix}-unity_catalog_policy_attach"
  roles      = [aws_iam_role.unity_catalog.name]
  policy_arn = aws_iam_policy.unity_catalog.arn
}

# Unity Catalog S3
resource "aws_s3_bucket" "unity_catalog_bucket" {
  bucket        = local.catalog_bucket_name
  force_destroy = true
}

resource "aws_s3_bucket_versioning" "unity_catalog_versioning" {
  bucket = aws_s3_bucket.unity_catalog_bucket.id
  versioning_configuration {
    status = "Disabled"
  }
}

resource "aws_s3_bucket_public_access_block" "unity_catalog" {
  bucket                  = aws_s3_bucket.unity_catalog_bucket.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
  depends_on              = [aws_s3_bucket.unity_catalog_bucket]
}

# External Location
resource "databricks_external_location" "uc_external_location" {
  provider        = databricks.workspace
  name            = local.uc_external_location_name
  url             = "s3://${aws_s3_bucket.unity_catalog_bucket.id}"
  credential_name = databricks_storage_credential.uc_storage_cred.id
  force_destroy   = true
  depends_on      = [time_sleep.wait_60_seconds]
}
resource "databricks_catalog" "uc_quickstart" {
  provider = databricks.workspace
  name     = local.uc_catalog_name
  # storage_root = "${var.storage_root}"
  storage_root  = databricks_external_location.uc_external_location.url
  comment       = "this catalog is managed by terraform"
  force_destroy = true
  # enable_predictive_optimization = "ENABLE"
  # isolation_mode = "OPEN"
  # properties = {
  #   purpose = "development"
  # }
}