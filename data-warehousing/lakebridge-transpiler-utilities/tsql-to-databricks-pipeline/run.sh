#!/bin/bash
# End-to-end T-SQL (SQL Server / mssql) to Databricks using Lakebridge.
#
# Two output modes (--switch-style):
#   sdp  — Lakeflow Declarative Pipeline with SQL (LDP SQL) notebooks
#   sql  — SQL .sql FILE objects + SQL Warehouse Job (BladeBridge off by default)
#
# Steps:
#   1. Install BladeBridge and/or Switch LLM transpiler
#   2. (Optional) Run BladeBridge on .sql source files
#   3. Stage .sql files for Switch LLM; preserve first_pass/ copy of BladeBridge output
#   4. Upload custom Switch prompt and update switch_config.yml
#   5. Run Switch LLM (llm-transpile); optionally wait for completion
#   6. sdp: Create Lakeflow Declarative Pipeline
#      sql: Create Databricks SQL Warehouse Job
#
# Default prompts are alongside this script; -x overrides the prompt.
#
# Usage:
#   ./run.sh [options]
#
# Options:
#   -i, --input-source        Path to a .sql file or directory of .sql files
#   -o, --output-folder       Local staging folder for conversion output
#   -w, --output-ws-folder    Workspace folder for converted files (must start with /Workspace/)
#   -e, --user-email          User email override (default: auto-detected from Databricks profile)
#   -p, --profile             Databricks CLI profile (default: DEFAULT)
#   -c, --catalog             UC catalog for Switch artifacts (required)
#   -s, --schema              Schema for Switch artifacts (default: switch)
#   -v, --volume              UC Volume name (default: switch_volume)
#   -m, --foundation-model    Foundation model endpoint (default: databricks-claude-sonnet-4-5)
#       --switch-style        Output mode: sdp (Lakeflow SQL pipeline) or sql (FILE + SQL Warehouse Job) [default: sdp]
#   -x, --custom-prompt       Custom Switch prompt YAML (default: from --switch-style in script dir)
#   -r, --overrides-file      BladeBridge override JSON (default: sample_override_tsql.json in script dir)
#       --error-file-path     BladeBridge conversion error log (default: <output-folder>/errors.log)
#       --transpiler-config-path   BladeBridge config path (default: ~/.databricks/labs/.../config.yml)
#       --no-transpiler-config-path  Do not pass --transpiler-config-path to BladeBridge
#       --pipeline-catalog    Lakeflow DLP catalog (sdp only; default: same as -c/--catalog)
#       --pipeline-target     Lakeflow DLP target schema (sdp only; default: default)
#       --pipeline-name       Lakeflow pipeline name (sdp only; default: derived from first .sql basename)
#       --cluster-policy      Cluster policy ID for pipeline compute (sdp only; omit for serverless)
#       --warehouse-id        SQL warehouse ID (sql only; default: interactive selection)
#       --job-name            SQL Warehouse Job name (sql only; default: derived from .sql basename)
#       --skip-job-create     Skip Step 6 SQL Warehouse Job creation (sql only)
#       --single-catalog      All data layers share the same catalog as Switch artifacts
#       --wait                Wait for Switch LLM to complete before finishing (default: async)
#       --skip-det-install    Skip BladeBridge installation
#       --skip-llm-install    Skip Switch LLM installation
#       --skip-bladebridge    Skip BladeBridge step entirely
#       --skip-switch         Skip Switch LLM entirely (no LLM step; no Step 6)
#   -y, --yes                 Non-interactive: skip all prompts, accept defaults
#   -h, --help                Show this help message
#
# All flags are prompted interactively if not provided (unless -y/--yes).

set -euo pipefail

CLEANUP_FILES=()
cleanup() {
    for f in "${CLEANUP_FILES[@]:-}"; do
        [[ -n "$f" ]] && rm -rf "$f" 2>/dev/null || true
    done
}
trap cleanup EXIT

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEFAULT_TRANSPILER_CONFIG_PATH="${HOME}/.databricks/labs/remorph-transpilers/bladebridge/lib/config.yml"

INPUT_SOURCE=""
OUTPUT_FOLDER=""
OUTPUT_WS_FOLDER=""
USER_EMAIL=""
PROFILE=""
CATALOG=""
SCHEMA=""
VOLUME=""
FOUNDATION_MODEL=""
OVERRIDES_FILE=""
ERROR_LOG_PATH=""
TRANSPILER_CONFIG_PATH=""
SKIP_TRANSPILER_CONFIG_PATH=false
CUSTOM_PROMPT=""
SWITCH_STYLE=""
PIPELINE_CATALOG=""
PIPELINE_TARGET=""
PIPELINE_NAME=""
CLUSTER_POLICY=""
USE_SERVERLESS=true
WAREHOUSE_ID=""
JOB_NAME=""
SKIP_JOB_CREATE=false
SKIP_DET_INSTALL=false
SKIP_LLM_INSTALL=false
SKIP_BLADEBRIDGE=false
SKIP_SWITCH=false
SINGLE_CATALOG=false
WAIT_FOR_SWITCH=false
YES=false

BRONZE_CATALOG=""
BRONZE_SCHEMA=""
SILVER_CATALOG=""
SILVER_SCHEMA=""
GOLD_CATALOG=""
GOLD_SCHEMA=""

