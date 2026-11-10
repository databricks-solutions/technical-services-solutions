data "aws_caller_identity" "current" {}

locals {
  restricted_policy = var.cross_account_policy_type == "restricted"
}

data "databricks_aws_assume_role_policy" "this" {
  provider    = databricks.mws
  external_id = var.databricks_account_id
}

resource "aws_iam_role" "cross_account_role" {
  name               = "${var.prefix}-crossaccount"
  assume_role_policy = data.databricks_aws_assume_role_policy.this.json
  tags               = var.tags
}

# Cross-account access policy. Two variants from
# https://docs.databricks.com/aws/en/admin/workspace/create-uc-workspace (Step 2):
#   - "customer":   Customer-managed VPC with default restrictions.
#   - "restricted": Customer-managed VPC with custom restrictions. EC2 actions are scoped
#                   to this AWS account, region, VPC and workspace security group.
# The restricted arguments are left null for "customer" so that variant is unchanged.
data "databricks_aws_crossaccount_policy" "this" {
  provider          = databricks.mws
  policy_type       = var.cross_account_policy_type
  aws_account_id    = local.restricted_policy ? data.aws_caller_identity.current.account_id : null
  region            = local.restricted_policy ? var.region : null
  vpc_id            = local.restricted_policy ? local.vpc_id : null
  security_group_id = local.restricted_policy ? local.security_group_ids[0] : null

  lifecycle {
    precondition {
      condition     = !local.restricted_policy || length(local.security_group_ids) == 1
      error_message = "cross_account_policy_type = \"restricted\" scopes the policy to a single security group. Provide exactly one ID in security_group_ids (or leave it empty so the template creates one)."
    }
    precondition {
      condition     = !local.restricted_policy || data.aws_caller_identity.current.account_id == var.aws_account_id
      error_message = "aws_account_id does not match the AWS account of the current AWS credentials. The restricted policy is scoped to the account where the VPC and cross-account role live."
    }
  }
}

resource "aws_iam_role_policy" "this" {
  name   = "${var.prefix}-policy"
  role   = aws_iam_role.cross_account_role.id
  policy = data.databricks_aws_crossaccount_policy.this.json
}

