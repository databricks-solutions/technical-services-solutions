#!/bin/bash
# End-to-end automation for SSIS-to-Databricks migration using Lakebridge.
#
# Prerequisite: Lakebridge must be installed (`databricks labs install lakebridge`)
#
# This script handles everything else:
#   1. Installs BladeBridge transpiler and Switch LLM transpiler
#   2. Runs BladeBridge to produce initial PySpark conversion from SSIS packages
#   3. Separates job JSONs (orchestration reference) and moves .py files to switch_input/
#   4. Uploads custom prompt and updates switch_config.yml on workspace
#   5. Runs Switch LLM transpiler (SDP: notebooks; sparksql: .sql per .py) to the workspace
#   6. Creates a Lakeflow Declarative Pipeline (skipped for --ssis-output sparksql; same idea as
#      tsql dbsql — DLP is Python graph–based; SQL path uses a SQL job or DBSQL instead)
#
# Default override JSON and prompt YAML are located alongside this script.
# Use --ssis-output sdp|sparksql to pick sdp vs Spark SQL .sql (unless -x overrides the prompt).
# Pass -r or -x to use files from other locations.
#
# Usage:
#   ./run.sh [options]
#
# Options:
#   -i, --input-source       Local path to SSIS packages (.dtsx files or project folder)
#   -o, --output-folder      Local path for BladeBridge output
#   -w, --output-ws-folder   Workspace folder for notebooks (must start with /Workspace/)
#   -e, --user-email         User email override (default: auto-detected from Databricks profile)
#   -p, --profile            Databricks CLI profile (default: DEFAULT)
#   -c, --catalog            Catalog for Switch artifacts (required)
#   -s, --schema             Schema for Switch artifacts (default: switch)
#   -v, --volume             UC Volume name (default: switch_volume)
#   -m, --foundation-model   Foundation model endpoint (default: databricks-claude-sonnet-4-5)
#       --sdp-language       Switch sdp_language: python or sql (default: python for sdp, sql for sparksql)
#       --ssis-output        Switch result type: sdp (Lakeflow / pyspark.pipelines) or sparksql (one .sql per .py; default: sdp)
#   -r, --overrides-file     Override JSON for BladeBridge (default: sample_override.json in script dir)
#       --error-file-path    Local path for BladeBridge conversion error log (default: <output-folder>/errors.log)
#       --transpiler-config-path  Path to BladeBridge config.yml (default: see DEFAULT_TRANSPILER_CONFIG_PATH;
#                                 always passed to transpile so the CLI does not use a bad built-in path)
#       --no-transpiler-config-path  Do not pass --transpiler-config-path (Lakebridge chooses the path)
#   -x, --custom-prompt      Custom Switch prompt YAML (default: from --ssis-output in script dir, unless -x is set)
#       --bronze-catalog     Bronze layer catalog (default: value of -c/--catalog)
#       --bronze-schema      Bronze layer schema (default: value of -s/--schema)
#       --silver-catalog     Silver layer catalog (default: prompted)
#       --silver-schema      Silver layer schema (default: prompted)
#       --gold-catalog       Gold layer catalog (default: prompted)
#       --gold-schema        Gold layer schema (default: prompted)
#       --pipeline-name      Pipeline name (default: derived from output folder basename)
#       --cluster-policy     Cluster policy ID for pipeline compute (omit for serverless)
#       --skip-det-install   Skip deterministic transpiler (BladeBridge) installation
#       --skip-llm-install   Skip LLM transpiler (Switch) installation
#       --skip-bladebridge   Skip BladeBridge step (if output already exists)
#       --skip-switch        Skip Switch LLM entirely (no Switch-only prompts; no DLP step 6)
#       --warehouse-id       SQL warehouse ID (skip interactive selection; sparksql mode only)
#       --job-name           Job name (default: last file in switch_input/ + " SQL Job"; sparksql mode only)
#       --skip-job-create    Skip Step 6 SQL Warehouse Job creation (sparksql mode only)
#       --single-catalog     All data layers (bronze/silver/gold) share the same catalog as Switch artifacts
#       --wait               Wait for Switch LLM job to complete before finishing (default: async)
#   -y, --yes                Non-interactive: skip all y/n prompts, accept defaults
#   -h, --help               Show this help message
#
# All flags are prompted interactively if not provided.

set -euo pipefail

