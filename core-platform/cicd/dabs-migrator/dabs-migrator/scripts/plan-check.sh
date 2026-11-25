#!/usr/bin/env bash
# scripts/plan-check.sh
#
# Safety gate between `databricks bundle plan` and `databricks bundle deploy` for staging and prod.
# Runs the plan, prints every planned change (with old and new values), and fails closed.
# Nothing is deployed by this script.
#
# Usage:
#   bash scripts/plan-check.sh <target> [--first-deploy] [--profile <name>]
#
# Modes:
#   --first-deploy  The one-time bind-and-deploy run on a staging or prod source workspace.
#                   Fails on:
#                     - any delete, recreate or update_id (the existing asset would be replaced or removed)
#                     - any create of a key listed in bindings/<target>.yml (missed bind)
#                     - any other create, unless approved in plan-allow/<target>.txt
#                     - changes to run_as, schedules/triggers, catalog/schema, storage or notifications
#                       of an existing asset, unless approved in plan-allow/<target>.txt
#   (default)       Recurring staging and prod deploys. Fails on any delete, recreate or update_id
#                   unless approved. Creates and other updates are listed; sensitive changes are flagged.
#
# Approvals: plan-allow/<target>.txt, reviewed in a pull request. One entry per line:
#   create   resources.jobs.new_job
#   delete   resources.jobs.old_job
#   recreate resources.pipelines.etl
#   change   resources.jobs.etl schedule
# Lines starting with # are comments. Remove entries after the deploy that needed them.
#
# Output: the full plan is saved to plan-<target>.json. Keep it as a CI artifact; do not commit it.
#
# Requires: bash 3.2+, jq, Databricks CLI with `bundle plan -o json` (plan_version 2).

set -euo pipefail

usage() { echo "Usage: bash scripts/plan-check.sh <target> [--first-deploy] [--profile <name>]" >&2; exit 2; }

