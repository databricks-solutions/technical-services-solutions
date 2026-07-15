#!/usr/bin/env bash
#
# Tolerant read of an S3 bucket policy for consumption by a Terraform
# `data "external"` block. Returns an empty string when the bucket has no
# policy (NoSuchBucketPolicy) — a case where the raw `data.aws_s3_bucket_policy`
# errors out. Called from data.external.current_bucket_policy in
# tf/s3_endpoint.tf.
#
# Inputs (stdin, query JSON from `data "external"`):
#   {"bucket": "<bucket-name>"}
#
# Output (stdout, JSON with string values only — data.external contract):
#   {"policy": "<stringified policy JSON>"}   when bucket has a policy
#   {"policy": ""}                             when bucket has no policy
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
  POLICY=$(printf '%s' "$POLICY_JSON" | jq -r '.Policy')
  jq -nc --arg policy "$POLICY" '{policy: $policy}'
elif grep -q "NoSuchBucketPolicy" "$STDERR_TMP"; then
  # Bucket exists but has no policy — expected case, return empty snapshot.
  jq -nc '{policy: ""}'
else
  echo "[read-bucket-policy] failed to read policy for bucket $BUCKET:" >&2
  cat "$STDERR_TMP" >&2
  exit 1
fi
