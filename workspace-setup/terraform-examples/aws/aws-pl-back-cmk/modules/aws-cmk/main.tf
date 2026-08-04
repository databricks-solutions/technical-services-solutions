# kms.tf (root or a module)

resource "aws_kms_key" "databricks_cmk" {
  description             = "CMK for Databricks Managed Services & Workspace Storage"
  enable_key_rotation     = true
  deletion_window_in_days = 7
}

resource "aws_kms_alias" "databricks_cmk_alias" {
  name          = "alias/databricks/${var.project_name}-cmk"
  target_key_id = aws_kms_key.databricks_cmk.key_id
}

# Replace ACCOUNT_ID below with your AWS account id (or use data.aws_caller_identity.current.account_id)
data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "databricks_cmk_policy" {
  # Full admin for your account root (you can refine to a KMS admin group)
  statement {
    sid     = "AllowAccountAdministrators"
    actions = ["kms:*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
    resources = ["*"]
  }

  # Allow Databricks control plane (commercial) to describe and encrypt/decrypt for validation
  statement {
    sid = "AllowDatabricksControlPlaneDirectUse"
    actions = [
      "kms:Decrypt",
      "kms:Encrypt",
      "kms:GenerateDataKey*",
      "kms:DescribeKey",
      "kms:ReEncrypt*"
    ]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::414351767826:root"]
    }
    resources = ["*"]
  }

  # Allow Databricks control plane to create grants & use the key for AWS resources
  statement {
    sid = "AllowDatabricksControlPlaneGrants"
    actions = [
      "kms:CreateGrant",
      "kms:DescribeKey"
    ]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::414351767826:root"]
    }
    resources = ["*"]
    condition {
      test     = "Bool"
      variable = "kms:GrantIsForAWSResource"
      values   = ["true"]
    }
  }

  # Optional: let your Databricks cross-account role create grants too
  statement {
    sid = "AllowCrossAccountProvisioningRoleGrants"
    actions = [
      "kms:CreateGrant",
      "kms:DescribeKey"
    ]
    principals {
      type        = "AWS"
      identifiers = [var.cross_account_role_arn]
    }
    resources = ["*"]
    condition {
      test     = "Bool"
      variable = "kms:GrantIsForAWSResource"
      values   = ["true"]
    }
  }
}

resource "aws_kms_key_policy" "databricks_cmk_policy" {
  key_id = aws_kms_key.databricks_cmk.key_id
  policy = data.aws_iam_policy_document.databricks_cmk_policy.json
}

# Wait for KMS key policy to propagate
resource "time_sleep" "wait_for_kms_policy" {
  create_duration = "30s"

  depends_on = [aws_kms_key_policy.databricks_cmk_policy]
}
