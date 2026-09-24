locals {
  storage_credential_name = "${var.bucket_name}_storage_credential"
}

resource "databricks_storage_credential" "uc_storage_cred" {
  name = local.storage_credential_name
  aws_iam_role {
    role_arn = "arn:aws:iam::${var.aws_account_id}:role/${local.uc_iam_role}"
  }
  comment = "AWS IAM role credential managed by TF"
}