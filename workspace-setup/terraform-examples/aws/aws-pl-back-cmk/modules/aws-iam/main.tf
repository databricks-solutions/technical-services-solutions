# Cross-account IAM role that Databricks assumes (commercial control plane account id 414351767826)
data "aws_caller_identity" "current" {}

resource "aws_iam_role" "databricks" {
  name = "${var.project}-databricks-cross-account"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect    = "Allow",
      Principal = { AWS = "arn:aws:iam::414351767826:root" },
      Action    = "sts:AssumeRole",
      Condition = {
        StringEquals = { "sts:ExternalId" = var.external_id }
      }
    }]
  })
}

# Minimal policy for workspace provisioning; tailor to your org's security baseline
data "aws_iam_policy_document" "policy" {
  statement {
    actions = [
      "s3:*",
      "ec2:*",
      "iam:PassRole",
      "iam:CreateServiceLinkedRole",
      "kms:*",
      "sts:AssumeRole"
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "databricks_inline" {
  name   = "${var.project}-databricks-provisioning"
  role   = aws_iam_role.databricks.id
  policy = data.aws_iam_policy_document.policy.json
}

output "cross_account_role_arn" {
  value      = aws_iam_role.databricks.arn
  depends_on = [aws_iam_role_policy.databricks_inline]
}