CLEANUP_FILES=()
cleanup() {
    for f in "${CLEANUP_FILES[@]:-}"; do
        [[ -n "$f" ]] && rm -rf "$f" 2>/dev/null || true
    done
}
trap cleanup EXIT

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# After `databricks labs lakebridge install-transpile`, remorph/BladeBridge config is installed here
# (same layout the CLI uses; $HOME e.g. /Users/you, not /root).
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
BRONZE_CATALOG=""
BRONZE_SCHEMA=""
SILVER_CATALOG=""
SILVER_SCHEMA=""
GOLD_CATALOG=""
GOLD_SCHEMA=""
PIPELINE_NAME=""
CLUSTER_POLICY=""
USE_SERVERLESS=true
SKIP_DET_INSTALL=false
SKIP_LLM_INSTALL=false
SKIP_BLADEBRIDGE=false
SKIP_SWITCH=false
SDP_LANGUAGE=""
# sdp = Lakeflow SDP; sparksql = Spark SQL .sql per .py (Step 6 = SQL Warehouse Job)
SSIS_OUTPUT=""
WAREHOUSE_ID=""
JOB_NAME=""
SKIP_JOB_CREATE=false
SINGLE_CATALOG=false
WAIT_FOR_SWITCH=false
YES=false

usage() {
    sed -n '/^# Usage:/,/^[^#]/{ /^#/s/^# \?//p }' "$0"
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -i|--input-source)       INPUT_SOURCE="$2"; shift 2 ;;
        -o|--output-folder)      OUTPUT_FOLDER="$2"; shift 2 ;;
        -w|--output-ws-folder)   OUTPUT_WS_FOLDER="$2"; shift 2 ;;
        -e|--user-email)         USER_EMAIL="$2"; shift 2 ;;
        -p|--profile)            PROFILE="$2"; shift 2 ;;
        -c|--catalog)            CATALOG="$2"; shift 2 ;;
        -s|--schema)             SCHEMA="$2"; shift 2 ;;
        -v|--volume)             VOLUME="$2"; shift 2 ;;
        -m|--foundation-model)   FOUNDATION_MODEL="$2"; shift 2 ;;
        --sdp-language)          SDP_LANGUAGE="$2"; shift 2 ;;
        --ssis-output)            SSIS_OUTPUT="$2"; shift 2 ;;
        -r|--overrides-file)     OVERRIDES_FILE="$2"; shift 2 ;;
        --error-file-path)        ERROR_LOG_PATH="$2"; shift 2 ;;
        --transpiler-config-path) TRANSPILER_CONFIG_PATH="$2"; shift 2 ;;
        --no-transpiler-config-path) SKIP_TRANSPILER_CONFIG_PATH=true; shift ;;
        -x|--custom-prompt)      CUSTOM_PROMPT="$2"; shift 2 ;;
        --bronze-catalog)        BRONZE_CATALOG="$2"; shift 2 ;;
        --bronze-schema)         BRONZE_SCHEMA="$2"; shift 2 ;;
        --silver-catalog)        SILVER_CATALOG="$2"; shift 2 ;;
        --silver-schema)         SILVER_SCHEMA="$2"; shift 2 ;;
        --gold-catalog)          GOLD_CATALOG="$2"; shift 2 ;;
        --gold-schema)           GOLD_SCHEMA="$2"; shift 2 ;;
        --pipeline-name)         PIPELINE_NAME="$2"; shift 2 ;;
        --cluster-policy)       CLUSTER_POLICY="$2"; USE_SERVERLESS=false; shift 2 ;;
        --skip-det-install)      SKIP_DET_INSTALL=true; shift ;;
        --skip-llm-install)      SKIP_LLM_INSTALL=true; shift ;;
        --skip-bladebridge)      SKIP_BLADEBRIDGE=true; SKIP_DET_INSTALL=true; shift ;;
        --skip-switch)           SKIP_SWITCH=true; SKIP_LLM_INSTALL=true; shift ;;
        --warehouse-id)          WAREHOUSE_ID="$2"; shift 2 ;;
        --job-name)              JOB_NAME="$2"; shift 2 ;;
        --skip-job-create)       SKIP_JOB_CREATE=true; shift ;;
        --single-catalog)        SINGLE_CATALOG=true; shift ;;
        --wait)                  WAIT_FOR_SWITCH=true; shift ;;
        -y|--yes)                YES=true; shift ;;
        -h|--help)               usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

if [ -n "$SDP_LANGUAGE" ]; then
    _sdp_lc=$(printf '%s' "$SDP_LANGUAGE" | tr '[:upper:]' '[:lower:]')
    if [ "$_sdp_lc" != "python" ] && [ "$_sdp_lc" != "sql" ]; then
        echo "Error: --sdp-language must be 'python' or 'sql' (got: ${SDP_LANGUAGE})"
        exit 1
    fi
    SDP_LANGUAGE="$_sdp_lc"
fi

