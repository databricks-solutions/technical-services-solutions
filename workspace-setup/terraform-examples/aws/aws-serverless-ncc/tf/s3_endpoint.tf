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
    ignore_changes = [enabled]
  }
}

# Wait 90s for AWS to provision the underlying VPC endpoint. The Databricks
# API returns the rule before AWS has finished provisioning, so the rule's
# vpc_endpoint_id attribute is null in the immediate response. Re-reading
# the NCC after this wait surfaces the populated vpc_endpoint_id.
resource "time_sleep" "wait_for_vpc_endpoint" {
  depends_on      = [databricks_mws_ncc_private_endpoint_rule.s3]
  create_duration = "90s"

  triggers = {
    rule_id = databricks_mws_ncc_private_endpoint_rule.s3.rule_id
  }
}

# Re-read the NCC after the wait to fetch the populated vpc_endpoint_id from
# its egress_config.
data "databricks_mws_network_connectivity_config" "ncc_refreshed" {
  provider = databricks.account
  name     = databricks_mws_network_connectivity_config.ncc.name

  depends_on = [time_sleep.wait_for_vpc_endpoint]
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

# Enable the rule via the Databricks REST API.
#
# Why this is a null_resource and not a Terraform resource attribute: the
# Databricks API ignores enabled=true at create time for S3 rules. The field
# can only be PATCHed AFTER connection_state has reached ESTABLISHED — which
# only happens after the bucket policy is in place and AWS auto-approves the
# connection (typically 1–5 min).
#
# Requires curl and jq on PATH. Reads DATABRICKS_CLIENT_ID and
# DATABRICKS_CLIENT_SECRET from the inherited shell environment.
resource "null_resource" "enable_s3_rule" {
  triggers = {
    rule_id = databricks_mws_ncc_private_endpoint_rule.s3.rule_id
  }

  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    environment = {
      ACCOUNT_ID = var.databricks_account_id
      NCC_ID     = databricks_mws_network_connectivity_config.ncc.network_connectivity_config_id
      RULE_ID    = databricks_mws_ncc_private_endpoint_rule.s3.rule_id
    }
    command = <<-EOT
      set -uo pipefail

      if [ -z "$${DATABRICKS_CLIENT_ID:-}" ] || [ -z "$${DATABRICKS_CLIENT_SECRET:-}" ]; then
        echo "[enable_s3_rule] DATABRICKS_CLIENT_ID and DATABRICKS_CLIENT_SECRET must be exported in your shell" >&2
        exit 1
      fi

      TOKEN=$(curl -s -X POST -u "$DATABRICKS_CLIENT_ID:$DATABRICKS_CLIENT_SECRET" \
        "https://accounts.cloud.databricks.com/oidc/accounts/$ACCOUNT_ID/v1/token" \
        -d 'grant_type=client_credentials&scope=all-apis' | jq -r '.access_token // empty')

      if [ -z "$TOKEN" ]; then
        echo "[enable_s3_rule] Failed to get OAuth token" >&2
        exit 1
      fi

      RULE_URL="https://accounts.cloud.databricks.com/api/2.0/accounts/$ACCOUNT_ID/network-connectivity-configs/$NCC_ID/private-endpoint-rules/$RULE_ID"

      # Wait for connection_state=ESTABLISHED. The Databricks API rejects
      # PATCH enabled=true until the underlying VPC endpoint connection is
      # approved by AWS (1–5 min after bucket policy is in place). Poll up
      # to 10 minutes total.
      STATE="UNKNOWN"
      for i in $(seq 1 60); do
        STATE=$(curl -s -H "Authorization: Bearer $TOKEN" "$RULE_URL" | jq -r '.connection_state // "UNKNOWN"')
        echo "[enable_s3_rule] connection_state=$STATE (attempt $i/60)" >&2
        if [ "$STATE" = "ESTABLISHED" ]; then
          break
        fi
        if [ "$STATE" = "REJECTED" ] || [ "$STATE" = "DISCONNECTED" ] || [ "$STATE" = "EXPIRED" ]; then
          echo "[enable_s3_rule] connection_state=$STATE is terminal, cannot enable rule" >&2
          exit 1
        fi
        sleep 10
      done

      if [ "$STATE" != "ESTABLISHED" ]; then
        echo "[enable_s3_rule] connection_state did not reach ESTABLISHED after ~10 minutes (last: $STATE)" >&2
        exit 1
      fi

      # PATCH enabled=true. Retry on transient network errors.
      TMP=$(mktemp)
      for attempt in 1 2 3 4 5; do
        echo "[enable_s3_rule] PATCH attempt $attempt" >&2
        HTTP=$(curl -s -o "$TMP" -w '%%{http_code}' -X PATCH \
          -H "Authorization: Bearer $TOKEN" \
          -H "Content-Type: application/json" \
          "$RULE_URL?update_mask=enabled" \
          -d '{"enabled": true}')
        CURL_RC=$?
        BODY=$(cat "$TMP" 2>/dev/null || echo "")
        echo "[enable_s3_rule] curl_rc=$CURL_RC http=$HTTP body=$BODY" >&2
        if [ "$CURL_RC" = "0" ] && [ "$HTTP" = "200" ]; then
          ENABLED=$(echo "$BODY" | jq -r '.enabled // false')
          if [ "$ENABLED" = "true" ]; then
            echo "[enable_s3_rule] rule enabled successfully" >&2
            rm -f "$TMP"
            exit 0
          fi
        fi
        sleep 5
      done

      rm -f "$TMP"
      echo "[enable_s3_rule] failed to enable rule after 5 attempts" >&2
      exit 1
    EOT
  }

  depends_on = [
    aws_s3_bucket_policy.allow_databricks_s3_vpce,
    time_sleep.wait_for_vpc_endpoint,
  ]
}