TARGET="${1:-}"
[[ -z "$TARGET" ]] && usage
shift
MODE="recurring"
PROFILE_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --first-deploy) MODE="first-deploy"; shift ;;
    --profile) [[ $# -ge 2 ]] || usage; PROFILE_ARGS=(--profile "$2"); shift 2 ;;
    *) echo "Unknown argument: $1" >&2; usage ;;
  esac
done

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq is required (Linux: apt-get install -y jq, macOS: brew install jq)." >&2
  exit 1
fi

PLAN_FILE="plan-${TARGET}.json"
ERR_FILE="plan-${TARGET}.err"
ALLOW_FILE="plan-allow/${TARGET}.txt"
BINDINGS_FILE="bindings/${TARGET}.yml"
SENSITIVE='^(run_as|schedule|trigger|continuous|catalog|schema|target|storage|root_path|event_log|email_notifications|webhook_notifications|notification_settings|notifications)$'

# --- 1. Run the plan. If the plan itself fails, show why and stop. ---
if ! databricks bundle plan -t "$TARGET" ${PROFILE_ARGS[@]+"${PROFILE_ARGS[@]}"} -o json >"$PLAN_FILE" 2>"$ERR_FILE"; then
  cat "$ERR_FILE" >&2
  echo "ERROR: 'databricks bundle plan' failed for target '$TARGET'. Nothing was deployed." >&2
  exit 1
fi
if [[ -s "$ERR_FILE" ]]; then
  cat "$ERR_FILE" >&2
fi

# --- 2. Fail closed on unexpected output (a jq error must never count as "no problems"). ---
if ! jq -e '(.plan_version == 2) and ((.plan // {}) | type == "object")' "$PLAN_FILE" >/dev/null; then
  echo "ERROR: unexpected output in $PLAN_FILE (expected plan_version 2 with a .plan object)." >&2
  echo "  Failing closed. Check the CLI version (bundle plan -o json, direct deployment engine)." >&2
  exit 1
fi

allowed() {
  # allowed <action> <plan_key> [field]
  [[ -f "$ALLOW_FILE" ]] || return 1
  local want="$1 $2"
  [[ -n "${3:-}" ]] && want="$want $3"
  sed -e 's/#.*//' -e 's/[[:space:]][[:space:]]*/ /g' -e 's/^ //' -e 's/ $//' "$ALLOW_FILE" | grep -qxF -- "$want"
}

is_bound() {
  # is_bound <resource_key>: the key is listed in bindings/<target>.yml
  [[ -f "$BINDINGS_FILE" ]] || return 1
  sed -e 's/#.*//' "$BINDINGS_FILE" | cut -d: -f1 | tr -d ' "' | grep -qxF -- "$1"
}

FAIL=0
blocked() { echo "    BLOCKED: $*" >&2; FAIL=1; }

echo "Plan for target '$TARGET' (mode: $MODE). Full plan: $PLAN_FILE"

ENTRIES=$(jq -r '(.plan // {}) | to_entries[]
  | [.key, (.value.action // ""), (((.value.state_only // false) or (.value.gone // false)) | tostring)]
  | @tsv' "$PLAN_FILE")

while IFS=$'\t' read -r key action state_only; do
  [[ -z "$key" ]] && continue
  [[ "$action" == "skip" || -z "$action" ]] && continue

  # Plan keys look like resources.<type>.<key> (resource) or resources.<type>.<key>.<child> (e.g. permissions).
  name=$(printf '%s' "$key" | cut -d. -f3)
  parts=$(printf '%s' "$key" | awk -F. '{print NF}')
  echo "  $action  $key"

  case "$action" in
    delete)
      [[ "$state_only" == "true" ]] && continue
      allowed delete "$key" || blocked "$key would be DELETED. If intended, add 'delete $key' to $ALLOW_FILE in a reviewed PR."
      ;;
    recreate|update_id)
      allowed recreate "$key" || blocked "$key would be REPLACED ($action): the existing asset (and, for pipelines, its tables) is removed. Fix the YAML to match the asset, or add 'recreate $key' to $ALLOW_FILE in a reviewed PR."
      ;;
    create)
      if [[ "$parts" -eq 3 ]] && is_bound "$name"; then
        blocked "$key is listed in $BINDINGS_FILE but plans as create: the bind did not take. Nothing was deployed."
      elif [[ "$MODE" == "first-deploy" && "$parts" -eq 3 ]] && ! allowed create "$key"; then
        blocked "$key would be CREATED as a new asset in $TARGET. If it really is new, add 'create $key' to $ALLOW_FILE; if it already exists, add its ID to $BINDINGS_FILE."
      fi
      ;;
    update|resize)
      jq -r --arg k "$key" '(.plan[$k].changes // {}) | to_entries[] | select(.value.action != "skip")
        | "      \(.key): \((.value.remote // .value.old) | tojson) -> \(.value.new | tojson)"' "$PLAN_FILE"
      while IFS= read -r field; do
        [[ -z "$field" ]] && continue
        top="${field%%.*}"
        top="${top%%\[*}"
        if [[ "$top" =~ $SENSITIVE ]]; then
          if [[ "$MODE" == "first-deploy" ]] && ! allowed change "$key" "$top"; then
            blocked "$key: '$field' changes on the existing asset. Make the YAML match the live asset, or add 'change $key $top' to $ALLOW_FILE in a reviewed PR."
          elif [[ "$MODE" != "first-deploy" ]]; then
            echo "    NOTE: sensitive field '$field' changes on $key." >&2
          fi
        fi
      done < <(jq -r --arg k "$key" '(.plan[$k].changes // {}) | to_entries[] | select(.value.action != "skip") | .key' "$PLAN_FILE")
      ;;
    *)
      blocked "$key has an unknown plan action '$action'. Failing closed."
      ;;
  esac
done <<< "$ENTRIES"

if [[ $FAIL -ne 0 ]]; then
  echo "" >&2
  echo "ERROR: plan check failed for '$TARGET'. Nothing was deployed. Review $PLAN_FILE and the BLOCKED lines above." >&2
  exit 1
fi

echo "Plan check passed for '$TARGET'."
