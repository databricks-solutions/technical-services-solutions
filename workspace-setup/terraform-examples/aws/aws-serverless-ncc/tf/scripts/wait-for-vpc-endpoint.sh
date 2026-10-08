#!/usr/bin/env bash
#
# Poll the Databricks NCC private endpoint rule until its vpc_endpoint_id
# is populated by AWS. Called from null_resource.wait_for_vpc_endpoint in
# tf/s3_endpoint.tf.
#
# Inputs (env vars set by the null_resource provisioner):
#   NCC_ID, RULE_ID                            — the rule to poll
#   DATABRICKS_HOST, DATABRICKS_ACCOUNT_ID     — account-level CLI target
#   DATABRICKS_CLIENT_ID, DATABRICKS_CLIENT_SECRET — inherited from shell
#
# Polls every 10s up to 5 minutes (30 attempts). Exits 0 on success, 1 on
# timeout. Logs to stderr so Terraform surfaces it inline.

set -euo pipefail

: "${NCC_ID:?must be set by null_resource environment}"
: "${RULE_ID:?must be set by null_resource environment}"
: "${DATABRICKS_HOST:?must be set by null_resource environment}"
: "${DATABRICKS_ACCOUNT_ID:?must be set by null_resource environment}"
: "${DATABRICKS_CLIENT_ID:?must be exported in your shell}"
: "${DATABRICKS_CLIENT_SECRET:?must be exported in your shell}"

for i in $(seq 1 30); do
  VPCE=$(databricks account network-connectivity get-private-endpoint-rule \
    "$NCC_ID" "$RULE_ID" --output json | jq -r '.vpc_endpoint_id // empty')
  if [ -n "$VPCE" ]; then
    echo "[wait-for-vpc-endpoint] vpc_endpoint_id=$VPCE ready (attempt $i/30)" >&2
    exit 0
  fi
  echo "[wait-for-vpc-endpoint] vpc_endpoint_id not yet populated (attempt $i/30)" >&2
  sleep 10
done

echo "[wait-for-vpc-endpoint] vpc_endpoint_id not populated after 5 minutes" >&2
exit 1
