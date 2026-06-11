################################################################################
# 5. S3 NCC private endpoint rule + bucket policy + enable PATCH
################################################################################

# Create the S3-specific private endpoint rule. We set enabled=false here
# (rather than true) because the Databricks API ignores enabled=true at create
# time for S3 rules — the rule must transition to connection_state=ESTABLISHED
# before it can be enabled. Actual enabling is done by null_resource.enable_s3_rule
# below, which polls and PATCHes via the REST API.
#
# lifecycle.ignore_changes=[enabled] keeps Terraform from re-toggling enabled
# on subsequent applies (the null_resource owns that field's state).
resource "databricks_mws_ncc_private_endpoint_rule" "s3" {
  provider = databricks.account

  network_connectivity_config_id = databricks_mws_network_connectivity_config.ncc.network_connectivity_config_id
  endpoint_service               = "com.amazonaws.${var.region}.s3"
  resource_names                 = [var.external_location_bucket_name]
  enabled                        = false

  lifecycle {
    # `enabled`: owned by null_resource.enable_s3_rule (see below).
    # `account_id`: server-populated; provider versions disagree about whether
    #   to store it, causing phantom drift on upgrade. Ignoring it stops TF
    #   from sending an empty PATCH that the API rejects with
    #   "Update mask must be specified".
    ignore_changes = [enabled, account_id]
    # Fail before creating the rule (and burning the 5-minute VPC endpoint
    # wait) if the bucket is in a different region than the workspace.
    # Cross-region gives a cryptic 307 later in apply.
    precondition {
      # Passes if the bucket region matches OR the bucket can't be found.
      # The NOT_FOUND escape hatch is needed for `terraform destroy` after a
      # user has already deleted the bucket out-of-band — without it, destroy
      # would be blocked by a stale precondition on a resource that's about
      # to be destroyed anyway. If the bucket is genuinely missing during
      # apply, the downstream aws_s3_bucket_policy resource will fail with a
      # clear "NoSuchBucket" error.
      condition     = data.external.bucket_region.result["region"] == "NOT_FOUND" || data.external.bucket_region.result["region"] == var.region
      error_message = "Bucket '${var.external_location_bucket_name}' is in region '${data.external.bucket_region.result["region"]}' but the workspace is in '${var.region}'. They must match — Databricks requires the external-location bucket to be in the same region as the workspace. Either recreate the bucket in '${var.region}', or set var.region to match the bucket."
    }
  }
}

# Poll until AWS has provisioned the underlying VPC endpoint and the rule's
# vpc_endpoint_id is populated. The Databricks API returns the rule before
# AWS has finished provisioning, so vpc_endpoint_id is null in the create
# response. A flat sleep was unreliable (sometimes >90s was needed), so we
# poll the rule every 10s for up to 5 minutes.
resource "null_resource" "wait_for_vpc_endpoint" {
  triggers = {
    rule_id = databricks_mws_ncc_private_endpoint_rule.s3.rule_id
  }

  provisioner "local-exec" {
    command = "bash ${path.module}/scripts/wait-for-vpc-endpoint.sh"
    environment = {
      NCC_ID                = databricks_mws_network_connectivity_config.ncc.network_connectivity_config_id
      RULE_ID               = databricks_mws_ncc_private_endpoint_rule.s3.rule_id
      DATABRICKS_HOST       = "https://accounts.cloud.databricks.com"
      DATABRICKS_ACCOUNT_ID = var.databricks_account_id
    }
  }

  depends_on = [databricks_mws_ncc_private_endpoint_rule.s3]
}

# Re-read the NCC after the poll completes to fetch the populated
# vpc_endpoint_id from its egress_config.
data "databricks_mws_network_connectivity_config" "ncc_refreshed" {
  provider = databricks.account
  name     = databricks_mws_network_connectivity_config.ncc.name

  depends_on = [null_resource.wait_for_vpc_endpoint]
}

locals {
  # Flatten egress_config[*].target_rules[*].aws_private_endpoint_rules into a
  # single list of rule objects, then pick the one matching our rule_id.
  ncc_aws_private_endpoint_rules = flatten([
    for ec in data.databricks_mws_network_connectivity_config.ncc_refreshed.egress_config : [
      for tr in ec.target_rules : tr.aws_private_endpoint_rules
    ]
  ])

  matching_vpc_endpoint_ids = [
    for r in local.ncc_aws_private_endpoint_rules :
    r.vpc_endpoint_id if r.rule_id == databricks_mws_ncc_private_endpoint_rule.s3.rule_id
  ]

  # Resolve the vpce_id, propagating "(known after apply)" through plan time.
  #
  # The trick: rule.vpc_endpoint_id is "(known after apply)" at plan during
  # create — UNKNOWN. coalesce() short-circuits left to right and stops at the
  # first non-null value, but it cannot determine null-ness of an unknown
  # value, so it returns UNKNOWN at plan time. That unknown propagates through
  # aws_iam_policy_document.json and the bucket policy resource, which means
  # the bucket policy is committed with the real vpce_id at apply (no
  # two-apply convergence required).
  #
  # At apply time, rule.vpc_endpoint_id is null (Databricks API doesn't
  # populate it on create response). coalesce falls through to the data
  # source lookup, which by then has read fresh egress_config containing
  # the rule with its real vpce_id.
  s3_vpc_endpoint_id = coalesce(
    databricks_mws_ncc_private_endpoint_rule.s3.vpc_endpoint_id,
    one(local.matching_vpc_endpoint_ids)
  )
}

