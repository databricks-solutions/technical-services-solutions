#!/usr/bin/env bash
# scripts/auto-bind.sh
#
# Auto-discovers existing workspace resources by name and binds them to the bundle.
# Run once before the first deploy to a staging or prod source workspace.
#
# How it works:
#   1. Reads resolved resource names from `databricks bundle validate -t <target>`.
#   2. For each job/pipeline, searches the target workspace for a resource with that exact name.
#   3. Exactly one match  → binds it (`bundle deployment bind`).
#      No match           → skips; the first `bundle deploy` will create it as a new resource.
#      Multiple matches   → exits with error; resolve the correct ID manually (see below).
#   4. Writes bindings/<target>.yml as an audit trail of what was auto-bound — commit this file.
#
# Supported resource types: jobs, pipelines
# Unity Catalog resources (schemas, volumes, catalogs, registered_models, etc.) are not
# auto-discovered. Add them manually to bindings/<target>.yml before running, then bind with:
#   databricks bundle deployment bind <key> <bind_id> -t <target> --auto-approve
#
# Re-run safety: if bindings/<target>.yml already contains a key it is skipped (already bound).
#
# Prerequisites:
#   - Databricks CLI installed and authenticated to the target workspace
#     (DATABRICKS_HOST, DATABRICKS_CLIENT_ID, DATABRICKS_CLIENT_SECRET set, or --profile used)
#   - jq installed (available by default on GitHub Actions, Azure DevOps, GitLab CI runners)
#
# Usage:
#   bash scripts/auto-bind.sh <target>
#   bash scripts/auto-bind.sh <target> --profile <profile_name>

set -euo pipefail

TARGET="${1:?Usage: bash scripts/auto-bind.sh <target> [--profile <name>]}"
PROFILE_FLAG=""
shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) PROFILE_FLAG="--profile $2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

# --- Guardrails ---

if ! command -v jq &>/dev/null; then
  echo "ERROR: jq is required." >&2
  echo "  Linux:  apt-get install -y jq" >&2
  echo "  macOS:  brew install jq" >&2
  exit 1
fi

if [[ "$TARGET" == "dev" ]]; then
  echo "ERROR: auto-bind.sh must not run against the 'dev' target." >&2
  echo "Dev deployments intentionally create a new isolated copy — no bind needed." >&2
  exit 1
fi

echo "════════════════════════════════════════════════════════════"
echo " dabs-migrator: auto-bind — target: $TARGET"
echo "════════════════════════════════════════════════════════════"
echo ""

# --- Step 1: Get resolved resource names from the bundle ---

echo "▶ 1/3  Validating bundle for target '$TARGET' …"
BUNDLE_JSON=$(databricks bundle validate -t "$TARGET" $PROFILE_FLAG --output json 2>/dev/null) || {
  echo "ERROR: 'databricks bundle validate' failed. Fix validation errors before binding." >&2
  exit 1
}

# --- Step 2: Fetch all workspace resources once ---

echo "▶ 2/3  Querying workspace …"
ALL_JOBS=$(databricks jobs list $PROFILE_FLAG -o json 2>/dev/null)
ALL_PIPELINES=$(databricks pipelines list-pipelines $PROFILE_FLAG -o json 2>/dev/null)

# --- Step 3: Discover and bind ---

echo "▶ 3/3  Discovering and binding …"
echo ""

BIND_COUNT=0
NEW_COUNT=0
AMBIGUOUS=0
BOUND_KEYS=()
BOUND_IDS=()

already_bound() {
  local key="$1"
  [[ -f "bindings/${TARGET}.yml" ]] && grep -qE "^${key}:" "bindings/${TARGET}.yml" 2>/dev/null
}

