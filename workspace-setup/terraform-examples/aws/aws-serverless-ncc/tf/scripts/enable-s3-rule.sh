#!/usr/bin/env bash
#
# Enable the S3 NCC private endpoint rule. Called from null_resource.enable_s3_rule
# in tf/s3_endpoint.tf, AFTER the bucket policy is in place.
#
# Why a script is needed: the Databricks API ignores enabled=true at create
# time for S3 rules — the rule must transition to connection_state=ESTABLISHED
# before it can be enabled via update. The Terraform provider supports the
# update but does not natively poll for ESTABLISHED, so we do that here.
#
# Inputs (env vars set by the null_resource provisioner):
#   NCC_ID, RULE_ID                            — the rule to enable
#   DATABRICKS_HOST, DATABRICKS_ACCOUNT_ID     — account-level CLI target
#   DATABRICKS_CLIENT_ID, DATABRICKS_CLIENT_SECRET — inherited from shell
#
# Polls every 10s up to 10 minutes (60 attempts) for ESTABLISHED, then sends
# update with --update-mask=enabled --enabled. Exits 0 on success, 1 on
# timeout or terminal failure state.

set -euo pipefail

: "${NCC_ID:?must be set by null_resource environment}"
: "${RULE_ID:?must be set by null_resource environment}"
: "${DATABRICKS_HOST:?must be set by null_resource environment}"
: "${DATABRICKS_ACCOUNT_ID:?must be set by null_resource environment}"
: "${DATABRICKS_CLIENT_ID:?must be exported in your shell}"
: "${DATABRICKS_CLIENT_SECRET:?must be exported in your shell}"

STATE="UNKNOWN"
for i in $(seq 1 60); do
  STATE=$(databricks account network-connectivity get-private-endpoint-rule \
    "$NCC_ID" "$RULE_ID" --output json | jq -r '.connection_state // "UNKNOWN"')
  echo "[enable-s3-rule] connection_state=$STATE (attempt $i/60)" >&2
  case "$STATE" in
    ESTABLISHED)
      break
      ;;
    REJECTED|DISCONNECTED|EXPIRED)
      echo "[enable-s3-rule] connection_state=$STATE is terminal, cannot enable rule" >&2
      exit 1
      ;;
  esac
  sleep 10
done

if [ "$STATE" != "ESTABLISHED" ]; then
  echo "[enable-s3-rule] connection_state did not reach ESTABLISHED after ~10 minutes (last: $STATE)" >&2
  exit 1
fi

# Send update. UPDATE_MASK is positional; --enabled (a boolean flag) sets
# the rule to enabled=true.
databricks account network-connectivity update-private-endpoint-rule \
  "$NCC_ID" "$RULE_ID" enabled --enabled >&2

echo "[enable-s3-rule] rule enabled successfully" >&2