if [ -n "$SSIS_OUTPUT" ]; then
    _so_lc=$(printf '%s' "$SSIS_OUTPUT" | tr '[:upper:]' '[:lower:]')
    if [ "$_so_lc" != "sdp" ] && [ "$_so_lc" != "sparksql" ]; then
        echo "Error: --ssis-output must be 'sdp' or 'sparksql' (got: ${SSIS_OUTPUT})"
        exit 1
    fi
    SSIS_OUTPUT="$_so_lc"
fi

# --- Defaults for override and prompt (sibling files) ---

if [ -z "$OVERRIDES_FILE" ]; then
    OVERRIDES_FILE="${SCRIPT_DIR}/sample_override.json"
fi
if [ ! -f "$OVERRIDES_FILE" ]; then
    echo "Error: override file '${OVERRIDES_FILE}' not found."
    exit 1
fi

# custom prompt default is set when Switch runs (per --ssis-output), unless -x is used (validated in Step 4)

# --- Prompt for missing values ---

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

# --- Switch (LLM) first: "no" skips all Switch-only prompts and Step 4–5 (and the Lakeflow spec in step 6)
if [ "$SKIP_SWITCH" = false ] && [ "$YES" = false ]; then
    read -rp "Run Switch LLM conversion? (Y/n): " run_switch_answer
    if [[ "$run_switch_answer" =~ ^[Nn]$ ]]; then
        SKIP_SWITCH=true
        SKIP_LLM_INSTALL=true
    elif [ "$SKIP_LLM_INSTALL" = false ]; then
        read -rp "  Install Switch LLM transpiler first? (y/N): " install_switch_answer
        if [[ "$install_switch_answer" =~ ^[Yy]$ ]]; then
            SKIP_LLM_INSTALL=false
        else
            SKIP_LLM_INSTALL=true
        fi
    fi
fi

# --- BladeBridge: "no" skips all BladeBridge-only prompts (and Step 2)
if [ "$SKIP_BLADEBRIDGE" = false ] && [ "$YES" = false ]; then
    read -rp "Run BladeBridge deterministic conversion? (Y/n): " run_bb_answer
    if [[ "$run_bb_answer" =~ ^[Nn]$ ]]; then
        SKIP_BLADEBRIDGE=true; SKIP_DET_INSTALL=true
    elif [ "$SKIP_DET_INSTALL" = false ]; then
        read -rp "  Install BladeBridge transpiler first? (y/N): " install_bb_answer
        if [[ ! "$install_bb_answer" =~ ^[Yy]$ ]]; then
            SKIP_DET_INSTALL=true
        fi
    fi
fi

if [ "$SKIP_BLADEBRIDGE" = false ]; then
    if [ -z "$INPUT_SOURCE" ]; then
        read -rp "Local path to SSIS packages (.dtsx files or project folder): " INPUT_SOURCE
    fi
    if [ ! -e "$INPUT_SOURCE" ]; then
        echo "Error: input source '${INPUT_SOURCE}' does not exist."
        exit 1
    fi
fi

if [ -z "$OUTPUT_FOLDER" ]; then
    if [ "$SKIP_BLADEBRIDGE" = true ]; then
        read -rp "Local output folder (use existing BladeBridge/switch state): " OUTPUT_FOLDER
    else
        read -rp "Local output folder for BladeBridge results: " OUTPUT_FOLDER
    fi
fi
if [ -z "$OUTPUT_FOLDER" ]; then
    echo "Error: output folder is required."
    exit 1
fi

