################################################################################
# 6a. Unity Catalog IAM role + storage credential + grants
################################################################################

# AWS account ID — used to construct the IAM role ARN below.
data "aws_caller_identity" "current" {}

locals {
  # Default the IAM role / storage credential names off the prefix when the
  # user doesn't override them.
  uc_iam_role_name = coalesce(var.uc_iam_role_name, "${var.prefix}-uc-external-access")

  resolved_storage_credential_name = coalesce(var.storage_credential_name, local.uc_iam_role_name)
}

# Create the storage credential FIRST so its external_id is allocated. The
# external_id is required by the IAM trust policy below (this is the standard
# Databricks UC "self-assuming role" pattern).
resource "databricks_storage_credential" "external" {
  provider = databricks.workspace

  name = local.resolved_storage_credential_name
  # Owner stays as the deployment SP so it can create the external location
  # below. The user gets MANAGE via databricks_grants.storage_credential later.

  aws_iam_role {
    role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.uc_iam_role_name}"
  }

  comment = "Managed by Terraform"

  depends_on = [databricks_metastore_assignment.this]
}

# Standard Databricks-generated trust policy JSON. Uses the storage
# credential's external_id (allocated above) to scope the trust.
data "databricks_aws_unity_catalog_assume_role_policy" "external" {
  provider = databricks.workspace

  aws_account_id = data.aws_caller_identity.current.account_id
  role_name      = local.uc_iam_role_name
  external_id    = databricks_storage_credential.external.aws_iam_role[0].external_id
}

# Standard Databricks-generated IAM policy JSON for UC access to the bucket.
data "databricks_aws_unity_catalog_policy" "external" {
  provider = databricks.workspace

  aws_account_id = data.aws_caller_identity.current.account_id
  bucket_name    = var.external_location_bucket_name
  role_name      = local.uc_iam_role_name
}

resource "aws_iam_role" "external_data_access" {
  name               = local.uc_iam_role_name
  assume_role_policy = data.databricks_aws_unity_catalog_assume_role_policy.external.json
}

resource "aws_iam_policy" "external_data_access" {
  name   = "${local.uc_iam_role_name}-policy"
  policy = data.databricks_aws_unity_catalog_policy.external.json
}

resource "aws_iam_policy_attachment" "external_data_access" {
  name       = "${local.uc_iam_role_name}-attach"
  roles      = [aws_iam_role.external_data_access.name]
  policy_arn = aws_iam_policy.external_data_access.arn
}

# IAM changes need ~60s to propagate before the external location can use
# the role. Without this wait, external location creation fails with an
# AccessDenied even though the role exists.
resource "time_sleep" "wait_for_uc_iam" {
  depends_on      = [aws_iam_policy_attachment.external_data_access]
  create_duration = "60s"
}

# Grant the user MANAGE + standard usage privileges on the storage credential.
#
# depends_on the external location so the grants are applied AFTER the
# external location is created. databricks_grants is authoritative — applying
# it in parallel with external location creation can transiently revoke the
# SP-as-owner's implicit CREATE_EXTERNAL_LOCATION privilege.
resource "databricks_grants" "storage_credential" {
  provider = databricks.workspace

  storage_credential = databricks_storage_credential.external.id

  grant {
    principal  = var.workspace_admin_email
    privileges = ["MANAGE", "CREATE_EXTERNAL_LOCATION", "CREATE_EXTERNAL_TABLE", "READ_FILES", "WRITE_FILES"]
  }

  depends_on = [databricks_external_location.this]
}
