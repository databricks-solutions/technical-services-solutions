#!/usr/bin/env bash
# scripts/auto-bind.sh
#
# Binds bundle resources to their existing workspace counterparts before the first deploy.
# Run once before the first deploy to a staging or prod source workspace.
#
# PRIMARY path: binds by explicit ID from bindings/<target>.yml (populated during migration step 4).
# FALLBACK: for resources not listed in bindings/<target>.yml, searches by name.
#   - 1 match, interactive  → prompts for confirmation.
#   - 1 match, CI (no TTY)  → FAILS unless CONFIRM_NAME_FALLBACK=yes is set.
#     Skipping would silently create a duplicate on the next deploy; failing is safer.
#   - 1 match, CONFIRM_NAME_FALLBACK=yes → binds automatically (dangerous: verify the ID first).
#   - 0 matches → skips; the first `bundle deploy` will create a new resource.
#   - 2+ matches → fails with instructions to add the correct ID to bindings/<target>.yml manually.
#
# Why bind by ID, not name: a workspace may have multiple jobs with the same name. Binding by name
# silently picks one; the plan check then passes (shows "update") even if it's the wrong asset.
# Explicit IDs from step 4 eliminate this ambiguity. Name lookup is only a fallback for gaps.
#
# Re-run safety: resources already listed in bindings/<target>.yml are re-bound by ID; if the CLI
# reports "already managed", the actual bound ID is read from the bundle state file.
#
# Prerequisites:
#   - Databricks CLI installed and authenticated to the target workspace
#     (DATABRICKS_HOST, DATABRICKS_CLIENT_ID, DATABRICKS_CLIENT_SECRET set, or --profile used)
#   - jq installed (available by default on GitHub Actions, Azure DevOps, GitLab CI runners)
#
# Usage:
#   bash scripts/auto-bind.sh <target> [--profile <name>]
#   CONFIRM_NAME_FALLBACK=yes bash scripts/auto-bind.sh <target>  # auto-approve name fallbacks in CI

set -euo pipefail

# Require bash 4+ for associative arrays (declare -A).
# macOS ships bash 3.2 — install a newer shell with: brew install bash
if [[ "${BASH_VERSINFO[0]}" -lt 4 ]]; then
  echo "ERROR: bash 4+ is required (current: $BASH_VERSION)." >&2
  echo "  macOS: brew install bash" >&2
  echo "  Then run: /opt/homebrew/bin/bash scripts/auto-bind.sh $*" >&2
  exit 1
fi

TARGET="${1:?Usage: bash scripts/auto-bind.sh <target> [--profile <name>]}"
PROFILE_FLAG=""
shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) PROFILE_FLAG="--profile $2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

BINDINGS_FILE="bindings/${TARGET}.yml"

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

# --- Step 1: Validate bundle to get resolved resource names ---

echo "▶ 1/3  Validating bundle …"
BUNDLE_JSON=$(databricks bundle validate -t "$TARGET" $PROFILE_FLAG --output json 2>/dev/null) || {
  echo "ERROR: 'databricks bundle validate' failed. Fix validation errors before binding." >&2
  exit 1
}

# --- Step 2: Fetch workspace resources for the name-fallback path ---

echo "▶ 2/3  Querying workspace …"
ALL_JOBS=$(databricks jobs list $PROFILE_FLAG -o json 2>/dev/null)
ALL_PIPELINES=$(databricks pipelines list-pipelines $PROFILE_FLAG -o json 2>/dev/null)

# --- Load explicit IDs from bindings file (primary source) ---

