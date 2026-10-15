#!/bin/bash
# usage: HOST=https://<workspace-host> TOKEN_FILE=<file with the test SP access token> ./call.sh <model>
# Calls a system.ai model service. 200 = access. 404 "does not exist" = no access.
curl -s -o /tmp/ug_body -w '%{http_code}' \
  -H "Authorization: Bearer $(cat "$TOKEN_FILE")" -H 'Content-Type: application/json' \
  "$HOST/ai-gateway/mlflow/v1/chat/completions" \
  -d "{\"model\":\"system.ai.$1\",\"messages\":[{\"role\":\"user\",\"content\":\"Say OK\"}],\"max_tokens\":5}"
echo "  $1  $(head -c 120 /tmp/ug_body)"