usage() {
    sed -n '/^# Usage:/,/^[^#]/{ /^#/s/^# \?//p }' "$0"
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -i|--input-source)           INPUT_SOURCE="$2"; shift 2 ;;
        -o|--output-folder)          OUTPUT_FOLDER="$2"; shift 2 ;;
        -w|--output-ws-folder)       OUTPUT_WS_FOLDER="$2"; shift 2 ;;
        -e|--user-email)             USER_EMAIL="$2"; shift 2 ;;
        -p|--profile)                PROFILE="$2"; shift 2 ;;
        -c|--catalog)                CATALOG="$2"; shift 2 ;;
        -s|--schema)                 SCHEMA="$2"; shift 2 ;;
        -v|--volume)                 VOLUME="$2"; shift 2 ;;
        -m|--foundation-model)       FOUNDATION_MODEL="$2"; shift 2 ;;
        --switch-style)              SWITCH_STYLE="$2"; shift 2 ;;
        -x|--custom-prompt)          CUSTOM_PROMPT="$2"; shift 2 ;;
        -r|--overrides-file)         OVERRIDES_FILE="$2"; shift 2 ;;
        --error-file-path)           ERROR_LOG_PATH="$2"; shift 2 ;;
        --transpiler-config-path)    TRANSPILER_CONFIG_PATH="$2"; shift 2 ;;
        --no-transpiler-config-path) SKIP_TRANSPILER_CONFIG_PATH=true; shift ;;
        --pipeline-catalog)          PIPELINE_CATALOG="$2"; shift 2 ;;
        --pipeline-target)           PIPELINE_TARGET="$2"; shift 2 ;;
        --pipeline-name)             PIPELINE_NAME="$2"; shift 2 ;;
        --cluster-policy)            CLUSTER_POLICY="$2"; USE_SERVERLESS=false; shift 2 ;;
        --warehouse-id)              WAREHOUSE_ID="$2"; shift 2 ;;
        --job-name)                  JOB_NAME="$2"; shift 2 ;;
        --skip-job-create)           SKIP_JOB_CREATE=true; shift ;;
        --single-catalog)            SINGLE_CATALOG=true; shift ;;
        --wait)                      WAIT_FOR_SWITCH=true; shift ;;
        --skip-det-install)          SKIP_DET_INSTALL=true; shift ;;
        --skip-llm-install)          SKIP_LLM_INSTALL=true; shift ;;
        --skip-bladebridge)          SKIP_BLADEBRIDGE=true; SKIP_DET_INSTALL=true; shift ;;
        --skip-switch)               SKIP_SWITCH=true; SKIP_LLM_INSTALL=true; shift ;;
        -y|--yes)                    YES=true; shift ;;
        -h|--help)                   usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

if [ -n "$SWITCH_STYLE" ]; then
    _ss_lc=$(printf '%s' "$SWITCH_STYLE" | tr '[:upper:]' '[:lower:]')
    if [ "$_ss_lc" != "sdp" ] && [ "$_ss_lc" != "sql" ]; then
        echo "Error: --switch-style must be 'sdp' or 'sql' (got: ${SWITCH_STYLE})"
        exit 1
    fi
    SWITCH_STYLE="$_ss_lc"
fi

if [ -z "$OVERRIDES_FILE" ]; then
    OVERRIDES_FILE="${SCRIPT_DIR}/sample_override_tsql.json"
fi
if [ ! -f "$OVERRIDES_FILE" ]; then
    echo "Error: override file '${OVERRIDES_FILE}' not found."
    exit 1
fi

# --- Prompts ---

if [ -z "$PROFILE" ]; then
    read -rp "Databricks CLI profile [default: DEFAULT]: " PROFILE
    PROFILE="${PROFILE:-DEFAULT}"
fi

PROFILE_FLAG="-p $PROFILE"

if [ -z "$USER_EMAIL" ]; then
    echo "Detecting user email from Databricks profile '${PROFILE}'..."
    USER_EMAIL=$(databricks current-user me $PROFILE_FLAG -o json 2>/dev/null \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['userName'])" 2>/dev/null) || true
    if [ -z "$USER_EMAIL" ]; then
        echo "Error: could not detect user email from profile. Pass -e/--user-email explicitly."
        exit 1
    fi
    echo "  Detected: ${USER_EMAIL}"
fi

if [ "$SKIP_SWITCH" = false ] && [ "$YES" = false ]; then
    read -rp "Run Switch LLM conversion? (Y/n): " run_switch_answer
    if [[ "$run_switch_answer" =~ ^[Nn]$ ]]; then
        SKIP_SWITCH=true
        SKIP_LLM_INSTALL=true
    elif [ "$SKIP_LLM_INSTALL" = false ]; then
        read -rp "  Install Switch LLM transpiler first? (y/N): " install_switch_answer
        if [[ ! "$install_switch_answer" =~ ^[Yy]$ ]]; then
            SKIP_LLM_INSTALL=true
        fi
    fi
fi

if [ "$SKIP_SWITCH" = false ]; then
    if [ -z "$SWITCH_STYLE" ] && [ "$YES" = false ]; then
        read -rp "Switch target: (sdp) Lakeflow SQL pipeline or (sql) SQL files + Warehouse Job [default: sdp]: " _sws
        _sws="${_sws:-sdp}"
        _sws=$(printf '%s' "$_sws" | tr '[:upper:]' '[:lower:]')
        [ "$_sws" = "sql" ] && SWITCH_STYLE=sql || SWITCH_STYLE=sdp
    fi
    SWITCH_STYLE="${SWITCH_STYLE:-sdp}"
fi

if [ "$SKIP_SWITCH" = false ] && [ "$SWITCH_STYLE" = "sql" ] && [ "$YES" = false ]; then
    if [ "$SKIP_JOB_CREATE" = false ]; then
        read -rp "Create a SQL Warehouse Job for the converted files? (Y/n): " _job_ans
        [[ "$_job_ans" =~ ^[Nn]$ ]] && SKIP_JOB_CREATE=true
    fi
fi

if [ "$SKIP_SWITCH" = false ] && [ "$WAIT_FOR_SWITCH" = false ] && [ "$YES" = false ]; then
    read -rp "Wait for Switch LLM to complete before finishing? (y/N): " _wait_ans
    [[ "$_wait_ans" =~ ^[Yy]$ ]] && WAIT_FOR_SWITCH=true
fi

if [ "$SKIP_BLADEBRIDGE" = false ] && [ "$YES" = false ]; then
    if [ "${SWITCH_STYLE:-sdp}" = "sql" ]; then
        read -rp "Run BladeBridge pre-processing? (y/N — often fails on complex stored procedures): " run_bb_answer
        if [[ ! "$run_bb_answer" =~ ^[Yy]$ ]]; then
            SKIP_BLADEBRIDGE=true; SKIP_DET_INSTALL=true
        fi
    else
        read -rp "Run BladeBridge deterministic conversion? (Y/n): " run_bb_answer
        if [[ "$run_bb_answer" =~ ^[Nn]$ ]]; then
            SKIP_BLADEBRIDGE=true; SKIP_DET_INSTALL=true
        fi
    fi
fi

if [ -z "$INPUT_SOURCE" ]; then
    read -rp "Path to a .sql file, or a folder of .sql files: " INPUT_SOURCE
fi
if [ ! -e "$INPUT_SOURCE" ]; then
    echo "Error: input source '${INPUT_SOURCE}' does not exist."
    exit 1
