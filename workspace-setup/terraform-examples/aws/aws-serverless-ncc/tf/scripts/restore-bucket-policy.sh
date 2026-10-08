#!/usr/bin/env bash
#
# Restore the bucket policy that existed before this Terraform module owned
# it. Called from null_resource.restore_bucket_policy_on_destroy in
# tf/s3_endpoint.tf via a `when = destroy` provisioner, AFTER Terraform has
# torn down `aws_s3_bucket_policy.allow_databricks_s3_vpce` (which would
# otherwise leave the bucket with no policy at all).
#
# Inputs (env vars set by the null_resource `triggers` + provisioner):
#   BUCKET_NAME        — bucket to restore the policy on
#   ORIGINAL_POLICY    — stringified JSON policy captured on first apply.
#                        Empty string means "bucket originally had no policy";
#                        we exit cleanly without touching the bucket.
#
# Tolerates the bucket having been deleted out-of-band before destroy runs
# (in that case there's nothing to restore, so exit 0). All other AWS
# errors surface non-zero so destroy fails loudly.

set -euo pipefail

: "${BUCKET_NAME:?must be set by null_resource environment}"

if [ -z "${ORIGINAL_POLICY:-}" ]; then
  echo "[restore-bucket-policy] no original policy captured on first apply; nothing to restore" >&2
  exit 0
fi

if ! aws s3api head-bucket --bucket "$BUCKET_NAME" 2>/dev/null; then
  echo "[restore-bucket-policy] bucket $BUCKET_NAME no longer exists, skipping restore" >&2
  exit 0
fi

# Write policy to a temp file so we don't fight shell quoting rules for
# large JSON blobs (aws CLI's file:// prefix reads the payload verbatim).
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT
printf '%s' "$ORIGINAL_POLICY" >"$TMP"

echo "[restore-bucket-policy] restoring original policy on bucket $BUCKET_NAME" >&2
aws s3api put-bucket-policy --bucket "$BUCKET_NAME" --policy "file://$TMP"
echo "[restore-bucket-policy] done" >&2