# Look up the target bucket's region so we can fail fast (with a clear
# message) if it doesn't match var.region. A cross-region bucket gives a
# cryptic 307 redirect later in the apply, which this precondition prevents.
#
# Implementation: data.aws_s3_bucket is region-bound (it returns "empty
# result" for a bucket in a different region), so we use the AWS CLI via
# data "external" instead. The CLI handles cross-region S3 lookups natively
# via GetBucketLocation. Requires `aws` and `jq` on PATH — same prereqs as
# the rest of this config.
#
# LocationConstraint is null for us-east-1 buckets (S3's "default" region),
# so we coalesce to "us-east-1".
data "external" "bucket_region" {
  # set -o pipefail makes the pipeline fail (and the || fallback fire) when
  # the AWS CLI errors. Without it, jq exits 0 on empty input, the `||` never
  # triggers, TF receives empty stdout, and the data source errors with
  # "unexpected end of JSON input" — which surfaces during destroy if the
  # bucket got deleted out-of-band before the destroy ran.
  program = ["bash", "-c", "set -o pipefail; aws s3api get-bucket-location --bucket ${var.external_location_bucket_name} --output json 2>/dev/null | jq '{region: (.LocationConstraint // \"us-east-1\")}' || echo '{\"region\": \"NOT_FOUND\"}'"]
}

# If merging with an existing bucket policy is requested, read it. Used as
# source_policy_documents in the IAM policy doc below.
data "aws_s3_bucket_policy" "existing" {
  count  = var.merge_existing_bucket_policy ? 1 : 0
  bucket = var.external_location_bucket_name
}

# Build the bucket policy. The aws:SourceVpce condition restricts the allow
# statement to traffic coming via the Databricks-owned VPC endpoint.
#
# depends_on = [ncc_refreshed] keeps this data source deferred to apply time
# so it picks up the resolved vpce_id from the local above.
data "aws_iam_policy_document" "allow_databricks_s3_vpce" {
  source_policy_documents = var.merge_existing_bucket_policy ? [data.aws_s3_bucket_policy.existing[0].policy] : []

  statement {
    sid    = "AllowDatabricksServerlessViaVpce"
    effect = "Allow"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]

    resources = [
      "arn:aws:s3:::${var.external_location_bucket_name}",
      "arn:aws:s3:::${var.external_location_bucket_name}/*"
    ]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceVpce"
      values   = [local.s3_vpc_endpoint_id]
    }
  }

  depends_on = [data.databricks_mws_network_connectivity_config.ncc_refreshed]
}

# Apply the bucket policy. If merge_existing_bucket_policy=false (default),
# this REPLACES whatever policy was on the bucket. Set the flag if the bucket
# has other statements you need to preserve.
resource "aws_s3_bucket_policy" "allow_databricks_s3_vpce" {
  bucket = var.external_location_bucket_name
  policy = data.aws_iam_policy_document.allow_databricks_s3_vpce.json
}

# Enable the rule via the Databricks API.
#
# Why a null_resource (and not a TF resource attribute): the Databricks API
# ignores enabled=true at create time for S3 rules. The field can only be
# updated AFTER connection_state has reached ESTABLISHED — which only
# happens after the bucket policy is in place and AWS auto-approves the
# connection (typically 1–5 min). The TF provider supports the update but
# does not natively poll for ESTABLISHED.
#
# Logic lives in tf/scripts/enable-s3-rule.sh. Requires `databricks` CLI
# (>= 0.297), `jq`, and DATABRICKS_CLIENT_ID / DATABRICKS_CLIENT_SECRET
# exported in the shell that runs terraform.
resource "null_resource" "enable_s3_rule" {
  triggers = {
    rule_id = databricks_mws_ncc_private_endpoint_rule.s3.rule_id
  }

  provisioner "local-exec" {
    command = "bash ${path.module}/scripts/enable-s3-rule.sh"
    environment = {
      NCC_ID                = databricks_mws_network_connectivity_config.ncc.network_connectivity_config_id
      RULE_ID               = databricks_mws_ncc_private_endpoint_rule.s3.rule_id
      DATABRICKS_HOST       = "https://accounts.cloud.databricks.com"
      DATABRICKS_ACCOUNT_ID = var.databricks_account_id
    }
  }

  depends_on = [
    aws_s3_bucket_policy.allow_databricks_s3_vpce,
    null_resource.wait_for_vpc_endpoint,
  ]
}

