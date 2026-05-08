################################################################################
# Databricks Serverless Workspace + NCC + S3 External Location
#
# This file contains all provider blocks, resources, data sources, and locals
# for this scenario. Sections (in apply order):
#
#   1. Providers
#   2. Workspace (lookup or create) + admin assignment
#   3. NCC + binding + optional generic non-S3 endpoint rule
#   4. Metastore (lookup or create) + assignment + admin grants
#   5. S3 NCC private endpoint rule + bucket policy + enable PATCH
#   6. UC IAM role + storage credential + external location + grants
#
# All sensitive auth (Databricks OAuth client_id/client_secret, AWS keys)
# is read from environment variables, not from variables in this config.
# See the README for the env vars to export before running terraform.
################################################################################


################################################################################
# 1. Providers
################################################################################

# Account-level Databricks provider — used to create workspace, NCC, metastore,
# permission assignments. Reads OAuth M2M credentials from
# DATABRICKS_CLIENT_ID / DATABRICKS_CLIENT_SECRET env vars.
provider "databricks" {
  alias      = "account"
  host       = "https://accounts.cloud.databricks.com"
  account_id = var.databricks_account_id
}

# Workspace-level Databricks provider — used for storage credential, external
# location, and grants. account_id is required so the SDK fetches the OAuth
# token from the accounts URL when authenticating with an account-level SP.
# Without account_id, the SDK would attempt workspace-level OAuth and fail.
provider "databricks" {
  alias = "workspace"
  host = var.create_new_workspace ? databricks_mws_workspaces.serverless_workspace[0].workspace_url : (
    var.existing_workspace_host != null ? var.existing_workspace_host : "https://accounts.cloud.databricks.com"
  )
  account_id = var.databricks_account_id
}

# AWS provider — credentials read from environment (AWS_PROFILE,
# AWS_ACCESS_KEY_ID, AWS_SESSION_TOKEN, etc.). default_tags applies the tags
# below to every AWS resource managed by this config.
provider "aws" {
  region = var.region

  default_tags {
    tags = {
      ManagedBy = "Terraform"
      Project   = var.prefix
    }
  }
}


################################################################################
# 2. Workspace
################################################################################

# Optional lookup of an existing workspace by name (when neither
# create_new_workspace nor existing_workspace_id are set).
data "databricks_mws_workspaces" "existing_by_name" {
  count    = (!var.create_new_workspace && var.existing_workspace_id == null && var.existing_workspace_name != null) ? 1 : 0
  provider = databricks.account
}

# Create a new serverless workspace.
resource "databricks_mws_workspaces" "serverless_workspace" {
  count = var.create_new_workspace ? 1 : 0

  provider       = databricks.account
  account_id     = var.databricks_account_id
  workspace_name = var.workspace_name
  aws_region     = var.region
  compute_mode   = "SERVERLESS"
}

# Resolve workspace_id from the appropriate source:
#   1. If create_new_workspace=true,  use the just-created workspace's ID.
#   2. Else if existing_workspace_id is set, use it directly.
#   3. Else, look up by existing_workspace_name in the by_name data source.
locals {
  resolved_existing_workspace_id = var.existing_workspace_id != null ? var.existing_workspace_id : (
    length(data.databricks_mws_workspaces.existing_by_name) > 0
    ? lookup(data.databricks_mws_workspaces.existing_by_name[0].ids, var.existing_workspace_name, null)
    : null
  )

  workspace_id = var.create_new_workspace ? databricks_mws_workspaces.serverless_workspace[0].workspace_id : local.resolved_existing_workspace_id
}

# Look up the user that should be made workspace admin. Errors at apply time
# if the email isn't a real Databricks account user.
data "databricks_user" "workspace_admin" {
  provider  = databricks.account
  user_name = var.workspace_admin_email
}

# Assign the user as workspace ADMIN. Depends on NCC binding + metastore
# assignment so we don't activate the user before the workspace is fully
# wired up.
resource "databricks_mws_permission_assignment" "workspace_admin" {
  provider     = databricks.account
  workspace_id = local.workspace_id
  principal_id = data.databricks_user.workspace_admin.id
  permissions  = ["ADMIN"]

  depends_on = [
    databricks_mws_ncc_binding.ncc_binding,
    databricks_metastore_assignment.this
  ]
}


################################################################################
# 3. Network Connectivity Configuration (NCC)
################################################################################

# The NCC routes serverless egress traffic privately. Each workspace can be
# bound to one NCC. Default name is "ncc-<prefix>" if ncc_name isn't set.
resource "databricks_mws_network_connectivity_config" "ncc" {
  provider = databricks.account
  name     = coalesce(var.ncc_name, "ncc-${var.prefix}")
  region   = var.region
}

# Bind the NCC to the workspace. Must succeed before metastore assignment +
# admin assignment are attempted.
resource "databricks_mws_ncc_binding" "ncc_binding" {
  provider = databricks.account

  network_connectivity_config_id = databricks_mws_network_connectivity_config.ncc.network_connectivity_config_id
  workspace_id                   = local.workspace_id

  lifecycle {
    precondition {
      condition     = local.workspace_id != null
      error_message = "workspace_id could not be resolved. Set create_new_workspace=true, or provide existing_workspace_id, or provide existing_workspace_name that matches an existing workspace in the Databricks account."
    }
  }
}

