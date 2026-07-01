#!/usr/bin/env bash
#
# Databricks Terraform Pre-Check — one-command runner (macOS / Linux).
#
# This does the whole setup for you: it creates a local Python environment,
# installs what it needs, asks two or three questions, runs the check, and
# writes a report.md you can send back to your Databricks contact.
#
#   ./run.sh                                   # interactive (recommended)
#   ./run.sh --cloud aws --region us-east-1    # advanced: pass flags straight through
#
# Requirements: Python 3.10+ and you must already be logged in to your cloud
# CLI (aws configure / az login / gcloud auth application-default login).

set -euo pipefail

# Always run from the folder this script lives in.
cd "$(dirname "$0")"

# --- 1. Find a suitable Python (3.10+) -------------------------------------
find_python() {
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
        echo "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON="$(find_python || true)"
if [ -z "$PYTHON" ]; then
  echo "ERROR: Python 3.10 or newer is required but was not found." >&2
  echo "       Install it from https://www.python.org/downloads/ and re-run ./run.sh" >&2
  exit 1
fi

# --- 2. Create / reuse the virtual environment -----------------------------
VENV_DIR="venv"
if [ ! -d "$VENV_DIR" ]; then
  echo "→ Creating Python virtual environment (one-time setup)..."
  "$PYTHON" -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# --- 3. Install dependencies (only when needed) ----------------------------
# A marker file lets us skip reinstalling on every run. We reinstall if the
# requirements file has changed since the last successful install.
MARKER="$VENV_DIR/.deps-installed"
if [ ! -f "$MARKER" ] || [ requirements.txt -nt "$MARKER" ]; then
  echo "→ Installing dependencies (one-time, ~1–2 min)..."
  pip install --quiet --upgrade pip
  pip install --quiet -r requirements.txt
  touch "$MARKER"
fi

# --- 4. Gather inputs ------------------------------------------------------
if [ "$#" -gt 0 ]; then
  # Advanced mode: forward whatever flags the caller passed, untouched.
  ARGS=("$@")
else
  echo
  echo "Which cloud is your Databricks workspace being deployed to?"
  read -rp "  aws / azure / gcp: " CLOUD
  CLOUD="$(echo "$CLOUD" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"

  ARGS=(--cloud "$CLOUD")

  case "$CLOUD" in
    aws)
      read -rp "  AWS region (e.g. us-east-1): " REGION
      while [ -z "$REGION" ]; do read -rp "  Region cannot be empty. AWS region: " REGION; done
      ARGS+=(--region "$REGION")
      ;;
    azure)
      read -rp "  Azure subscription ID: " SUB
      while [ -z "$SUB" ]; do read -rp "  Subscription ID cannot be empty: " SUB; done
      read -rp "  Azure region (e.g. eastus): " REGION
      while [ -z "$REGION" ]; do read -rp "  Region cannot be empty. Azure region: " REGION; done
      ARGS+=(--subscription-id "$SUB" --region "$REGION")
      ;;
    gcp)
      read -rp "  GCP project ID: " PROJECT
      while [ -z "$PROJECT" ]; do read -rp "  Project ID cannot be empty: " PROJECT; done
      read -rp "  GCP region (e.g. us-central1): " REGION
      while [ -z "$REGION" ]; do read -rp "  Region cannot be empty. GCP region: " REGION; done
      ARGS+=(--project "$PROJECT" --region "$REGION")
      ;;
    *)
      echo "ERROR: unknown cloud '$CLOUD' (expected aws, azure, or gcp)." >&2
      exit 1
      ;;
  esac

  echo
  echo "How would you like to run the check?"
  echo
  echo "  1) Dry run  — Preview only. Shows exactly what the full run WOULD"
  echo "               create and test. NOTHING is created in your account and"
  echo "               no changes are made. Good for a first look."
  echo
  echo "  2) Full run — Creates small, clearly-tagged temporary resources"
  echo "               (dbxprecheck-* / dbx-precheck-temp-*), verifies your"
  echo "               permissions, then DELETES them. On Azure this briefly"
  echo "               includes a NAT Gateway + Public IP (a few cents). This is"
  echo "               the real check and produces the report.md you send back."
  echo "               [recommended]"
  echo
  echo "  (GCP is always read-only — it never creates anything, in either mode.)"
  echo
  read -rp "Choose 1 or 2 (default 2): " MODE
  MODE="$(echo "$MODE" | tr -d '[:space:]')"

  if [ "$MODE" = "1" ]; then
    RUN_MODE="dryrun"
    ARGS+=(--dry-run)
  else
    RUN_MODE="full"
    # Produce the customer-friendly report file to send back.
    ARGS+=(--format markdown --output report.md)
  fi
fi

# --- 5. Run ----------------------------------------------------------------
echo
echo "→ Running the pre-check..."
# The tool exits non-zero when it finds blockers; that's expected, so don't let
# it abort the script before we point you at the report.
python main.py "${ARGS[@]}" || true

echo
if [ "${RUN_MODE:-}" = "dryrun" ]; then
  echo "✓ That was a PREVIEW (dry run) — nothing was created in your account."
  echo "  When you're ready for the real check, run ./run.sh again and choose"
  echo "  option 2 (Full run). It creates, verifies, and deletes the temporary"
  echo "  resources and writes the report.md you send back."
elif [ -f report.md ]; then
  echo "✓ Done. Your report is here:"
  echo "    $(pwd)/report.md"
  echo
  echo "  Please send report.md back to your Databricks contact."
else
  echo "The run finished but no report.md was produced — check the output above."
fi
