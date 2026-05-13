################################################################################
# 6b. Unity Catalog external location + grants
################################################################################

locals {
  external_location_url = (
    var.external_location_path == ""
    ? "s3://${var.external_location_bucket_name}/"
    : "s3://${var.external_location_bucket_name}/${trim(var.external_location_path, "/")}/"
  )

  resolved_external_location_name = coalesce(var.external_location_name, "${var.prefix}-external-location")
}

# Create the external location. depends_on the bucket policy + endpoint rule
# so UC's first read against the bucket succeeds immediately.
resource "databricks_external_location" "this" {
  provider = databricks.workspace

  name            = local.resolved_external_location_name
  url             = local.external_location_url
  credential_name = databricks_storage_credential.external.id
  comment         = "Managed by Terraform"
  # Owner stays as the deployment SP. The user gets MANAGE via
  # databricks_grants.external_location below.

  depends_on = [
    time_sleep.wait_for_uc_iam,
    aws_s3_bucket_policy.allow_databricks_s3_vpce,
    databricks_mws_ncc_private_endpoint_rule.s3,
  ]
}

# Grant the user MANAGE on the external location, plus the optional
# external_location_grant_principal (e.g. "account users") gets read-mostly
# access if set.
resource "databricks_grants" "external_location" {
  provider = databricks.workspace

  external_location = databricks_external_location.this.id

  grant {
    principal  = var.workspace_admin_email
    privileges = ["MANAGE", "CREATE_EXTERNAL_TABLE", "READ_FILES", "WRITE_FILES"]
  }

  dynamic "grant" {
    for_each = var.external_location_grant_principal != null ? [var.external_location_grant_principal] : []
    content {
      principal  = grant.value
      privileges = ["CREATE_EXTERNAL_TABLE", "READ_FILES"]
    }
  }
}