fi
if [ -f "$INPUT_SOURCE" ]; then
    case "$INPUT_SOURCE" in
        *.[sS][qQ][lL]) ;;
        *) echo "Error: when the input is a file, it must be a .sql file (got: ${INPUT_SOURCE})"; exit 1 ;;
    esac
elif [ -d "$INPUT_SOURCE" ]; then
    _tsql_count=$(find "$INPUT_SOURCE" -type f -iname "*.sql" 2>/dev/null | wc -l | tr -d ' ')
    if [ "${_tsql_count:-0}" -eq 0 ]; then
        echo "Error: input directory must contain at least one .sql file: ${INPUT_SOURCE}"
        exit 1
    fi
else
    echo "Error: input must be a file or directory: ${INPUT_SOURCE}"
    exit 1
fi

if [ -z "$OUTPUT_FOLDER" ]; then
    read -rp "Local output folder for staged files: " OUTPUT_FOLDER
fi
if [ -z "$OUTPUT_FOLDER" ]; then
    echo "Error: output folder is required."
    exit 1
fi

if [ "$SKIP_SWITCH" = true ]; then
    OUTPUT_WS_FOLDER="${OUTPUT_WS_FOLDER:-/Workspace/Users/${USER_EMAIL}/$(basename "$OUTPUT_FOLDER")}"
    CATALOG="${CATALOG}"
    SCHEMA="${SCHEMA:-switch}"
    VOLUME="${VOLUME:-switch_volume}"
    FOUNDATION_MODEL="${FOUNDATION_MODEL:-databricks-claude-sonnet-4-5}"
    PIPELINE_CATALOG="${PIPELINE_CATALOG:-${CATALOG}}"
    PIPELINE_TARGET="${PIPELINE_TARGET:-default}"
    BRONZE_CATALOG="${BRONZE_CATALOG:-${CATALOG}}"
    BRONZE_SCHEMA="${BRONZE_SCHEMA:-bronze}"
    SILVER_CATALOG="${SILVER_CATALOG:-${CATALOG}}"
    SILVER_SCHEMA="${SILVER_SCHEMA:-silver}"
    GOLD_CATALOG="${GOLD_CATALOG:-${CATALOG}}"
    GOLD_SCHEMA="${GOLD_SCHEMA:-gold}"