if [ "$SKIP_SWITCH" = true ]; then
    # No workspace LLM run: defaults only (summary / not used for llm-transpile)
    if [ -z "$OUTPUT_WS_FOLDER" ]; then
        OUTPUT_WS_FOLDER="/Workspace/Users/${USER_EMAIL}/$(basename "$OUTPUT_FOLDER")"
    fi
    CATALOG="${CATALOG}"
    SCHEMA="${SCHEMA:-switch}"
    VOLUME="${VOLUME:-switch_volume}"
    FOUNDATION_MODEL="${FOUNDATION_MODEL:-databricks-claude-sonnet-4-5}"
    BRONZE_CATALOG="${BRONZE_CATALOG:-$CATALOG}"
    BRONZE_SCHEMA="${BRONZE_SCHEMA:-bronze}"
    SILVER_CATALOG="${SILVER_CATALOG:-$BRONZE_CATALOG}"
    SILVER_SCHEMA="${SILVER_SCHEMA:-silver}"
    GOLD_CATALOG="${GOLD_CATALOG:-$BRONZE_CATALOG}"
    GOLD_SCHEMA="${GOLD_SCHEMA:-gold}"
    USE_SERVERLESS=true
    CLUSTER_POLICY=""
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
        [ "$YES" = false ] && read -rp "Schema name for Switch artifacts [default: switch]: " SCHEMA
        SCHEMA="${SCHEMA:-switch}"
    fi
    if [ -z "$VOLUME" ]; then
        [ "$YES" = false ] && read -rp "UC Volume name [default: switch_volume]: " VOLUME
        VOLUME="${VOLUME:-switch_volume}"
    fi
    if [ -z "$FOUNDATION_MODEL" ]; then
        [ "$YES" = false ] && read -rp "Foundation model endpoint [default: databricks-claude-sonnet-4-5]: " FOUNDATION_MODEL
        FOUNDATION_MODEL="${FOUNDATION_MODEL:-databricks-claude-sonnet-4-5}"
    fi
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
    if [ -z "$CLUSTER_POLICY" ] && [ "$YES" = false ]; then
        read -rp "Pipeline compute — Serverless (S) or Cluster Policy (C)? [default: S]: " compute_choice
        if [[ "$compute_choice" =~ ^[Cc]$ ]]; then
            USE_SERVERLESS=false
            read -rp "  Cluster policy ID: " CLUSTER_POLICY
            if [ -z "$CLUSTER_POLICY" ]; then
                echo "Error: cluster policy ID is required when using cluster compute."
                exit 1
            fi
        fi
    fi
    if [ -z "$SSIS_OUTPUT" ]; then
        read -rp "SSIS Switch output: (sdp) Lakeflow SDP or (sparksql) Spark SQL .sql per .py [default: sdp]: " _so_ans
        _so_ans="${_so_ans:-sdp}"
        _so_ans=$(printf '%s' "$_so_ans" | tr '[:upper:]' '[:lower:]')
        if [ "$_so_ans" = "sparksql" ] || [ "$_so_ans" = "sql" ]; then
            SSIS_OUTPUT=sparksql
        else
            SSIS_OUTPUT=sdp
        fi
    fi
    # Resolve SDP_LANGUAGE before CUSTOM_PROMPT so sdp+sql auto-selects the right prompt
    if [ "$SSIS_OUTPUT" = "sparksql" ] && [ -z "$SDP_LANGUAGE" ]; then
        SDP_LANGUAGE=sql
    fi
    if [ -z "$SDP_LANGUAGE" ] && [ "$YES" = false ]; then
        read -rp "Switch sdp output language: python or sql [default: python]: " _sdp_ans
        _sdp_ans="${_sdp_ans:-python}"
        _sdp_ans=$(printf '%s' "$_sdp_ans" | tr '[:upper:]' '[:lower:]')
        if [ "$_sdp_ans" != "python" ] && [ "$_sdp_ans" != "sql" ]; then
            echo "Error: Switch sdp_language must be 'python' or 'sql'."
            exit 1
        fi
        SDP_LANGUAGE="$_sdp_ans"
    fi
    if [ "$SSIS_OUTPUT" = "sparksql" ]; then
        SDP_LANGUAGE="${SDP_LANGUAGE:-sql}"
    else
        SDP_LANGUAGE="${SDP_LANGUAGE:-python}"
    fi
    if [ -z "$CUSTOM_PROMPT" ]; then
        if [ "$SSIS_OUTPUT" = "sparksql" ]; then
            CUSTOM_PROMPT="${SCRIPT_DIR}/ssis_to_sparksql_file_switch_prompt.yml"
        elif [ "$SSIS_OUTPUT" = "sdp" ] && [ "$SDP_LANGUAGE" = "sql" ]; then
            # SQL-language Lakeflow Declarative Pipeline (LDP SQL syntax, not Python @dp)
            CUSTOM_PROMPT="${SCRIPT_DIR}/ssis_to_databricks_sdp_sql_prompt.yml"
        else
            CUSTOM_PROMPT="${SCRIPT_DIR}/ssis_to_databricks_sdp_prompt.yml"
        fi
    fi
    SSIS_OUTPUT="${SSIS_OUTPUT:-sdp}"

    if [ "$SKIP_JOB_CREATE" = false ] && [ "$SSIS_OUTPUT" = "sparksql" ] && [ "$SKIP_SWITCH" = false ] && [ "$YES" = false ]; then
        read -rp "Create a SQL Warehouse Job for the converted files? (Y/n): " _job_ans
        [[ "$_job_ans" =~ ^[Nn]$ ]] && SKIP_JOB_CREATE=true
    fi
    if [ "$WAIT_FOR_SWITCH" = false ] && [ "$SSIS_OUTPUT" = "sparksql" ] && [ "$SKIP_SWITCH" = false ] && [ "$YES" = false ]; then
        read -rp "Wait for Switch LLM to complete before finishing? (y/N): " _wait_ans
        [[ "$_wait_ans" =~ ^[Yy]$ ]] && WAIT_FOR_SWITCH=true
    fi
fi