bind_one() {
  local type="$1" key="$2" name="$3" count="$4" id="${5:-}"
  if already_bound "$key"; then
    echo "  ⏭   $type.$key  '$name'  already in bindings/${TARGET}.yml — skipping"
    return
  fi
  if   [[ "$count" -eq 1 ]]; then
    echo "  ✅  $type.$key  '$name'  →  $id  (binding …)"
    databricks bundle deployment bind "$key" "$id" -t "$TARGET" $PROFILE_FLAG --auto-approve
    BOUND_KEYS+=("$key")
    BOUND_IDS+=("$id")
    ((BIND_COUNT++)) || true
  elif [[ "$count" -eq 0 ]]; then
    echo "  ➕  $type.$key  '$name'  not found in workspace — will be created on first deploy"
    ((NEW_COUNT++)) || true
  else
    echo "  ⚠️   $type.$key  '$name'  — $count matches found, resolve manually (see script header)"
    ((AMBIGUOUS++)) || true
  fi
}

# Jobs
while IFS= read -r key; do
  name=$(echo "$BUNDLE_JSON" | jq -r ".resources.jobs.\"$key\".name // empty")
  [[ -z "$name" ]] && continue
  matches=$(echo "$ALL_JOBS" | jq -c "[.jobs // [] | .[] | select(.settings.name == \"$name\")]")
  count=$(echo "$matches" | jq 'length')
  id=""; [[ "$count" -eq 1 ]] && id=$(echo "$matches" | jq -r '.[0].job_id')
  bind_one "jobs" "$key" "$name" "$count" "$id"
done < <(echo "$BUNDLE_JSON" | jq -r '.resources.jobs // {} | keys[]' 2>/dev/null || true)

# Pipelines
while IFS= read -r key; do
  name=$(echo "$BUNDLE_JSON" | jq -r ".resources.pipelines.\"$key\".name // empty")
  [[ -z "$name" ]] && continue
  matches=$(echo "$ALL_PIPELINES" | jq -c "[.statuses // [] | .[] | select(.name == \"$name\")]")
  count=$(echo "$matches" | jq 'length')
  id=""; [[ "$count" -eq 1 ]] && id=$(echo "$matches" | jq -r '.[0].pipeline_id')
  bind_one "pipelines" "$key" "$name" "$count" "$id"
done < <(echo "$BUNDLE_JSON" | jq -r '.resources.pipelines // {} | keys[]' 2>/dev/null || true)

# --- Write / update bindings audit trail ---

if [[ $BIND_COUNT -gt 0 ]]; then
  mkdir -p bindings
  {
    if [[ -f "bindings/${TARGET}.yml" ]]; then
      # Preserve existing entries (already-bound resources)
      grep -v '^#' "bindings/${TARGET}.yml" 2>/dev/null || true
    fi
    printf '# Auto-generated by scripts/auto-bind.sh — %s — target: %s\n' \
      "$(date -u +%Y-%m-%dT%H:%MZ)" "$TARGET"
    for i in "${!BOUND_KEYS[@]}"; do
      printf '%s: "%s"\n' "${BOUND_KEYS[$i]}" "${BOUND_IDS[$i]}"
    done
  } > "bindings/${TARGET}.yml.tmp" && mv "bindings/${TARGET}.yml.tmp" "bindings/${TARGET}.yml"
  echo ""
  echo "▶ Wrote bindings/${TARGET}.yml — commit this file as an audit trail."
fi

# --- Summary ---

echo ""
echo "════════════════════════════════════════════════════════════"
printf "  Bound this run:    %d resource(s)\n"  "$BIND_COUNT"
printf "  Will create new:   %d resource(s)\n"  "$NEW_COUNT"
printf "  Ambiguous (error): %d resource(s)\n"  "$AMBIGUOUS"
echo "════════════════════════════════════════════════════════════"

if [[ $AMBIGUOUS -gt 0 ]]; then
  echo "" >&2
  echo "ERROR: $AMBIGUOUS resource(s) matched multiple workspace assets with the same name." >&2
  echo "Resolve each manually:" >&2
  echo "  1. Identify the correct resource in the Databricks UI or via the CLI." >&2
  echo "  2. databricks bundle deployment bind <key> <id> -t $TARGET --auto-approve" >&2
  echo "  3. Add the line   <key>: \"<id>\"   to bindings/${TARGET}.yml manually." >&2
  exit 1
fi

echo ""
echo "✅  Done. Next step: databricks bundle plan -t $TARGET"