declare -A BINDINGS_MAP   # key → bind_id
if [[ -f "$BINDINGS_FILE" ]]; then
  while IFS= read -r line; do
    [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
    key=$(echo "$line" | cut -d: -f1 | tr -d ' ')
    bind_id=$(echo "$line" | cut -d: -f2- | tr -d ' "')
    [[ -n "$key" && -n "$bind_id" ]] && BINDINGS_MAP["$key"]="$bind_id"
  done < "$BINDINGS_FILE"
  echo "   Loaded ${#BINDINGS_MAP[@]} explicit ID(s) from $BINDINGS_FILE."
fi

echo "▶ 3/3  Binding …"
echo ""

BIND_COUNT=0
NEW_COUNT=0
AMBIGUOUS=0
declare -A RESULT_MAP   # key → actual_id (for audit trail)

# Helper: execute bind and handle errors
run_bind() {
  local key="$1" bind_id="$2"
  local out exit_code=0
  out=$(databricks bundle deployment bind "$key" "$bind_id" \
        -t "$TARGET" $PROFILE_FLAG --auto-approve 2>&1) || exit_code=$?

  if [[ $exit_code -ne 0 ]]; then
    if echo "$out" | grep -qi "already managed"; then
      # Resource is already tracked in the bundle's workspace state.
      # Read the actual bound ID from the local state file (more reliable than the found ID).
      local state_file=".databricks/bundle/${TARGET}/resources.json"
      local actual_id="$bind_id"
      if [[ -f "$state_file" ]]; then
        local state_id
        state_id=$(jq -r --arg k "$key" \
          '.state | to_entries[] | select(.key | endswith("." + $k)) | .value.__id__ // empty' \
          "$state_file" 2>/dev/null | head -1)
        [[ -n "$state_id" ]] && actual_id="$state_id"
      fi
      echo "  ⏭   $key  already managed in bundle state (ID: $actual_id)"
      RESULT_MAP["$key"]="$actual_id"
    else
      printf '%s\n' "$out" >&2
      echo "  ERROR: 'bundle deployment bind' failed for '$key' (exit $exit_code)." >&2
      exit 1
    fi
  else
    printf '%s\n' "$out"
    RESULT_MAP["$key"]="$bind_id"
  fi
  ((BIND_COUNT++)) || true
}

# --- PRIMARY: bind each key in bindings/<target>.yml by its explicit ID ---

for key in "${!BINDINGS_MAP[@]}"; do
  bind_id="${BINDINGS_MAP[$key]}"
  echo "  ✅  $key  →  $bind_id  (explicit ID)"
  run_bind "$key" "$bind_id"
done

# --- FALLBACK: name lookup for bundle resources not in bindings/<target>.yml ---

name_fallback() {
  local type="$1" key="$2" name="$3" count="$4" found_id="${5:-}"

  # Already handled via bindings file
  [[ -n "${BINDINGS_MAP[$key]+set}" ]] && return

  if [[ "$count" -eq 1 ]]; then
    echo ""
    echo "  ⚠️  $type.$key  '$name'  found by name (ID: $found_id) — not in $BINDINGS_FILE."
    echo "     Verify this is the correct asset. To confirm: add  $key: \"$found_id\"  to $BINDINGS_FILE."

    local proceed=0
    if [[ -t 0 ]]; then
      read -r -p "     Bind now? [y/N] " resp
      [[ "$resp" =~ ^[Yy]$ ]] && proceed=1
    elif [[ "${CONFIRM_NAME_FALLBACK:-}" == "yes" ]]; then
      echo "     CONFIRM_NAME_FALLBACK=yes — proceeding."
      proceed=1
    else
      # Non-interactive without CONFIRM_NAME_FALLBACK=yes: fail rather than skip.
      # Skipping would let bundle deploy create a duplicate resource in staging/prod,
      # and the plan check wouldn't catch it (the key isn't in bindings/).
      echo "" >&2
      echo "ERROR: '$key' was found by name but is not listed in $BINDINGS_FILE." >&2
      echo "  In non-interactive mode this is an error — skipping would create a duplicate" >&2
      echo "  on the next deploy, and the plan check would not catch it." >&2
      echo "  Fix: add   $key: \"$found_id\"   to $BINDINGS_FILE and re-run." >&2
      echo "  Or set CONFIRM_NAME_FALLBACK=yes to auto-approve (verify the ID is correct first)." >&2
      exit 1
    fi

    if [[ $proceed -eq 1 ]]; then
      echo "  ✅  $type.$key  →  $found_id  (name fallback)"
      run_bind "$key" "$found_id"
    else
      echo "  ↩  $type.$key  skipped."
      ((NEW_COUNT++)) || true
    fi

  elif [[ "$count" -eq 0 ]]; then
    echo "  ➕  $type.$key  '$name'  not found in workspace — will be created on first deploy"
    ((NEW_COUNT++)) || true

  else
    echo "  ⚠️  $type.$key  '$name'  — $count matches found. Add correct ID to $BINDINGS_FILE manually."
    ((AMBIGUOUS++)) || true
  fi
}

# Jobs fallback
while IFS= read -r key; do
  [[ -n "${BINDINGS_MAP[$key]+set}" ]] && continue   # already handled
  name=$(echo "$BUNDLE_JSON" | jq -r ".resources.jobs.\"$key\".name // empty")
  [[ -z "$name" ]] && continue
  matches=$(echo "$ALL_JOBS" | jq --arg n "$name" -c '[.[] | select(.settings.name == $n)]')
  count=$(echo "$matches" | jq 'length')
  id=""; [[ "$count" -eq 1 ]] && id=$(echo "$matches" | jq -r '.[0].job_id')
  name_fallback "jobs" "$key" "$name" "$count" "$id"
done < <(echo "$BUNDLE_JSON" | jq -r '.resources.jobs // {} | keys[]' 2>/dev/null || true)

# Pipelines fallback
while IFS= read -r key; do
  [[ -n "${BINDINGS_MAP[$key]+set}" ]] && continue
  name=$(echo "$BUNDLE_JSON" | jq -r ".resources.pipelines.\"$key\".name // empty")
  [[ -z "$name" ]] && continue
  matches=$(echo "$ALL_PIPELINES" | jq --arg n "$name" -c '[.[] | select(.name == $n)]')
  count=$(echo "$matches" | jq 'length')
  id=""; [[ "$count" -eq 1 ]] && id=$(echo "$matches" | jq -r '.[0].pipeline_id')
  name_fallback "pipelines" "$key" "$name" "$count" "$id"
done < <(echo "$BUNDLE_JSON" | jq -r '.resources.pipelines // {} | keys[]' 2>/dev/null || true)

# --- Write / update bindings audit trail ---

if [[ ${#RESULT_MAP[@]} -gt 0 ]]; then
  mkdir -p bindings
  {
    printf '# Auto-generated by scripts/auto-bind.sh — %s — target: %s\n' \
      "$(date -u +%Y-%m-%dT%H:%MZ)" "$TARGET"
    printf '# Commit this file as an audit trail of what was bound at migration time.\n'
    for key in "${!RESULT_MAP[@]}"; do
      printf '%s: "%s"\n' "$key" "${RESULT_MAP[$key]}"
    done
    # Preserve any explicit-ID entries not re-processed (e.g. UC resource types)
    for key in "${!BINDINGS_MAP[@]}"; do
      [[ -n "${RESULT_MAP[$key]+set}" ]] && continue
      printf '%s: "%s"\n' "$key" "${BINDINGS_MAP[$key]}"
    done
  } > "${BINDINGS_FILE}.tmp" && mv "${BINDINGS_FILE}.tmp" "$BINDINGS_FILE"
  echo ""
  echo "▶ Wrote $BINDINGS_FILE — commit this file."
fi

# --- Summary ---

echo ""
echo "════════════════════════════════════════════════════════════"
printf "  Bound this run:    %d resource(s)\n" "$BIND_COUNT"
printf "  Will create new:   %d resource(s)\n" "$NEW_COUNT"
printf "  Ambiguous (error): %d resource(s)\n" "$AMBIGUOUS"
echo "════════════════════════════════════════════════════════════"

if [[ $AMBIGUOUS -gt 0 ]]; then
  echo "" >&2
  echo "ERROR: $AMBIGUOUS resource(s) matched multiple workspace assets with the same name." >&2
  echo "Resolve each manually: add the correct  <key>: \"<id>\"  entry to $BINDINGS_FILE." >&2
  exit 1
fi

echo ""
echo "✅  Done. Next step: databricks bundle plan -t $TARGET -o json"