echo ""
echo "============================================"
echo "  SSIS-to-Databricks Migration"
echo "============================================"
echo "  Profile:            ${PROFILE}"
echo "  User email:         ${USER_EMAIL}"
[ "$SKIP_BLADEBRIDGE" = false ] && echo "  Input source:       ${INPUT_SOURCE}"
echo "  Output folder:      ${OUTPUT_FOLDER}"
echo "  BB error log:       ${ERROR_LOG_PATH:-${OUTPUT_FOLDER}/errors.log}"
if [ "$SKIP_TRANSPILER_CONFIG_PATH" = true ]; then
    echo "  Transpiler config:  (not passed; Lakebridge default)"
else
    echo "  Transpiler config:  ${TRANSPILER_CONFIG_PATH:-${DEFAULT_TRANSPILER_CONFIG_PATH}} (default if unset)"
fi
if [ "$SKIP_SWITCH" = true ]; then
    echo "  Workspace folder:   (N/A – Switch disabled)"
    echo "  Custom prompt:      (N/A – Switch disabled)"
    echo "  Switch catalog/UC:  (N/A – Switch disabled)"
    echo "  Medallion / DLP:    (skipped with Switch; no workspace notebooks to wire)"
else
    echo "  Workspace folder:   ${OUTPUT_WS_FOLDER}"
    echo "  Custom prompt:      ${CUSTOM_PROMPT}"
    echo "  SSIS output:        ${SSIS_OUTPUT} (sdp = Lakeflow pipeline; sparksql = one .sql per .py + SQL Warehouse Job)"
    if [ "$SSIS_OUTPUT" = "sparksql" ]; then
        echo "  Job creation:       $([ "$SKIP_JOB_CREATE" = true ] && echo 'skip' || echo 'yes (warehouse selection at Step 6)')"
    fi
    echo "  Catalog:            ${CATALOG}"
    echo "  Schema:             ${SCHEMA}"
    echo "  Volume:             ${VOLUME}"
    echo "  Foundation model:   ${FOUNDATION_MODEL}"
    echo "  Switch sdp_language: ${SDP_LANGUAGE}"
    if [ "$SINGLE_CATALOG" = true ]; then
        echo "  Layers (single):    ${CATALOG}  bronze=${BRONZE_SCHEMA}  silver=${SILVER_SCHEMA}  gold=${GOLD_SCHEMA}"
    else
        echo "  Bronze:             ${BRONZE_CATALOG}.${BRONZE_SCHEMA}"
        echo "  Silver:             ${SILVER_CATALOG}.${SILVER_SCHEMA}"
        echo "  Gold:               ${GOLD_CATALOG}.${GOLD_SCHEMA}"
    fi
    [ "$SSIS_OUTPUT" = "sparksql" ] && echo "  Switch completion:  $([ "$WAIT_FOR_SWITCH" = true ] && echo 'wait (synchronous)' || echo 'async (fires and continues)')"
    echo "  Pipeline name:      ${PIPELINE_NAME}"
    echo "  Pipeline compute:   $([ "$USE_SERVERLESS" = true ] && echo 'Serverless' || echo "Cluster Policy: ${CLUSTER_POLICY}")"
fi
echo "  BladeBridge:        $([ "$SKIP_BLADEBRIDGE" = true ] && echo 'skip' || ([ "$SKIP_DET_INSTALL" = true ] && echo 'run (no install)' || echo 'install + run'))"
echo "  Switch LLM:        $([ "$SKIP_SWITCH" = true ] && echo 'skip' || ([ "$SKIP_LLM_INSTALL" = true ] && echo 'run (no install)' || echo 'install + run'))"
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

# --- Update override file config_variables ---

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
    echo "Step 1a: Skipping deterministic transpiler install (--skip-det-install)."
fi

if [ "$SKIP_LLM_INSTALL" = false ]; then
    echo "Step 1b: Installing LLM transpiler (Switch)..."
    databricks labs lakebridge install-transpile --include-llm-transpiler true --interactive false $PROFILE_FLAG
    echo ""
