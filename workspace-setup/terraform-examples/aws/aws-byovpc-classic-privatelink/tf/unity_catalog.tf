# Same optional catalog bundle as aws-byovpc-uc; metastore management is independent.
locals {
  uc_iam_role                = "${var.resource_prefix}-catalog"
  catalog_bucket_name        = "${var.resource_prefix}-catalog-storage-${join("", random_string.catalog_bucket_suffix[*].result)}"
  uc_catalog_name            = var.catalog_name != "" ? var.catalog_name : "${var.prefix}-catalog"
  uc_external_location_name  = var.external_location_name != "" ? var.external_location_name : "${var.resource_prefix}-external-location"
  uc_storage_credential_name = var.storage_credential_name != "" ? var.storage_credential_name : "${var.resource_prefix}-storage-credential"
}

resource "random_string" "catalog_bucket_suffix" {
  count   = var.new_catalog ? 1 : 0
  length  = 8
  special = false
  upper   = false
}

# The credential supplies the external ID used by the role's trust policy.
resource "databricks_storage_credential" "uc_storage_cred" {
  count    = var.new_catalog ? 1 : 0
  provider = databricks.workspace
  name     = local.uc_storage_credential_name
  aws_iam_role {
    role_arn = "arn:aws:iam::${var.aws_account_id}:role/${local.uc_iam_role}"
  }
  depends_on = [databricks_metastore_assignment.this]

  lifecycle {
    precondition {
      condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
      error_message = "aws_account_id must be a 12-digit AWS account ID when new_catalog is true."
    }
  }
}

data "databricks_aws_unity_catalog_assume_role_policy" "unity_catalog" {
  count                 = var.new_catalog ? 1 : 0
  provider              = databricks.workspace
  aws_account_id        = var.aws_account_id
  aws_partition         = "aws"
  role_name             = local.uc_iam_role
  unity_catalog_iam_arn = "arn:aws:iam::414351767826:role/unity-catalog-prod-UCMasterRole-14S5ZJVKOTYTL"
  external_id           = databricks_storage_credential.uc_storage_cred[0].aws_iam_role[0].external_id
}

data "databricks_aws_unity_catalog_policy" "unity_catalog" {
  count          = var.new_catalog ? 1 : 0
  provider       = databricks.workspace
  aws_account_id = var.aws_account_id
  aws_partition  = "aws"
  bucket_name    = local.catalog_bucket_name
  role_name      = local.uc_iam_role
}

resource "aws_iam_policy" "unity_catalog" {
  count  = var.new_catalog ? 1 : 0
  name   = "${var.prefix}-catalog-policy"
  policy = data.databricks_aws_unity_catalog_policy.unity_catalog[0].json
}

resource "aws_iam_role" "unity_catalog" {
  count              = var.new_catalog ? 1 : 0
  name               = local.uc_iam_role
  assume_role_policy = data.databricks_aws_unity_catalog_assume_role_policy.unity_catalog[0].json
}

resource "aws_iam_policy_attachment" "unity_catalog_attach" {
  count      = var.new_catalog ? 1 : 0
  name       = "${var.prefix}-unity_catalog_policy_attach"
  roles      = [aws_iam_role.unity_catalog[0].name]
  policy_arn = aws_iam_policy.unity_catalog[0].arn
}

resource "aws_s3_bucket" "unity_catalog_bucket" {
  count         = var.new_catalog ? 1 : 0
  bucket        = local.catalog_bucket_name
  force_destroy = true
}

resource "aws_s3_bucket_versioning" "unity_catalog_versioning" {
  count  = var.new_catalog ? 1 : 0
  bucket = aws_s3_bucket.unity_catalog_bucket[0].id
  versioning_configuration {
    status = "Disabled"
  }
}

resource "aws_s3_bucket_public_access_block" "unity_catalog" {
  count                   = var.new_catalog ? 1 : 0
  bucket                  = aws_s3_bucket.unity_catalog_bucket[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "time_sleep" "wait_60_seconds" {
  count           = var.new_catalog ? 1 : 0
  depends_on      = [aws_iam_policy_attachment.unity_catalog_attach]
  create_duration = "60s"
}

resource "databricks_external_location" "uc_external_location" {
  count           = var.new_catalog ? 1 : 0
  provider        = databricks.workspace
  name            = local.uc_external_location_name
  url             = "s3://${aws_s3_bucket.unity_catalog_bucket[0].id}"
  credential_name = databricks_storage_credential.uc_storage_cred[0].id
  force_destroy   = true
  depends_on      = [time_sleep.wait_60_seconds, aws_s3_bucket_public_access_block.unity_catalog]
}

resource "databricks_catalog" "uc_quickstart" {
  count         = var.new_catalog ? 1 : 0
  provider      = databricks.workspace
  name          = local.uc_catalog_name
  storage_root  = databricks_external_location.uc_external_location[0].url
  comment       = "this catalog is managed by terraform"
  force_destroy = true
}