else
    if [ -z "$OUTPUT_WS_FOLDER" ]; then
        read -rp "Workspace output folder (must start with /Workspace/): " OUTPUT_WS_FOLDER
    fi
    if [[ ! "$OUTPUT_WS_FOLDER" == /Workspace/* ]]; then
        echo "Error: workspace output folder must start with /Workspace/"
        exit 1
    fi
    if [ -z "$CATALOG" ]; then
        [ "$YES" = false ] && read -rp "Catalog for Switch artifacts (required): " CATALOG
        if [ -z "$CATALOG" ]; then
            echo "Error: --catalog is required."
            exit 1
        fi
    fi
    if [ -z "$SCHEMA" ]; then
        [ "$YES" = false ] && read -rp "Schema for Switch artifacts [default: switch]: " SCHEMA
        SCHEMA="${SCHEMA:-switch}"
    fi
    if [ -z "$VOLUME" ]; then
        [ "$YES" = false ] && read -rp "UC Volume name [default: switch_volume]: " VOLUME
        VOLUME="${VOLUME:-switch_volume}"
    fi

    # Medallion layer catalog/schema resolution
    if [ "$SINGLE_CATALOG" = false ] && [ "$YES" = false ]; then
        read -rp "Are all data layers (bronze/silver/gold) in the same catalog? (Y/n): " _sc_ans
        [[ ! "$_sc_ans" =~ ^[Nn]$ ]] && SINGLE_CATALOG=true
    fi
    if [ "$SINGLE_CATALOG" = true ]; then
        BRONZE_CATALOG="${BRONZE_CATALOG:-$CATALOG}"
        BRONZE_SCHEMA="${BRONZE_SCHEMA:-bronze}"
        SILVER_CATALOG="${SILVER_CATALOG:-$CATALOG}"
        SILVER_SCHEMA="${SILVER_SCHEMA:-silver}"
        GOLD_CATALOG="${GOLD_CATALOG:-$CATALOG}"
        GOLD_SCHEMA="${GOLD_SCHEMA:-gold}"
    else
        if [ -z "$BRONZE_CATALOG" ]; then
            [ "$YES" = false ] && read -rp "Bronze catalog [default: ${CATALOG}]: " BRONZE_CATALOG
            BRONZE_CATALOG="${BRONZE_CATALOG:-$CATALOG}"
        fi
        if [ -z "$BRONZE_SCHEMA" ]; then
            [ "$YES" = false ] && read -rp "Bronze schema [default: bronze]: " BRONZE_SCHEMA
            BRONZE_SCHEMA="${BRONZE_SCHEMA:-bronze}"
        fi
        if [ -z "$SILVER_CATALOG" ]; then
            [ "$YES" = false ] && read -rp "Silver catalog [default: ${BRONZE_CATALOG}]: " SILVER_CATALOG
            SILVER_CATALOG="${SILVER_CATALOG:-$BRONZE_CATALOG}"
        fi
        if [ -z "$SILVER_SCHEMA" ]; then
            [ "$YES" = false ] && read -rp "Silver schema [default: silver]: " SILVER_SCHEMA
            SILVER_SCHEMA="${SILVER_SCHEMA:-silver}"
        fi
        if [ -z "$GOLD_CATALOG" ]; then
            [ "$YES" = false ] && read -rp "Gold catalog [default: ${BRONZE_CATALOG}]: " GOLD_CATALOG
            GOLD_CATALOG="${GOLD_CATALOG:-$BRONZE_CATALOG}"
        fi
        if [ -z "$GOLD_SCHEMA" ]; then
            [ "$YES" = false ] && read -rp "Gold schema [default: gold]: " GOLD_SCHEMA
            GOLD_SCHEMA="${GOLD_SCHEMA:-gold}"
        fi
    fi

    if [ -z "$FOUNDATION_MODEL" ]; then
        [ "$YES" = false ] && read -rp "Foundation model endpoint [default: databricks-claude-sonnet-4-5]: " FOUNDATION_MODEL
        FOUNDATION_MODEL="${FOUNDATION_MODEL:-databricks-claude-sonnet-4-5}"
    fi

    if [ "$SWITCH_STYLE" = "sdp" ]; then
        if [ -z "$PIPELINE_CATALOG" ]; then
            [ "$YES" = false ] && read -rp "Lakeflow DLP catalog [default: ${CATALOG}]: " PIPELINE_CATALOG
            PIPELINE_CATALOG="${PIPELINE_CATALOG:-$CATALOG}"
        fi
        if [ -z "$PIPELINE_TARGET" ]; then
            [ "$YES" = false ] && read -rp "Lakeflow DLP target schema [default: default]: " PIPELINE_TARGET
            PIPELINE_TARGET="${PIPELINE_TARGET:-default}"
        fi
        if [ -z "$CLUSTER_POLICY" ] && [ "$YES" = false ]; then
            read -rp "DLP compute — Serverless (S) or Cluster Policy (C)? [default: S]: " compute_choice
            if [[ "$compute_choice" =~ ^[Cc]$ ]]; then
                USE_SERVERLESS=false
                read -rp "  Cluster policy ID: " CLUSTER_POLICY
                if [ -z "$CLUSTER_POLICY" ]; then
                    echo "Error: cluster policy ID is required when using cluster compute."
                    exit 1
                fi
            fi
        fi
    else
        PIPELINE_CATALOG="${PIPELINE_CATALOG:-$CATALOG}"
        PIPELINE_TARGET="${PIPELINE_TARGET:-default}"
    fi
fi

# Set custom prompt default after SWITCH_STYLE is resolved
if [ -z "$CUSTOM_PROMPT" ] && [ "$SKIP_SWITCH" = false ]; then
    if [ "$SWITCH_STYLE" = "sql" ]; then
        CUSTOM_PROMPT="${SCRIPT_DIR}/mssql_to_sparksql_file_prompt.yml"
    else
        CUSTOM_PROMPT="${SCRIPT_DIR}/mssql_sp_to_sdp_switch_prompt.yml"
    fi
fi

# --- Summary ---
echo ""
echo "============================================"
echo "  T-SQL to Databricks (Lakebridge)"
echo "============================================"
echo "  Profile:            ${PROFILE}"
echo "  User email:         ${USER_EMAIL}"
echo "  Input source:       ${INPUT_SOURCE}"
echo "  Output folder:      ${OUTPUT_FOLDER}"
if [ "$SKIP_TRANSPILER_CONFIG_PATH" = true ]; then
    echo "  Transpiler config:  (not passed; Lakebridge default)"
else
    echo "  Transpiler config:  ${TRANSPILER_CONFIG_PATH:-${DEFAULT_TRANSPILER_CONFIG_PATH}} (default if unset)"
fi
if [ "$SKIP_SWITCH" = true ]; then
    echo "  Workspace folder:   (N/A – Switch disabled)"
    echo "  Switch:             (disabled)"
else
    echo "  Workspace folder:   ${OUTPUT_WS_FOLDER}"
    echo "  Custom prompt:      ${CUSTOM_PROMPT}"
    echo "  Catalog:            ${CATALOG}"
    echo "  Schema:             ${SCHEMA}"
    echo "  Volume:             ${VOLUME}"
    echo "  Foundation model:   ${FOUNDATION_MODEL}"
    echo "  Switch style:       ${SWITCH_STYLE}"
    if [ "$SINGLE_CATALOG" = true ]; then
        echo "  Layers (single):    ${CATALOG}  bronze=${BRONZE_SCHEMA}  silver=${SILVER_SCHEMA}  gold=${GOLD_SCHEMA}"
    else
        echo "  Bronze:             ${BRONZE_CATALOG}.${BRONZE_SCHEMA}"
        echo "  Silver:             ${SILVER_CATALOG}.${SILVER_SCHEMA}"
        echo "  Gold:               ${GOLD_CATALOG}.${GOLD_SCHEMA}"
    fi
    if [ "$SWITCH_STYLE" = "sdp" ]; then
        echo "  DLP:                catalog=${PIPELINE_CATALOG} target=${PIPELINE_TARGET}"
        echo "  Pipeline name:      ${PIPELINE_NAME:-<from first .sql>}"
        echo "  DLP compute:        $([ "$USE_SERVERLESS" = true ] && echo 'Serverless' || echo "Cluster Policy: ${CLUSTER_POLICY}")"
    else
        echo "  SQL Warehouse Job:  $([ "$SKIP_JOB_CREATE" = true ] && echo 'skip' || echo 'yes (warehouse selection at Step 6)')"
    fi
    echo "  Switch completion:  $([ "$WAIT_FOR_SWITCH" = true ] && echo 'wait (synchronous)' || echo 'async (fires and continues)')"
fi
echo "  BladeBridge:        $([ "$SKIP_BLADEBRIDGE" = true ] && echo 'skip' || ([ "$SKIP_DET_INSTALL" = true ] && echo 'run (no install)' || echo 'install + run'))"
echo "  Switch LLM:         $([ "$SKIP_SWITCH" = true ] && echo 'skip' || ([ "$SKIP_LLM_INSTALL" = true ] && echo 'run (no install)' || echo 'install + run'))"
echo "============================================"
echo ""
if [ "$YES" = false ]; then
    read -rp "Proceed? (y/N): " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
fi
echo ""

# --- Update override file USER_NAME/EMAIL_ADDRESS ---
SED_ARGS=(
    -e "s|\"USER_NAME\": \".*\"|\"USER_NAME\": \"${USER_EMAIL}\"|"
    -e "s|\"EMAIL_ADDRESS\": \".*\"|\"EMAIL_ADDRESS\": \"${USER_EMAIL}\"|"
)
sed -i.bak "${SED_ARGS[@]}" "$OVERRIDES_FILE"
rm -f "${OVERRIDES_FILE}.bak"

# =========================================================================
# Step 1: Install transpilers
# =========================================================================

if [ "$SKIP_DET_INSTALL" = false ]; then
    echo "Step 1a: Installing deterministic transpiler (BladeBridge)..."
    databricks labs lakebridge install-transpile --interactive false $PROFILE_FLAG
    echo ""
else
    echo "Step 1a: Skipping deterministic transpiler install."
fi

if [ "$SKIP_LLM_INSTALL" = false ]; then
    echo "Step 1b: Installing LLM transpiler (Switch)..."
    databricks labs lakebridge install-transpile --include-llm-transpiler true --interactive false $PROFILE_FLAG
    echo ""
else
    echo "Step 1b: Skipping LLM transpiler install."
fi
echo ""

# =========================================================================
# Step 2: Run BladeBridge transpilation
# =========================================================================

if [ "$SKIP_BLADEBRIDGE" = false ]; then
    echo "Step 2: Running BladeBridge transpilation..."
    echo ""

    mkdir -p "${OUTPUT_FOLDER}"
    if [ -z "$ERROR_LOG_PATH" ]; then
        ERROR_LOG_PATH="${OUTPUT_FOLDER}/errors.log"
    fi
    mkdir -p "$(dirname "$ERROR_LOG_PATH")"
    if [ "$SKIP_TRANSPILER_CONFIG_PATH" = false ]; then
        if [ -z "$TRANSPILER_CONFIG_PATH" ]; then
            TRANSPILER_CONFIG_PATH="${DEFAULT_TRANSPILER_CONFIG_PATH}"
        fi
        if [ ! -f "$TRANSPILER_CONFIG_PATH" ]; then
            echo "Error: BladeBridge config not found: ${TRANSPILER_CONFIG_PATH}"
            echo "  Run: databricks labs lakebridge install-transpile ${PROFILE_FLAG}"
            echo "  Or: --transpiler-config-path /path/to/config.yml  or  --no-transpiler-config-path"
            exit 1
        fi
    fi

    _lb_transpile=(databricks labs lakebridge transpile
        --source-dialect "mssql"
        --target-technology "SPARKSQL"
        --input-source "${INPUT_SOURCE}"
        --output-folder "${OUTPUT_FOLDER}"
        --overrides-file "${OVERRIDES_FILE}"
        --error-file-path "${ERROR_LOG_PATH}"
    )
    if [ "$SKIP_TRANSPILER_CONFIG_PATH" = false ]; then
        _lb_transpile+=(--transpiler-config-path "$TRANSPILER_CONFIG_PATH")
    fi
    _lb_transpile+=(--skip-validation true -p "$PROFILE")
    "${_lb_transpile[@]}"

    echo ""
    echo "  BladeBridge output: ${OUTPUT_FOLDER}"
    echo ""
else
    echo "Step 2: Skipping BladeBridge."
    mkdir -p "${OUTPUT_FOLDER}"
    echo ""
fi

# =========================================================================
# Step 3: Stage .sql files for Switch LLM
# =========================================================================

FIRST_PASS_DIR="${OUTPUT_FOLDER}/first_pass"
SWITCH_INPUT_DIR="${OUTPUT_FOLDER}/switch_input"
mkdir -p "${FIRST_PASS_DIR}" "${SWITCH_INPUT_DIR}"

echo "Step 3: Staging .sql files for Switch LLM..."

if [ "$SKIP_BLADEBRIDGE" = false ]; then
    # Preserve BladeBridge top-level output in first_pass/ then stage .sql to switch_input/
    find "${OUTPUT_FOLDER}" -maxdepth 1 -type f -exec cp {} "${FIRST_PASS_DIR}/" \;
    shopt -s nullglob nocaseglob
    bb_sql_files=("${OUTPUT_FOLDER}"/*.sql)
    shopt -u nocaseglob nullglob
    if [ ${#bb_sql_files[@]} -eq 0 ]; then
        echo "Error: no .sql files found in ${OUTPUT_FOLDER} after BladeBridge."
        exit 1
    fi
    for f in "${bb_sql_files[@]}"; do
        cp "$f" "${SWITCH_INPUT_DIR}/"
    done
    echo "  Staged ${#bb_sql_files[@]} BladeBridge .sql file(s) to switch_input/"
else
    # Stage raw input files to switch_input/
    if [ -f "$INPUT_SOURCE" ]; then
        cp "$INPUT_SOURCE" "${SWITCH_INPUT_DIR}/"
        echo "  Staged 1 raw .sql file: $(basename "$INPUT_SOURCE")"
    else
        shopt -s nullglob nocaseglob
        src_sql_files=("${INPUT_SOURCE}"/*.sql)
        shopt -u nocaseglob nullglob
        if [ ${#src_sql_files[@]} -eq 0 ]; then
            echo "Error: no .sql files found in ${INPUT_SOURCE}"
            exit 1
        fi
        for f in "${src_sql_files[@]}"; do
            cp "$f" "${SWITCH_INPUT_DIR}/"
        done
        echo "  Staged ${#src_sql_files[@]} raw .sql file(s) from ${INPUT_SOURCE}/"
    fi
fi

shopt -s nullglob nocaseglob
staged_files=("${SWITCH_INPUT_DIR}"/*.sql)
shopt -u nocaseglob nullglob
echo "  Total in switch_input/: ${#staged_files[@]} file(s)"
echo ""

# Derive pipeline/job name from first staged .sql
if [ -z "$PIPELINE_NAME" ]; then
    if [ ${#staged_files[@]} -gt 0 ]; then
        _base=$(basename "${staged_files[0]}")
        PIPELINE_NAME="${_base%.*}"
    else
        PIPELINE_NAME="$(basename "$OUTPUT_FOLDER")"
    fi
fi

# =========================================================================
# Step 4: Upload custom prompt and update switch_config.yml
# =========================================================================

if [ "$SKIP_SWITCH" = true ]; then
    echo "Step 4: Skipping Switch prompt upload (Switch not running)."
    echo ""
    echo "Step 5: Skipping Switch LLM conversion."
    echo ""
else

echo "Step 4: Uploading custom prompt and updating Switch configuration..."

if [ ! -f "$CUSTOM_PROMPT" ]; then
    echo "Error: custom prompt file '${CUSTOM_PROMPT}' not found."
    exit 1
fi
PROMPT_FILENAME="$(basename "$CUSTOM_PROMPT")"
WS_PROMPT_DIR="/Workspace/Users/${USER_EMAIL}/Prompts"
WS_PROMPT_PATH="${WS_PROMPT_DIR}/${PROMPT_FILENAME}"

if ! databricks workspace mkdirs "${WS_PROMPT_DIR}" $PROFILE_FLAG 2>&1; then
    echo "  WARNING: Failed to create workspace directory ${WS_PROMPT_DIR}. Continuing..."
fi
databricks workspace import "${WS_PROMPT_PATH}" \
    --file "$CUSTOM_PROMPT" \
    --format AUTO \
    --overwrite \
    $PROFILE_FLAG
echo "  Uploaded prompt to: ${WS_PROMPT_PATH}"

SWITCH_CONFIG_WS_PATH="/Users/${USER_EMAIL}/.lakebridge/switch/resources/switch_config.yml"
SWITCH_CONFIG_LOCAL="${OUTPUT_FOLDER}/switch_config.yml"

if [ "$SWITCH_STYLE" = "sql" ]; then
    cat > "$SWITCH_CONFIG_LOCAL" <<SWITCHEOF
# Switch configuration file
# Auto-generated by tsql-to-databricks run.sh

target_type: "file"
output_extension: "sql"
source_format: "generic"
comment_lang: "English"
log_level: "INFO"
token_count_threshold: 50000
concurrency: 4
max_fix_attempts: 0

conversion_prompt_yaml: ${WS_PROMPT_PATH}

sql_output_dir:
request_params:
sdp_language: sql
SWITCHEOF
else
    cat > "$SWITCH_CONFIG_LOCAL" <<SWITCHEOF
# Switch configuration file
# Auto-generated by tsql-to-databricks run.sh

target_type: "file"
output_extension: "sql"
source_format: "generic"
comment_lang: "English"
log_level: "INFO"
token_count_threshold: 20000
concurrency: 4
max_fix_attempts: 0

conversion_prompt_yaml: ${WS_PROMPT_PATH}

sql_output_dir:
request_params:
sdp_language: sql
SWITCHEOF
fi

databricks workspace import "${SWITCH_CONFIG_WS_PATH}" \
    --file "$SWITCH_CONFIG_LOCAL" \
    --format AUTO \
    --overwrite \
    $PROFILE_FLAG
echo "  Updated switch_config.yml at: ${SWITCH_CONFIG_WS_PATH}"
echo "  target_type: file (sql output — LDP SQL prompt)"
echo ""

# =========================================================================
# Step 5: Run Switch LLM conversion
# =========================================================================

echo "Step 5: Running Switch LLM transpiler..."
echo ""

_switch_log=$(mktemp)
CLEANUP_FILES+=("$_switch_log")
databricks labs lakebridge llm-transpile \
    --accept-terms true \
    --input-source "${SWITCH_INPUT_DIR}" \
    --output-ws-folder "${OUTPUT_WS_FOLDER}" \
    --source-dialect unknown_etl \
    --catalog-name "${CATALOG}" \
    --schema-name "${SCHEMA}" \
    --volume "${VOLUME}" \
    --foundation-model "${FOUNDATION_MODEL}" \
    $PROFILE_FLAG 2>&1 | tee "$_switch_log"
SWITCH_RUN_ID=$(sed 's/\x1b\[[0-9;]*m//g' "$_switch_log" \
    | grep -oE '/runs/[0-9]+' | tail -1 | sed 's|/runs/||')
rm -f "$_switch_log"

echo ""
if [ "$SWITCH_STYLE" = "sql" ]; then
    echo "  LLM conversion in progress. SQL files will appear under ${OUTPUT_WS_FOLDER} when completed."
else
    echo "  LLM conversion in progress. Notebooks at: ${OUTPUT_WS_FOLDER} when completed."
fi
echo ""

if [ "$WAIT_FOR_SWITCH" = true ] && [ -n "${SWITCH_RUN_ID:-}" ]; then
    echo "  Waiting for Switch LLM job (run ${SWITCH_RUN_ID})..."
    while true; do
        _sw_state=$(databricks jobs get-run "$SWITCH_RUN_ID" $PROFILE_FLAG -o json 2>/dev/null \
            | python3 -c "import sys,json; d=json.load(sys.stdin); \
              print(d.get('state',{}).get('life_cycle_state','UNKNOWN'))" 2>/dev/null || echo "UNKNOWN")
        if [ "$_sw_state" = "TERMINATED" ]; then
            _sw_result=$(databricks jobs get-run "$SWITCH_RUN_ID" $PROFILE_FLAG -o json 2>/dev/null \
                | python3 -c "import sys,json; d=json.load(sys.stdin); \
                  print(d.get('state',{}).get('result_state','UNKNOWN'))" 2>/dev/null || echo "UNKNOWN")
            echo "  Switch completed: ${_sw_result}"
            [ "$_sw_result" != "SUCCESS" ] && echo "  Warning: Switch did not succeed. Check workspace output before continuing."
            break
        fi
        echo "  Switch state: ${_sw_state} — waiting 30s..."
        sleep 30
    done
    echo ""
fi

fi  # end SKIP_SWITCH guard (Steps 4, 5)

# =========================================================================
# Step 6: SQL Warehouse Job (sql mode) or Lakeflow Pipeline (sdp mode)
# =========================================================================

JOB_WAS_CREATED=false
JOB_ID=""
PIPELINE_ID=""
WS_HOST=""

if [ "$SKIP_SWITCH" = true ]; then
    echo "Step 6: Skipping (Switch not run; no workspace output to reference)."
    echo ""
    echo "============================================"
    echo "  Run finished (Switch off)"
    echo "============================================"
    echo "  Staged files:       ${SWITCH_INPUT_DIR}"
    echo "  BladeBridge out:    ${OUTPUT_FOLDER}"
    [ "$SKIP_BLADEBRIDGE" = false ] && echo "  First pass:         ${FIRST_PASS_DIR}"
    echo "  Workspace:          (N/A – Switch disabled)"
    echo "============================================"

elif [ "$SWITCH_STYLE" = "sql" ]; then
    # -------------------------------------------------------------------------
    # SQL Warehouse Job creation
    # -------------------------------------------------------------------------
    if [ "$SKIP_JOB_CREATE" = true ]; then
        echo "Step 6: Skipping SQL Warehouse Job creation."
    else
        echo "Step 6: Creating Databricks SQL Warehouse Job..."
        echo ""

        if [ -z "$JOB_NAME" ]; then
            _last_sql=$(ls -1 "${SWITCH_INPUT_DIR}"/*.sql 2>/dev/null | sort | tail -1 || true)
            if [ -n "$_last_sql" ]; then
                JOB_NAME="$(basename "${_last_sql%.sql}") SQL Job"
            else
                JOB_NAME="$(basename "${OUTPUT_WS_FOLDER}") SQL Job"
            fi
        fi

        if [ -z "$WAREHOUSE_ID" ]; then
            echo "  Fetching SQL warehouses from workspace..."
            WH_LIST_FILE="${OUTPUT_FOLDER}/warehouses_list.json"
            if ! databricks warehouses list $PROFILE_FLAG -o json > "$WH_LIST_FILE" 2>/dev/null; then
                echo "[]" > "$WH_LIST_FILE"
            fi
            WH_COUNT=$(python3 -c "
import json
data = json.load(open('${WH_LIST_FILE}'))
whs = data if isinstance(data, list) else data.get('warehouses', [])
print(len(whs))" 2>/dev/null || echo 0)

            if [ "${WH_COUNT:-0}" -eq 0 ]; then
                echo "  No SQL warehouses found. Skipping job creation."
                SKIP_JOB_CREATE=true
            else
                echo ""
                python3 - <<PYEOF
import json
data = json.load(open('${WH_LIST_FILE}'))
whs = data if isinstance(data, list) else data.get('warehouses', [])
for i, w in enumerate(whs, 1):
    print(f"    {i}) {w['name']} ({w['id']})")
PYEOF
                echo ""
                if [ "$YES" = true ]; then
                    WAREHOUSE_ID=$(python3 -c "
import json
data = json.load(open('${WH_LIST_FILE}'))
whs = data if isinstance(data, list) else data.get('warehouses', [])
print(whs[0]['id'])")
                    WH_NAME=$(python3 -c "
import json
data = json.load(open('${WH_LIST_FILE}'))
whs = data if isinstance(data, list) else data.get('warehouses', [])
print(whs[0]['name'])")
                    echo "  Auto-selected (--yes): ${WH_NAME} (${WAREHOUSE_ID})"
                    echo ""
                else
                    read -rp "  Select warehouse [1-${WH_COUNT}]: " _sel
                    if [[ "$_sel" =~ ^[0-9]+$ ]] && [ "$_sel" -ge 1 ] && [ "$_sel" -le "$WH_COUNT" ]; then
                        WAREHOUSE_ID=$(python3 -c "
import json
data = json.load(open('${WH_LIST_FILE}'))
whs = data if isinstance(data, list) else data.get('warehouses', [])
print(whs[${_sel}-1]['id'])")
                        WH_NAME=$(python3 -c "
import json
data = json.load(open('${WH_LIST_FILE}'))
whs = data if isinstance(data, list) else data.get('warehouses', [])
print(whs[${_sel}-1]['name'])")
                        echo "  Selected: ${WH_NAME} (${WAREHOUSE_ID})"
                        echo ""
                    else
                        echo "  Invalid selection. Skipping job creation."
                        SKIP_JOB_CREATE=true
                    fi
                fi
            fi
        fi

        if [ "$SKIP_JOB_CREATE" = false ]; then
            JOB_SPEC_FILE="${OUTPUT_FOLDER}/job_spec.json"
            export SWITCH_INPUT_DIR OUTPUT_WS_FOLDER WAREHOUSE_ID JOB_NAME JOB_SPEC_FILE \
                   GOLD_CATALOG GOLD_SCHEMA BRONZE_CATALOG BRONZE_SCHEMA \
                   SILVER_CATALOG SILVER_SCHEMA
            python3 <<'PYEOF'
import os, re, json

switch_input_dir = os.environ['SWITCH_INPUT_DIR']
output_ws_folder = os.environ['OUTPUT_WS_FOLDER']
warehouse_id = os.environ['WAREHOUSE_ID']
job_name = os.environ['JOB_NAME']
job_spec_file = os.environ['JOB_SPEC_FILE']

sql_files = sorted([f for f in os.listdir(switch_input_dir) if f.lower().endswith('.sql')])

def remove_comments(sql):
    sql = re.sub(r'--[^\n]*', ' ', sql)
    return re.sub(r'/\*.*?\*/', ' ', sql, flags=re.DOTALL)

def obj_names(content, patterns):
    names = set()
    for pat in patterns:
        for m in re.finditer(pat, content, re.IGNORECASE):
            part = m.group(1).strip().split('.')[-1].strip('[]`"').lower()
            if part:
                names.add(part)
    return names

writes, reads = {}, {}
for fname in sql_files:
    c = remove_comments(open(os.path.join(switch_input_dir, fname), errors='replace').read())
    writes[fname] = obj_names(c, [
        r'INSERT\s+(?:INTO\s+)([\w.\[\]`"]+)',
        r'MERGE\s+(?:INTO\s+)?([\w.\[\]`"]+)',
        r'TRUNCATE\s+TABLE\s+([\w.\[\]`"]+)',
        r'UPDATE\s+([\w.\[\]`"]+)\s+SET',
        r'DELETE\s+FROM\s+([\w.\[\]`"]+)',
    ])
    reads[fname] = obj_names(c, [
        r'FROM\s+([\w.\[\]`"]+)',
        r'JOIN\s+([\w.\[\]`"]+)',
        r'EXEC(?:UTE)?\s+([\w.\[\]`"]+)',
    ])

raw_deps = {}
for fname in sql_files:
    key = re.sub(r'[^a-zA-Z0-9_]', '_', os.path.splitext(fname)[0])
    raw_deps[key] = [re.sub(r'[^a-zA-Z0-9_]', '_', os.path.splitext(o)[0])
                     for o in sql_files if o != fname and reads[fname] & writes[o]]

clean_deps = {k: list(v) for k, v in raw_deps.items()}
for key, deps in raw_deps.items():
    for dep in deps:
        if dep in clean_deps.get(key, []) and key in clean_deps.get(dep, []):
            clean_deps[dep] = [x for x in clean_deps[dep] if x != key]
            print(f"  Note: broke circular dependency {dep} → {key} (kept {key} → {dep})", flush=True)

tasks = []
for fname in sql_files:
    key = re.sub(r'[^a-zA-Z0-9_]', '_', os.path.splitext(fname)[0])
    deps = [{"task_key": d} for d in clean_deps.get(key, [])]
    task = {
        "task_key": key,
        "sql_task": {
            "file": {"path": f"{output_ws_folder}/{fname}"},
            "warehouse_id": warehouse_id
        }
    }
    if deps:
        task["depends_on"] = deps
    tasks.append(task)

parameters = [
    {"name": "gold_catalog",   "default": os.environ.get('GOLD_CATALOG', '')},
    {"name": "gold_schema",    "default": os.environ.get('GOLD_SCHEMA', '')},
    {"name": "bronze_catalog", "default": os.environ.get('BRONZE_CATALOG', '')},
    {"name": "bronze_schema",  "default": os.environ.get('BRONZE_SCHEMA', '')},
    {"name": "silver_catalog", "default": os.environ.get('SILVER_CATALOG', '')},
    {"name": "silver_schema",  "default": os.environ.get('SILVER_SCHEMA', '')},
    {"name": "source_catalog", "default": os.environ.get('BRONZE_CATALOG', '')},
    {"name": "source_schema",  "default": os.environ.get('BRONZE_SCHEMA', '')},
]
json.dump({"name": job_name, "parameters": parameters, "tasks": tasks}, open(job_spec_file, 'w'), indent=2)
print(f"  {len(tasks)} task(s) in job spec", flush=True)
for t in tasks:
    if t.get("depends_on"):
        deps_str = ", ".join(d["task_key"] for d in t["depends_on"])
        print(f"    {t['task_key']} depends on: {deps_str}", flush=True)
PYEOF

            echo ""
            echo "  Creating job '${JOB_NAME}'..."
            JOB_RESPONSE=$(databricks jobs create --json @"${JOB_SPEC_FILE}" $PROFILE_FLAG -o json 2>&1 || true)
            JOB_ID=$(echo "$JOB_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('job_id',''))" 2>/dev/null || true)
            if [ -n "$JOB_ID" ]; then
                JOB_WAS_CREATED=true
                echo "  Job created: ID ${JOB_ID}"
            else
                echo "  Warning: job creation may have failed. Response: ${JOB_RESPONSE}"
            fi
        fi
    fi

    echo ""
    echo "============================================"
    echo "  Run finished (sql mode)"
    echo "============================================"
    echo "  Staged files:       ${SWITCH_INPUT_DIR}"
    echo "  Workspace output:   ${OUTPUT_WS_FOLDER}"
    if [ "${JOB_WAS_CREATED:-false}" = true ] && [ -n "${JOB_ID:-}" ]; then
        WS_HOST=$(databricks auth describe $PROFILE_FLAG -o json 2>/dev/null \
            | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('details',{}).get('host',''))" 2>/dev/null || true)
        if [ -n "$WS_HOST" ]; then
            echo "  Job URL:            ${WS_HOST}/jobs/${JOB_ID}"
        else
            echo "  Job ID:             ${JOB_ID}"
        fi
        echo "  Job params:         Pre-populated from your input. Override in job settings if needed."
    else
        echo "  SQL Warehouse Job:  (skipped; create manually from ${OUTPUT_FOLDER}/job_spec.json)"
    fi
    echo "============================================"

else
    # -------------------------------------------------------------------------
    # Lakeflow Declarative Pipeline (sdp mode)
    # -------------------------------------------------------------------------
    echo "Step 6: Creating Lakeflow Declarative Pipeline (sdp style)..."

    WS_HOST=$(python3 -c "
import configparser, os, sys
profile = sys.argv[1]
cfg = configparser.ConfigParser()
cfg.read(os.path.expanduser('~/.databrickscfg'))
host = ''
if cfg.has_section(profile):
    host = cfg.get(profile, 'host', fallback='')
if not host and profile.upper() == 'DEFAULT':
    host = cfg.get('DEFAULT', 'host', fallback='')
print(host.rstrip('/'))
" "$PROFILE" 2>/dev/null) || WS_HOST=""

    # Build notebook paths from staged .sql basenames (Switch will create these in workspace)
    nb_list=""
    shopt -s nullglob nocaseglob
    switch_sql_files=("${SWITCH_INPUT_DIR}"/*.sql)
    shopt -u nocaseglob nullglob
    for f in "${switch_sql_files[@]}"; do
        _stem=$(basename "$f")
        nb_name="${_stem%.*}"
        nb_list="${nb_list}${OUTPUT_WS_FOLDER}/${nb_name}
"
    done

    PIPELINE_SPEC="${OUTPUT_FOLDER}/pipeline_spec.json"
    python3 << PYEOF > "$PIPELINE_SPEC"
import json
notebooks = """${nb_list}""".strip().split('\n')
use_serverless = "${USE_SERVERLESS}" == "true"
cluster_policy = "${CLUSTER_POLICY}"

spec = {
    "name": "${PIPELINE_NAME}",
    "catalog": "${PIPELINE_CATALOG}",
    "target": "${PIPELINE_TARGET}",
    "configuration": {
        "bronze_catalog": "${BRONZE_CATALOG}",
        "bronze_schema":  "${BRONZE_SCHEMA}",
        "silver_catalog": "${SILVER_CATALOG}",
        "silver_schema":  "${SILVER_SCHEMA}",
        "gold_catalog":   "${GOLD_CATALOG}",
        "gold_schema":    "${GOLD_SCHEMA}",
    },
    "allow_duplicate_names": True,
    "libraries": [{"file": {"path": f"{nb}.sql"}} for nb in notebooks if nb],
}

if use_serverless:
    spec["serverless"] = True
    spec["photon"] = True
else:
    spec["serverless"] = False
    spec["clusters"] = [{"label": "default", "policy_id": cluster_policy}]

print(json.dumps(spec, indent=2))
PYEOF

    echo "  Pipeline spec: ${PIPELINE_SPEC}"

    if output=$(databricks pipelines create --json @"$PIPELINE_SPEC" $PROFILE_FLAG -o json 2>&1); then
        PIPELINE_ID=$(echo "$output" | python3 -c "import sys,json; print(json.load(sys.stdin)['pipeline_id'])")
        echo "  Created pipeline: ${PIPELINE_NAME} (ID: ${PIPELINE_ID})"
    else
        echo "  WARNING: Pipeline creation failed: ${output}"
        echo "  You can create it manually: databricks pipelines create --json @${PIPELINE_SPEC} $PROFILE_FLAG"
    fi

    echo ""
    echo "============================================"
    echo "  Pipeline Complete (sdp mode)"
    echo "============================================"
    echo "  Staged files:       ${SWITCH_INPUT_DIR}"
    echo "  Notebooks:          ${OUTPUT_WS_FOLDER}"
    [ "$SKIP_BLADEBRIDGE" = false ] && echo "  First pass:         ${FIRST_PASS_DIR}"
    if [ -n "$PIPELINE_ID" ]; then
        echo "  Lakeflow Pipeline:  ${PIPELINE_NAME} (ID: ${PIPELINE_ID})"
        [ -n "$WS_HOST" ] && echo "  Pipeline URL:       ${WS_HOST}/pipelines/${PIPELINE_ID}"
    else
        echo "  Lakeflow Pipeline:  (not created — see pipeline_spec.json)"
    fi
    echo "============================================"
fi
