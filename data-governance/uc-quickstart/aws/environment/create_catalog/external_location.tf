locals {
  external_location_name = "${var.catalog_name}_external_location"
}

resource "null_resource" "previous" {}

# Wait to prevent race condition between IAM role and external location validation
resource "time_sleep" "wait_60_seconds" {
  depends_on      = [null_resource.previous]
  create_duration = "60s"
}

# External Location
resource "databricks_external_location" "uc_external_location" {
  name            = local.external_location_name
  url             = "s3://${aws_s3_bucket.unity_catalog_bucket.id}"
  credential_name = databricks_storage_credential.uc_storage_cred.id
  depends_on      = [aws_iam_policy_attachment.unity_catalog_attach, time_sleep.wait_60_seconds]
  force_destroy = var.force_destroy_external_location
}