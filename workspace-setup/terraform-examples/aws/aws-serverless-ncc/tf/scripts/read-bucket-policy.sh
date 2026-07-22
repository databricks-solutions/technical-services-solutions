#!/usr/bin/env bash
#
# Tolerant read of an S3 bucket policy for consumption by a Terraform
# `data "external"` block. Called from data.external.current_bucket_policy in
# tf/s3_endpoint.tf.
#
# Behavior:
#   - Returns an empty string when the bucket has no policy (NoSuchBucketPolicy)
#     — a case where the raw `data.aws_s3_bucket_policy` errors out.
#   - Strips the "AllowDatabricksServerlessViaVpce" statement if present, so
#     re-reading a bucket whose policy this module has already merged into
#     yields the same result as the first read. That idempotence is what lets
#     null_resource.restore_bucket_policy_on_destroy use this data source
#     directly as a trigger (no terraform_data snapshot needed) — the trigger
#     value stays stable across applies, and destroy-time restore replays
#     exactly the pre-Terraform statements.
#   - If stripping our statement leaves an otherwise-empty policy (no other
#     statements), returns "" so restore-bucket-policy.sh knows to leave the
#     bucket policy-less on destroy.
#
# Inputs (stdin, query JSON from `data "external"`):
#   {"bucket": "<bucket-name>"}
#
# Output (stdout, JSON with string values only — data.external contract):
#   {"policy": "<stringified policy JSON with our statement stripped>"}
#   {"policy": ""}   when bucket has no policy, or only had our statement
#
# Non-zero exit for any other failure (missing bucket, access denied, etc.)
# so misconfigurations surface at plan time rather than silently degrading.

set -euo pipefail

BUCKET=$(jq -r '.bucket')

if [ -z "$BUCKET" ] || [ "$BUCKET" = "null" ]; then
  echo "[read-bucket-policy] bucket name is required in query JSON" >&2
  exit 1
fi

STDERR_TMP=$(mktemp)
trap 'rm -f "$STDERR_TMP"' EXIT

if POLICY_JSON=$(aws s3api get-bucket-policy --bucket "$BUCKET" --output json 2>"$STDERR_TMP"); then
  # Strip the Databricks-managed statement. If nothing else is left, return
  # empty so downstream consumers treat the bucket as originally policy-less.
  STRIPPED=$(printf '%s' "$POLICY_JSON" | jq -r '.Policy' | jq -c '
    .Statement |= (map(select(.Sid != "AllowDatabricksServerlessViaVpce")))
    | if (.Statement | length) == 0 then null else . end
  ')
  if [ "$STRIPPED" = "null" ]; then
    jq -nc '{policy: ""}'
  else
    jq -nc --arg policy "$STRIPPED" '{policy: $policy}'
  fi
elif grep -q "NoSuchBucketPolicy" "$STDERR_TMP"; then
  # Bucket exists but has no policy — expected case, return empty snapshot.
  jq -nc '{policy: ""}'
else
  echo "[read-bucket-policy] failed to read policy for bucket $BUCKET:" >&2
  cat "$STDERR_TMP" >&2
  exit 1
fi