else
    echo "Step 1b: Skipping LLM transpiler install (--skip-llm-install)."
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
            echo "  Or set: --transpiler-config-path /path/to/.../config.yml  or  --no-transpiler-config-path"
            exit 1
        fi
    fi
    # One argv array (never empty) — avoids "unbound variable" on bash 3.2 + set -u
    _lb_transpile=(databricks labs lakebridge transpile
        --source-dialect "ssis"
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
    echo "Step 2: Skipping BladeBridge (--skip-bladebridge)."
    if [ ! -d "$OUTPUT_FOLDER" ]; then
        echo "Error: output folder '${OUTPUT_FOLDER}' does not exist. Cannot skip BladeBridge."
        exit 1
    fi
    echo ""
fi


# =========================================================================
# Step 3: Preserve raw BladeBridge output, then move .py files to switch_input/
# =========================================================================

FIRST_PASS_DIR="${OUTPUT_FOLDER}/first_pass"
mkdir -p "${FIRST_PASS_DIR}"
find "${OUTPUT_FOLDER}" -maxdepth 1 -type f -exec cp {} "${FIRST_PASS_DIR}/" \;
file_count=$(find "${FIRST_PASS_DIR}" -type f | wc -l | tr -d ' ')
echo "  Preserved ${file_count} raw BladeBridge file(s) in: first_pass/"
echo ""

echo "Step 3: Separating job JSONs and moving .py files to switch_input/..."

# Move JSON files (orchestration definitions) to databricks_jobs/ for reference
JOBS_DIR="${OUTPUT_FOLDER}/databricks_jobs"
shopt -s nullglob
json_files=("${OUTPUT_FOLDER}"/*.json)
shopt -u nullglob

if [ ${#json_files[@]} -gt 0 ]; then
    mkdir -p "${JOBS_DIR}"
    for f in "${json_files[@]}"; do
        mv "$f" "${JOBS_DIR}/"
        echo "  Moved: $(basename "$f") -> databricks_jobs/"
    done
    echo "  ${#json_files[@]} job JSON(s) preserved for orchestration reference."
fi

SWITCH_INPUT_DIR="${OUTPUT_FOLDER}/switch_input"
mkdir -p "${SWITCH_INPUT_DIR}"

shopt -s nullglob
py_files=("${OUTPUT_FOLDER}"/*.py)
shopt -u nullglob

if [ ${#py_files[@]} -eq 0 ]; then
    # .py files may already be in switch_input/ from a prior run — reuse them
    shopt -s nullglob
    _existing_py=("${SWITCH_INPUT_DIR}"/*.py)
    shopt -u nullglob
    if [ ${#_existing_py[@]} -gt 0 ]; then
        echo "  .py files already in switch_input/ (${#_existing_py[@]} file(s)); skipping move."
        py_files=("${_existing_py[@]}")
    else
        echo "Error: no .py files found in ${OUTPUT_FOLDER} or switch_input/ (expected after BladeBridge)."
        exit 1
    fi
else
    for f in "${py_files[@]}"; do
        mv "$f" "${SWITCH_INPUT_DIR}/"
        echo "  Moved: $(basename "$f") -> switch_input/"
    done
fi

if [ "$SKIP_SWITCH" = true ]; then
    echo "  ${#py_files[@]} Python file(s) in switch_input/ (Switch disabled)."
else
    echo "  ${#py_files[@]} Python file(s) ready for LLM conversion."
fi

# Derive pipeline name from first .py file now that switch_input/ is populated
if [ -z "$PIPELINE_NAME" ]; then
    shopt -s nullglob
    _first_py=("${SWITCH_INPUT_DIR}"/*.py)
    shopt -u nullglob
    if [ ${#_first_py[@]} -gt 0 ]; then
        PIPELINE_NAME="$(basename "${_first_py[0]}" .py)"
    else
        PIPELINE_NAME="$(basename "$OUTPUT_FOLDER")"
    fi
fi
echo ""

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

# Update switch_config.yml on workspace
SWITCH_CONFIG_WS_PATH="/Users/${USER_EMAIL}/.lakebridge/switch/resources/switch_config.yml"
SWITCH_CONFIG_LOCAL="${OUTPUT_FOLDER}/switch_config.yml"
if [ "$SSIS_OUTPUT" = "sparksql" ]; then
    SWITCH_TARGET_TYPE=file
    SWITCH_OUTPUT_EXT="sql"
else
    SWITCH_TARGET_TYPE=file
    SWITCH_OUTPUT_EXT="py"
fi
if [ -n "$SWITCH_OUTPUT_EXT" ]; then
cat > "$SWITCH_CONFIG_LOCAL" <<SWITCHEOF
# Switch configuration file
# Auto-generated by ssis_switch_pipeline run.sh

target_type: "${SWITCH_TARGET_TYPE}"
output_extension: "${SWITCH_OUTPUT_EXT}"
source_format: "generic"
comment_lang: "English"
log_level: "INFO"
token_count_threshold: 50000
concurrency: 4
max_fix_attempts: 0

conversion_prompt_yaml: ${WS_PROMPT_PATH}

sql_output_dir:
request_params:
sdp_language: ${SDP_LANGUAGE}
SWITCHEOF
else
cat > "$SWITCH_CONFIG_LOCAL" <<SWITCHEOF
# Switch configuration file
# Auto-generated by ssis_switch_pipeline run.sh

target_type: "${SWITCH_TARGET_TYPE}"
source_format: "generic"
comment_lang: "English"
log_level: "INFO"
token_count_threshold: 50000
concurrency: 4
max_fix_attempts: 0

conversion_prompt_yaml: ${WS_PROMPT_PATH}

sql_output_dir:
request_params:
sdp_language: ${SDP_LANGUAGE}
SWITCHEOF
fi

databricks workspace import "${SWITCH_CONFIG_WS_PATH}" \
    --file "$SWITCH_CONFIG_LOCAL" \
    --format AUTO \
    --overwrite \
    $PROFILE_FLAG
echo "  Updated switch_config.yml at: ${SWITCH_CONFIG_WS_PATH}"
echo "  target_type: ${SWITCH_TARGET_TYPE} (sparksql: file+sql, sdp: file+py)"
echo "  sdp_language: ${SDP_LANGUAGE}"
echo ""

# =========================================================================
# Step 5: Run Switch LLM conversion
# =========================================================================

echo "Step 5: Running Switch LLM transpiler..."
echo ""

_switch_log=$(mktemp)
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
if [ "${SSIS_OUTPUT:-sdp}" = "sparksql" ]; then
    echo "  LLM conversion in progress. Spark SQL artifacts are written under ${OUTPUT_WS_FOLDER} when completed."
else
    echo "  LLM conversion is in progress. Python .py files at: ${OUTPUT_WS_FOLDER} when completed"
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
            [ "$_sw_result" != "SUCCESS" ] && echo "  Warning: Switch did not succeed. Check workspace output before running the job."
            break
        fi
        echo "  Switch state: ${_sw_state} — waiting 30s..."
        sleep 30
    done
    echo ""
fi

fi  # end SKIP_SWITCH guard (Steps 4, 5)

# =========================================================================
# Step 6: Create Lakeflow Declarative Pipeline
# =========================================================================

PIPELINE_ID=""
WS_HOST=""

if [ "$SKIP_SWITCH" = true ]; then
    echo "Step 6: Skipping Lakeflow Declarative Pipeline (Switch/LLM not run; no workspace notebooks to reference)."
    echo ""
    echo "============================================"
    echo "  Run finished (Switch off)"
    echo "============================================"
    echo "  Notebooks:          (N/A – run Switch to publish notebooks to ${OUTPUT_WS_FOLDER})"
    echo "  BladeBridge:        ${OUTPUT_FOLDER}"
    echo "  First pass:         ${FIRST_PASS_DIR}"
    [ -d "${JOBS_DIR:-}" ] && echo "  Job JSONs:          ${JOBS_DIR}"
    echo "  Lakeflow Pipeline:  (skipped; requires Switch output)"
    echo "============================================"
elif [ "${SSIS_OUTPUT:-sdp}" = "sparksql" ]; then

JOB_WAS_CREATED=false
JOB_ID=""

if [ "$SKIP_JOB_CREATE" = true ]; then
    echo "Step 6: Skipping SQL Warehouse Job creation."
    echo ""
else

echo "Step 6: Creating Databricks SQL Warehouse Job..."
echo ""

if [ -z "$JOB_NAME" ]; then
    _last_py=$(ls -1 "${SWITCH_INPUT_DIR}"/*.py 2>/dev/null | sort | tail -1 || true)
    if [ -n "$_last_py" ]; then
        JOB_NAME="$(basename "${_last_py%.py}") SQL Job"
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
    SSIS_SWITCH_INPUT_DIR="${SWITCH_INPUT_DIR}"
    export SSIS_SWITCH_INPUT_DIR OUTPUT_WS_FOLDER WAREHOUSE_ID JOB_NAME JOB_SPEC_FILE \
           GOLD_CATALOG GOLD_SCHEMA BRONZE_CATALOG BRONZE_SCHEMA \
           SILVER_CATALOG SILVER_SCHEMA
    python3 <<'PYEOF'
import os, re, json

switch_input_dir = os.environ['SSIS_SWITCH_INPUT_DIR']
output_ws_folder = os.environ['OUTPUT_WS_FOLDER']
warehouse_id = os.environ['WAREHOUSE_ID']
job_name = os.environ['JOB_NAME']
job_spec_file = os.environ['JOB_SPEC_FILE']

py_files = sorted([f for f in os.listdir(switch_input_dir) if f.lower().endswith('.py')])

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
for fname in py_files:
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
for fname in py_files:
    base = os.path.splitext(fname)[0]
    key = re.sub(r'[^a-zA-Z0-9_]', '_', base)
    raw_deps[key] = [re.sub(r'[^a-zA-Z0-9_]', '_', os.path.splitext(o)[0])
                     for o in py_files if o != fname and reads[fname] & writes[o]]

def has_path(graph, src, dst, visited=None):
    if visited is None: visited = set()
    if src == dst: return True
    visited.add(src)
    return any(has_path(graph, n, dst, visited) for n in graph.get(src, []) if n not in visited)

clean_deps = {k: list(v) for k, v in raw_deps.items()}
for key, deps in raw_deps.items():
    for dep in deps:
        if dep in clean_deps.get(key, []) and key in clean_deps.get(dep, []):
            clean_deps[dep] = [x for x in clean_deps[dep] if x != key]
            print(f"  Note: broke circular dependency {dep} → {key} (kept {key} → {dep})", flush=True)

tasks = []
for fname in py_files:
    base = os.path.splitext(fname)[0]
    key = re.sub(r'[^a-zA-Z0-9_]', '_', base)
    deps = [{"task_key": d} for d in clean_deps.get(key, [])]
    task = {
        "task_key": key,
        "sql_task": {
            "file": {"path": f"{output_ws_folder}/{base}.sql"},
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

fi  # end SKIP_JOB_CREATE guard

echo "============================================"
echo "  Run finished (SSIS -> Spark SQL .sql)"
echo "============================================"
echo "  Artifacts:          see ${OUTPUT_WS_FOLDER} and local ${OUTPUT_FOLDER} (Switch layout)"
echo "  BladeBridge:        ${OUTPUT_FOLDER}"
echo "  First pass:         ${FIRST_PASS_DIR}"
[ -d "${JOBS_DIR:-}" ] && echo "  Job JSONs:          ${JOBS_DIR}"
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

# Build notebook paths from switch_input/ filenames (these are the files Switch will create)
    nb_list=""
    shopt -s nullglob
    switch_py_files=("${SWITCH_INPUT_DIR}"/*.py)
    shopt -u nullglob
    for f in "${switch_py_files[@]}"; do
        nb_name=$(basename "$f" .py)
        nb_list="${nb_list}${OUTPUT_WS_FOLDER}/${nb_name}
"
    done

# Generate pipeline spec
    PIPELINE_SPEC="${OUTPUT_FOLDER}/pipeline_spec.json"
    python3 << PYEOF > "$PIPELINE_SPEC"
import json, sys
notebooks = """${nb_list}""".strip().split('\n')
use_serverless = "${USE_SERVERLESS}" == "true"
cluster_policy = "${CLUSTER_POLICY}"

spec = {
    "name": "${PIPELINE_NAME}",
    "catalog": "${BRONZE_CATALOG}",
    "target": "${BRONZE_SCHEMA}",
    "allow_duplicate_names": True,
    "libraries": [{"file": {"path": f"{nb}.py"}} for nb in notebooks if nb],
    "configuration": {
        "bronze_catalog": "${BRONZE_CATALOG}",
        "bronze_schema": "${BRONZE_SCHEMA}",
        "silver_catalog": "${SILVER_CATALOG}",
        "silver_schema": "${SILVER_SCHEMA}",
        "gold_catalog": "${GOLD_CATALOG}",
        "gold_schema": "${GOLD_SCHEMA}"
    }
}

if use_serverless:
    spec["serverless"] = True
    spec["photon"] = True
else:
    spec["serverless"] = False
    spec["clusters"] = [
        {
            "label": "default",
            "policy_id": cluster_policy
        }
    ]

print(json.dumps(spec, indent=2))
PYEOF

    echo "  Pipeline spec: ${PIPELINE_SPEC}"

# Create pipeline
    if output=$(databricks pipelines create --json @"$PIPELINE_SPEC" $PROFILE_FLAG -o json 2>&1); then
        PIPELINE_ID=$(echo "$output" | python3 -c "import sys,json; print(json.load(sys.stdin)['pipeline_id'])")
        echo "  Created pipeline: ${PIPELINE_NAME} (ID: ${PIPELINE_ID})"
    else
        echo "  WARNING: Pipeline creation failed: ${output}"
        echo "  You can create it manually using: databricks pipelines create --json @${PIPELINE_SPEC} $PROFILE_FLAG"
    fi

    echo ""
    echo "============================================"
    echo "  Pipeline Complete"
    echo "============================================"
    echo "  Python files:       ${OUTPUT_WS_FOLDER}"
    echo "  BladeBridge:        ${OUTPUT_FOLDER}"
    echo "  First pass:         ${FIRST_PASS_DIR}"
    [ -d "${JOBS_DIR:-}" ] && echo "  Job JSONs:          ${JOBS_DIR}"
    if [ -n "$PIPELINE_ID" ]; then
        echo "  Lakeflow Pipeline:  ${PIPELINE_NAME} (ID: ${PIPELINE_ID})"
        [ -n "$WS_HOST" ] && echo "  Pipeline URL:       ${WS_HOST}/pipelines/${PIPELINE_ID}"
    else
        echo "  Lakeflow Pipeline:  (not created — see pipeline_spec.json)"
    fi
    echo "============================================"
fi