# Optional non-S3 NCC private endpoint rule (e.g. RDS, Kinesis, custom VPC
# endpoint service). Set create_private_endpoint_rule=true and supply
# endpoint_service + domain_names to use this. The S3-specific endpoint
# rule is handled in section 5.
resource "databricks_mws_ncc_private_endpoint_rule" "aws_private_endpoint" {
  count    = var.create_private_endpoint_rule ? 1 : 0
  provider = databricks.account

  network_connectivity_config_id = databricks_mws_network_connectivity_config.ncc.network_connectivity_config_id
  endpoint_service               = var.endpoint_service
  domain_names                   = var.domain_names

  lifecycle {
    precondition {
      condition     = var.endpoint_service != null && length(var.domain_names) > 0
      error_message = "When create_private_endpoint_rule=true, you must set endpoint_service and at least one value in domain_names."
    }
  }
}


################################################################################
# 4. Unity Catalog Metastore
################################################################################

# Three optional lookups for an existing metastore. Used in priority order:
# explicit ID, then by name, then any metastore in the same region.
data "databricks_metastore" "existing_by_id" {
  count    = var.use_existing_metastore && var.existing_metastore_id != null ? 1 : 0
  provider = databricks.account

  metastore_id = var.existing_metastore_id
}

data "databricks_metastore" "existing_by_name" {
  count    = var.use_existing_metastore && var.existing_metastore_id == null && var.existing_metastore_name != null ? 1 : 0
  provider = databricks.account

  name = var.existing_metastore_name
}

data "databricks_metastore" "existing_by_region" {
  count    = var.use_existing_metastore && var.existing_metastore_id == null && var.existing_metastore_name == null ? 1 : 0
  provider = databricks.account

  region = var.region
}

# Create a new metastore.
#
# We intentionally do NOT set owner = workspace_admin_email here. The deployment
# SP needs to remain metastore owner during the apply so it can create the
# storage credential and external location below. The user gets equivalent
# admin-level access via databricks_grants.metastore_for_admin further down.
#
# lifecycle.ignore_changes=[owner] lets a human transfer ownership in the UI
# later without Terraform reverting it on the next apply.
resource "databricks_metastore" "this" {
  count    = var.use_existing_metastore ? 0 : 1
  provider = databricks.account

  name          = var.metastore_name != null ? var.metastore_name : "${var.prefix}-${var.region}-metastore"
  region        = var.region
  force_destroy = true

  lifecycle {
    ignore_changes = [owner]
  }
}

# Resolve metastore_id from whichever path was used (existing or new).
locals {
  resolved_metastore_id = var.use_existing_metastore ? coalesce(
    try(data.databricks_metastore.existing_by_id[0].id, null),
    try(data.databricks_metastore.existing_by_name[0].id, null),
    try(data.databricks_metastore.existing_by_region[0].id, null)
  ) : databricks_metastore.this[0].id
}

# Assign the metastore to the workspace. Required before any UC objects can be
# created in the workspace.
resource "databricks_metastore_assignment" "this" {
  provider = databricks.account

  workspace_id = local.workspace_id
  metastore_id = local.resolved_metastore_id

  depends_on = [
    databricks_mws_ncc_binding.ncc_binding
  ]

  lifecycle {
    precondition {
      condition     = local.resolved_metastore_id != null
      error_message = "Metastore ID could not be resolved. If using an existing metastore, provide existing_metastore_id or existing_metastore_name, or ensure a metastore exists in the same region."
    }
  }
}

# Grant the workspace admin user admin-level privileges on the metastore.
# Only applied when we created the metastore — for existing metastores you
# manage grants separately.
#
# Uses the workspace provider (not account) because metastore-level grants
# require workspace context in the current Databricks Terraform provider.
resource "databricks_grants" "metastore_for_admin" {
  count    = var.use_existing_metastore ? 0 : 1
  provider = databricks.workspace

  metastore = local.resolved_metastore_id

  grant {
    principal = var.workspace_admin_email
    privileges = [
      "CREATE_CATALOG",
      "CREATE_EXTERNAL_LOCATION",
      "CREATE_STORAGE_CREDENTIAL",
      "CREATE_PROVIDER",
      "CREATE_RECIPIENT",
      "CREATE_SHARE",
      "USE_PROVIDER",
      "USE_RECIPIENT",
      "USE_SHARE",
    ]
  }

  depends_on = [
    databricks_metastore.this,
    databricks_metastore_assignment.this,
  ]
}


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


################################################################################
# 6. Unity Catalog IAM + storage credential + external location + grants
################################################################################

# AWS account ID — used to construct the IAM role ARN below.
data "aws_caller_identity" "current" {}

locals {
  # Default the IAM role / storage credential / external location names off
  # the prefix when the user doesn't override them.
  uc_iam_role_name = coalesce(var.uc_iam_role_name, "${var.prefix}-uc-external-access")

  external_location_url = (
    var.external_location_path == ""
    ? "s3://${var.external_location_bucket_name}/"
    : "s3://${var.external_location_bucket_name}/${trim(var.external_location_path, "/")}/"
  )

  resolved_storage_credential_name = coalesce(var.storage_credential_name, local.uc_iam_role_name)
  resolved_external_location_name  = coalesce(var.external_location_name, "${var.prefix}-external-location")
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
