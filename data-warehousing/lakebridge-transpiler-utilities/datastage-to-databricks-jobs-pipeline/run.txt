#!/bin/bash
# End-to-end automation for DataStage → Databricks migration using Lakebridge.
#
# A DataStage migration produces two artifacts per sequence job: a set of
# notebooks (one per stage) and a Databricks-jobs JSON that orchestrates them.
# Lakebridge ships two transpilers — BladeBridge (deterministic) and Switch
# (LLM) — which together do most of the conversion. This script wires them
# together with the additional steps needed to make the output runnable on
# Databricks.
#
# Pipeline overview:
#   1.  Install BladeBridge and Switch
#   2.  Run BladeBridge — produces a Python file per DataStage stage and a
#       Databricks-jobs JSON per sequence job
#   3.  Stage BladeBridge output into working directories (jobs JSON, notebooks
#       for the LLM, supplemental module, raw XML)
#   4.  (Optional) Map source-table names to Unity Catalog 3-level names
#   5.  Reconstruct each job's orchestration from the DataStage XML, normalize
#       notebook paths and parameters, and add the widgets the converted
#       notebooks need at runtime
#   6.  Apply mechanical fixes to the BladeBridge notebooks that the LLM can't
#       reliably do, and tag Load notebooks that need a Delta watermark pattern
#       from the LLM
#   7.  Drop watermark-writer tasks whose work now lives inside the Load
#       notebook
#   8.  Reconcile job parameters with the widgets each notebook actually
#       declares or fetches (drops orphan parameters before the LLM runs)
#   9.  Place the custom Switch prompt at the workspace path Switch reads from
#       and update switch_config.yml
#   10. Run Switch — finishes the per-notebook conversion against the prompt
#   11. Place the BladeBridge supplemental module at the workspace path the
#       notebooks import from
#   12. Create the Databricks jobs from the JSON definitions
#
# When running from a cluster web terminal, all paths under /Workspace/ are
# already on the cluster filesystem; the "place at" steps copy from one
# workspace path to another (no external upload). When running locally, the
# same steps push files from the local disk to the workspace.
#
# Prerequisite: `databricks labs install lakebridge`
#
# Default override JSON and prompt YAML are located alongside this script.
# Pass -r or -x to use files from other locations.
#
# Usage:
#   ./run.sh [options]
#
# Options:
#   -i, --input-source       Path to DataStage source files (XML exports)
#   -o, --output-folder      Output folder (on cluster: /Workspace/... base path; on local: any path)
#   -w, --output-ws-folder   Workspace folder for notebooks (must start with /Workspace/; local only)
#   -e, --user-email         User email override (default: auto-detected from Databricks profile)
#   -p, --profile            Databricks CLI profile (default: DEFAULT)
#   -c, --catalog            Databricks catalog name (default: lakebridge)
#   -s, --schema             Databricks schema name (default: switch)
#   -v, --volume             UC Volume name (default: switch_volume)
#   -m, --foundation-model   Foundation model endpoint (default: databricks-claude-sonnet-4-5)
#   -t, --target-tech        BladeBridge target technology: PYSPARK or SPARKSQL (default: PYSPARK)
#   -r, --overrides-file     Override JSON for BladeBridge (default: sample_override.json in script dir)
#       --error-file-path    Local path for BladeBridge conversion error log (default: <output-folder>/errors.log)
#       --transpiler-config-path  Path to BladeBridge config.yml (default: see DEFAULT_TRANSPILER_CONFIG_PATH;
#                                 always passed to transpile so the CLI does not use a bad built-in path)
#       --no-transpiler-config-path  Do not pass --transpiler-config-path (Lakebridge chooses the path)
#   -x, --custom-prompt      Custom Switch prompt YAML (default: datastage_to_databricks_prompt.yml in script dir)
#       --compute            Job compute type: serverless or classic (default: serverless)
#       --cloud              Cloud provider: azure, aws, or gcp (auto-detected from profile URL if not set)
#       --node-type          Worker node type for classic compute (default: cloud-specific standard)
#       --table-mapping      CSV file mapping source tables to UC 3-level names
#       --skip-det-install   Skip BladeBridge installation only (still run conversion)
#       --skip-llm-install   Skip Switch LLM installation only (still run conversion)
#       --skip-bladebridge   Skip BladeBridge entirely (install + conversion; use existing output)
#       --skip-switch        Skip Switch LLM entirely (no Switch-only prompts; Steps 4–5 skipped)
#   -h, --help               Show this help message
#
# All flags are prompted interactively if not provided.

set -euo pipefail

CLEANUP_FILES=()
cleanup() {
    for f in "${CLEANUP_FILES[@]:-}"; do
        [[ -n "$f" ]] && rm -rf "$f" 2>/dev/null
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
TARGET_TECH=""
OVERRIDES_FILE=""
ERROR_LOG_PATH=""
TRANSPILER_CONFIG_PATH=""
SKIP_TRANSPILER_CONFIG_PATH=false
CUSTOM_PROMPT=""
CLOUD=""
COMPUTE_TYPE=""
NODE_TYPE=""
TABLE_MAPPING=""
UC_CATALOG=""
UC_SCHEMA=""
SKIP_DET_INSTALL=false
SKIP_LLM_INSTALL=false
SKIP_BLADEBRIDGE=false
SKIP_SWITCH=false

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
        -t|--target-tech)        TARGET_TECH="$2"; shift 2 ;;
        -r|--overrides-file)     OVERRIDES_FILE="$2"; shift 2 ;;
        --error-file-path)        ERROR_LOG_PATH="$2"; shift 2 ;;
        --transpiler-config-path) TRANSPILER_CONFIG_PATH="$2"; shift 2 ;;
        --no-transpiler-config-path) SKIP_TRANSPILER_CONFIG_PATH=true; shift ;;
        -x|--custom-prompt)      CUSTOM_PROMPT="$2"; shift 2 ;;
        --cloud)                 CLOUD="$2"; shift 2 ;;
        --node-type)             NODE_TYPE="$2"; shift 2 ;;
        --compute)               COMPUTE_TYPE="$2"; shift 2 ;;
        --table-mapping)         TABLE_MAPPING="$2"; shift 2 ;;
        --skip-det-install)      SKIP_DET_INSTALL=true; shift ;;
        --skip-llm-install)      SKIP_LLM_INSTALL=true; shift ;;
        --skip-bladebridge)      SKIP_BLADEBRIDGE=true; SKIP_DET_INSTALL=true; shift ;;
        --skip-switch)           SKIP_SWITCH=true; SKIP_LLM_INSTALL=true; shift ;;
        -h|--help)               usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

# --- Defaults for override and prompt (sibling files) ---

if [ -z "$OVERRIDES_FILE" ]; then
    OVERRIDES_FILE="${SCRIPT_DIR}/sample_override.json"
fi
if [ ! -f "$OVERRIDES_FILE" ]; then
    echo "Error: override file '${OVERRIDES_FILE}' not found."
    exit 1
fi

if [ -z "$CUSTOM_PROMPT" ]; then
    CUSTOM_PROMPT="${SCRIPT_DIR}/datastage_to_databricks_prompt.yml"
fi

# --- Prompt for missing values ---

if [ -z "$PROFILE" ]; then
    read -rp "Databricks CLI profile [default: DEFAULT]: " PROFILE
    PROFILE="${PROFILE:-DEFAULT}"
fi

PROFILE_FLAG="-p $PROFILE"

ON_CLUSTER=false
if [ -n "${DB_CLUSTER_ID:-}" ] || \
   [ -d "/databricks/spark" ] || \
   [ -d "/databricks/python" ] || \
   [ -d "/databricks/driver" ]; then
    ON_CLUSTER=true
fi

# Derive cloud from the workspace host in the Databricks CLI profile config
CLOUD_DERIVED=""
CLOUD_DERIVED=$(python3 - "$PROFILE" <<'PYEOF' 2>/dev/null
import configparser, os, sys
profile = sys.argv[1]
cfg = configparser.ConfigParser()
cfg.read(os.path.expanduser('~/.databrickscfg'))
host = ''
if cfg.has_section(profile):
    host = cfg.get(profile, 'host', fallback='')
if not host and profile.upper() == 'DEFAULT':
    host = cfg.get('DEFAULT', 'host', fallback='')
host = host.rstrip('/')
if 'azuredatabricks' in host:
    print('azure')
elif 'gcp.databricks' in host:
    print('gcp')
elif 'databricks' in host:
    print('aws')
PYEOF
) || CLOUD_DERIVED=""

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

# --- Switch (LLM) first: "no" skips Switch-only prompts and Steps 4-5
if [ "$SKIP_SWITCH" = false ]; then
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

# --- BladeBridge: "no" skips BladeBridge-only prompts and Step 2
if [ "$SKIP_BLADEBRIDGE" = false ]; then
    read -rp "Run BladeBridge deterministic conversion? (Y/n): " run_bb_answer
    if [[ "$run_bb_answer" =~ ^[Nn]$ ]]; then
        SKIP_BLADEBRIDGE=true
        SKIP_DET_INSTALL=true
    elif [ "$SKIP_DET_INSTALL" = false ]; then
        read -rp "  Install BladeBridge transpiler first? (y/N): " install_bb_answer
        if [[ ! "$install_bb_answer" =~ ^[Yy]$ ]]; then
            SKIP_DET_INSTALL=true
        fi
    fi
fi

if [ "$SKIP_BLADEBRIDGE" = false ]; then
    if [ -z "$INPUT_SOURCE" ]; then
        read -rp "Path to DataStage source files (XML exports): " INPUT_SOURCE
    fi
    if [ ! -e "$INPUT_SOURCE" ]; then
        echo "Error: input source '${INPUT_SOURCE}' does not exist."
        exit 1
    fi
fi

if [ "$ON_CLUSTER" = true ]; then
    # ── Cluster web terminal ─────────────────────────────────────────────────
    # /Workspace/ paths persist across cluster restarts.
    # One base path → two subfolders: pipeline/ (staging) and notebooks/ (LLM output).
    if [ -z "$OUTPUT_FOLDER" ]; then
        read -rp "Workspace output folder (must start with /Workspace/): " OUTPUT_FOLDER
    fi
    if [[ ! "$OUTPUT_FOLDER" == /Workspace/* ]]; then
        echo "Error: on cluster, workspace output folder must start with /Workspace/"
        exit 1
    fi
    OUTPUT_FOLDER="${OUTPUT_FOLDER%/}"
    OUTPUT_WS_FOLDER="${OUTPUT_FOLDER}/notebooks"
    OUTPUT_FOLDER="${OUTPUT_FOLDER}/pipeline"
    echo "  Staging folder:   ${OUTPUT_FOLDER}"
    echo "  Notebooks folder: ${OUTPUT_WS_FOLDER}"
    echo ""
else
    # ── Local machine ────────────────────────────────────────────────────────
    if [ -z "$OUTPUT_FOLDER" ]; then
        if [ "$SKIP_BLADEBRIDGE" = true ]; then
            read -rp "Output folder (use existing BladeBridge/switch state): " OUTPUT_FOLDER
        else
            read -rp "Output folder for BladeBridge results: " OUTPUT_FOLDER
        fi
    fi
    if [ -z "$OUTPUT_FOLDER" ]; then
        echo "Error: output folder is required."
        exit 1
    fi
fi

if [ "$SKIP_BLADEBRIDGE" = false ]; then
    if [ -z "$TARGET_TECH" ]; then
        read -rp "BladeBridge target technology (PYSPARK or SPARKSQL) [default: PYSPARK]: " TARGET_TECH
    fi
    TARGET_TECH="${TARGET_TECH:-PYSPARK}"
else
    TARGET_TECH="${TARGET_TECH:-PYSPARK}"
fi

if [ "$SKIP_SWITCH" = true ]; then
    if [ -z "$OUTPUT_WS_FOLDER" ]; then
        OUTPUT_WS_FOLDER="/Workspace/Users/${USER_EMAIL}/$(basename "$OUTPUT_FOLDER")"
    fi
    CATALOG="${CATALOG:-lakebridge}"
    SCHEMA="${SCHEMA:-switch}"
    VOLUME="${VOLUME:-switch_volume}"
    FOUNDATION_MODEL="${FOUNDATION_MODEL:-databricks-claude-sonnet-4-5}"
else
    if [ "$ON_CLUSTER" = false ] && [ -z "$OUTPUT_WS_FOLDER" ]; then
        read -rp "Workspace output folder (must start with /Workspace/): " OUTPUT_WS_FOLDER
    fi
    if [[ ! "$OUTPUT_WS_FOLDER" == /Workspace/* ]]; then
        echo "Error: workspace output folder must start with /Workspace/"
        exit 1
    fi
    if [ -z "$CATALOG" ]; then
        read -rp "Catalog name for Switch artifacts [default: lakebridge]: " CATALOG
        CATALOG="${CATALOG:-lakebridge}"
    fi
    if [ -z "$SCHEMA" ]; then
        read -rp "Schema name for Switch artifacts [default: switch]: " SCHEMA
        SCHEMA="${SCHEMA:-switch}"
    fi
    if [ -z "$VOLUME" ]; then
        read -rp "UC Volume name for Switch artifacts [default: switch_volume]: " VOLUME
        VOLUME="${VOLUME:-switch_volume}"
    fi
    if [ -z "$FOUNDATION_MODEL" ]; then
        read -rp "Foundation model endpoint [default: databricks-claude-sonnet-4-5]: " FOUNDATION_MODEL
        FOUNDATION_MODEL="${FOUNDATION_MODEL:-databricks-claude-sonnet-4-5}"
    fi
    CATALOG="${CATALOG// /}"
    SCHEMA="${SCHEMA// /}"
    VOLUME="${VOLUME// /}"
fi

if [[ ! "$OUTPUT_WS_FOLDER" == /Workspace/* ]]; then
    echo "Error: workspace output folder must start with /Workspace/"
    exit 1
fi

if [ -z "$COMPUTE_TYPE" ]; then
    read -rp "Generated Databricks job compute type (serverless or classic) [default: serverless]: " COMPUTE_TYPE
    COMPUTE_TYPE="${COMPUTE_TYPE:-serverless}"
fi
COMPUTE_TYPE=$(echo "$COMPUTE_TYPE" | tr '[:upper:]' '[:lower:]')
if [ "$COMPUTE_TYPE" != "serverless" ] && [ "$COMPUTE_TYPE" != "classic" ]; then
    echo "Error: compute type must be serverless or classic."
    exit 1
fi

if [ "$COMPUTE_TYPE" = "classic" ]; then
    if [ -z "$CLOUD" ]; then
        if [ -n "$CLOUD_DERIVED" ]; then
            read -rp "Cloud provider (azure, aws, gcp) [detected: ${CLOUD_DERIVED}]: " CLOUD
            CLOUD="${CLOUD:-$CLOUD_DERIVED}"
        else
            read -rp "Cloud provider (azure, aws, gcp) [default: azure]: " CLOUD
            CLOUD="${CLOUD:-azure}"
        fi
    fi
    CLOUD=$(echo "$CLOUD" | tr '[:upper:]' '[:lower:]')
    case "$CLOUD" in
        azure) DEFAULT_NODE_TYPE="Standard_D4ds_v5" ;;
        aws)   DEFAULT_NODE_TYPE="i3.xlarge" ;;
        gcp)   DEFAULT_NODE_TYPE="n1-standard-4" ;;
        *)     echo "Error: cloud must be azure, aws, or gcp."; exit 1 ;;
    esac
    if [ -z "$NODE_TYPE" ]; then
        read -rp "Worker node type [default: ${DEFAULT_NODE_TYPE}]: " NODE_TYPE
        NODE_TYPE="${NODE_TYPE:-$DEFAULT_NODE_TYPE}"
    fi
fi

# --- Table mapping for Unity Catalog 3-level namespace ---

if [ -z "$TABLE_MAPPING" ]; then
    default_mapping="${SCRIPT_DIR}/table_mapping.csv"
    if [ -f "$default_mapping" ]; then
        has_entries=$(grep -v '^\s*#' "$default_mapping" | grep -v '^\s*$' | head -1 || true)
        if [ -n "$has_entries" ]; then
            read -rp "Table mapping file found (${default_mapping}). Use it? (Y/n): " use_mapping
            if [[ ! "$use_mapping" =~ ^[Nn]$ ]]; then
                TABLE_MAPPING="$default_mapping"
            fi
        fi
    fi

    if [ -z "$TABLE_MAPPING" ]; then
        echo "No table mapping file. Enter a default UC catalog and schema for all tables,"
        echo "or press Enter to skip table namespace mapping."
        read -rp "Default UC catalog [skip]: " UC_CATALOG
        if [ -n "$UC_CATALOG" ]; then
            read -rp "Default UC schema: " UC_SCHEMA
            if [ -z "$UC_SCHEMA" ]; then
                echo "Error: UC schema is required when catalog is specified."
                exit 1
            fi
        fi
    fi
fi

if [ -n "$TABLE_MAPPING" ] && [ ! -f "$TABLE_MAPPING" ]; then
    echo "Error: table mapping file '${TABLE_MAPPING}' not found."
    exit 1
fi

echo ""
echo "============================================"
echo "  DataStage-to-Databricks Migration"
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
echo "  Workspace folder:   ${OUTPUT_WS_FOLDER}"
echo "  Target technology:  ${TARGET_TECH}"
echo "  Override file:      ${OVERRIDES_FILE}"
if [ "$SKIP_SWITCH" = true ]; then
    echo "  Custom prompt:      (N/A - Switch disabled)"
    echo "  Switch catalog/UC:  (N/A - Switch disabled)"
else
    echo "  Custom prompt:      ${CUSTOM_PROMPT}"
    echo "  Catalog:            ${CATALOG}"
    echo "  Schema:             ${SCHEMA}"
    echo "  Volume:             ${VOLUME}"
    echo "  Foundation model:   ${FOUNDATION_MODEL}"
fi
echo "  Job compute:        ${COMPUTE_TYPE}"
[ "$COMPUTE_TYPE" = "classic" ] && echo "  Cloud / Node type:  ${CLOUD} / ${NODE_TYPE}"
[ -n "$TABLE_MAPPING" ] && echo "  Table mapping:      ${TABLE_MAPPING}"
[ -n "$UC_CATALOG" ] && echo "  UC namespace:       ${UC_CATALOG}.${UC_SCHEMA}.*"
[ -z "$TABLE_MAPPING" ] && [ -z "$UC_CATALOG" ] && echo "  Table mapping:      (skipped)"
echo "  BladeBridge:        $([ "$SKIP_BLADEBRIDGE" = true ] && echo 'skip' || ([ "$SKIP_DET_INSTALL" = true ] && echo 'run (no install)' || echo 'install + run'))"
echo "  Switch LLM:        $([ "$SKIP_SWITCH" = true ] && echo 'skip' || ([ "$SKIP_LLM_INSTALL" = true ] && echo 'run (no install)' || echo 'install + run'))"
echo "============================================"
echo ""
read -rp "Proceed? (y/N): " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi
echo ""

# --- Update override file config_variables ---

TASK_PATH="${OUTPUT_WS_FOLDER#/}"
SED_ARGS=(
    -e "s|\"USER_NAME\": \".*\"|\"USER_NAME\": \"${USER_EMAIL}\"|"
    -e "s|\"EMAIL_ADDRESS\": \".*\"|\"EMAIL_ADDRESS\": \"${USER_EMAIL}\"|"
    -e "s|\"SUCCESS_EMAIL_ADDRESS\": \".*\"|\"SUCCESS_EMAIL_ADDRESS\": \"${USER_EMAIL}\"|"
    -e "s|\"FAILURE_EMAIL_ADDRESS\": \".*\"|\"FAILURE_EMAIL_ADDRESS\": \"${USER_EMAIL}\"|"
    -e "s|\"TASK_PATH\": \".*\"|\"TASK_PATH\": \"${TASK_PATH}\"|"
)
if [ "$COMPUTE_TYPE" = "classic" ]; then
    SED_ARGS+=(-e "s|\"NODE_TYPE\": \".*\"|\"NODE_TYPE\": \"${NODE_TYPE}\"|")
fi
sed -i.bak "${SED_ARGS[@]}" "$OVERRIDES_FILE"
rm -f "${OVERRIDES_FILE}.bak"

# =========================================================================
# Step 1: Install transpilers
# =========================================================================

if [ "$SKIP_DET_INSTALL" = false ]; then
    echo "Step 1a: Installing deterministic transpiler (BladeBridge)..."
    (yes || true) | databricks labs lakebridge install-transpile $PROFILE_FLAG
    echo ""
else
    echo "Step 1a: Skipping BladeBridge install."
fi

if [ "$SKIP_LLM_INSTALL" = false ]; then
    echo "Step 1b: Installing LLM transpiler (Switch)..."
    (yes || true) | databricks labs lakebridge install-transpile --include-llm-transpiler true $PROFILE_FLAG
    echo ""
else
    echo "Step 1b: Skipping Switch LLM install."
fi
echo ""

# =========================================================================
# Step 2: Run BladeBridge transpilation
# =========================================================================

if [ "$SKIP_BLADEBRIDGE" = false ]; then
    echo "Step 2: Running BladeBridge transpilation (DataStage)..."
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
    _lb_transpile=(databricks labs lakebridge transpile
        --source-dialect "datastage"
        --target-technology "${TARGET_TECH}"
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
# Step 3: Preserve raw BladeBridge output, then separate non-convertible files
# =========================================================================

FIRST_PASS_DIR="${OUTPUT_FOLDER}/first_pass"
mkdir -p "${FIRST_PASS_DIR}"
find "${OUTPUT_FOLDER}" -maxdepth 1 -type f -exec cp {} "${FIRST_PASS_DIR}/" \;
file_count=$(find "${FIRST_PASS_DIR}" -type f | wc -l | tr -d ' ')
echo "  Preserved ${file_count} raw BladeBridge file(s) in: first_pass/"
echo ""

echo "Step 3: Separating non-convertible files from BladeBridge output..."

JOBS_DIR="${OUTPUT_FOLDER}/databricks_jobs"
JOBS_XML_DIR="${OUTPUT_FOLDER}/databricks_jobs/input"
SUPPLEMENTS_DIR="${OUTPUT_FOLDER}/supplements"

# Stage DataStage XML inputs to a stable location next to the JSON output so
# Steps 5 and 6 can read the dependency graph. INPUT_SOURCE may be a single
# .dsx/.xml file or a directory; copy any .xml files we find.
mkdir -p "${JOBS_XML_DIR}"
if [ -n "${INPUT_SOURCE:-}" ] && [ -e "${INPUT_SOURCE}" ]; then
    if [ -d "${INPUT_SOURCE}" ]; then
        find "${INPUT_SOURCE}" -maxdepth 2 -name "*.xml" -exec cp {} "${JOBS_XML_DIR}/" \; 2>/dev/null || true
    elif [ -f "${INPUT_SOURCE}" ] && [[ "${INPUT_SOURCE}" == *.xml ]]; then
        cp "${INPUT_SOURCE}" "${JOBS_XML_DIR}/" 2>/dev/null || true
    fi
fi
xml_staged=$(find "${JOBS_XML_DIR}" -maxdepth 1 -name "*.xml" 2>/dev/null | wc -l | tr -d ' ')
if [ "${xml_staged}" -gt 0 ]; then
    echo "  Staged ${xml_staged} XML file(s) to: ${JOBS_XML_DIR}/"
fi

shopt -s nullglob
json_files=("${OUTPUT_FOLDER}"/*.json)
shopt -u nullglob

if [ ${#json_files[@]} -gt 0 ]; then
    mkdir -p "${JOBS_DIR}"
    for f in "${json_files[@]}"; do
        mv "$f" "${JOBS_DIR}/"
        echo "  Moved: $(basename "$f") -> databricks_jobs/"
    done
else
    jj_count=$(find "${JOBS_DIR}" -maxdepth 1 -name "*.json" 2>/dev/null | wc -l | tr -d ' ')
    if [ "$jj_count" -gt 0 ]; then
        echo "  databricks_jobs/ already contains ${jj_count} JSON file(s) — skipping move (rerun)."
    fi
fi

if [ -f "${OUTPUT_FOLDER}/databricks_conversion_supplements.py" ]; then
    mkdir -p "${SUPPLEMENTS_DIR}"
    mv "${OUTPUT_FOLDER}/databricks_conversion_supplements.py" "${SUPPLEMENTS_DIR}/"
    echo "  Moved: databricks_conversion_supplements.py -> supplements/"
fi

SWITCH_INPUT_DIR="${OUTPUT_FOLDER}/switch_input"
mkdir -p "${SWITCH_INPUT_DIR}"

py_root_files=()
while IFS= read -r -d '' f; do
    py_root_files+=("$f")
done < <(find "${OUTPUT_FOLDER}" -maxdepth 1 -name "*.py" -print0 2>/dev/null)

if [ ${#py_root_files[@]} -gt 0 ]; then
    for f in "${py_root_files[@]}"; do
        mv "$f" "${SWITCH_INPUT_DIR}/"
        echo "  Moved: $(basename "$f") -> switch_input/"
    done
    py_count=${#py_root_files[@]}
    if [ "$SKIP_SWITCH" = true ]; then
        echo "  ${py_count} Python file(s) in switch_input/ (Switch disabled)."
    else
        echo "  ${py_count} Python file(s) ready for LLM conversion."
    fi
else
    si_count=$(find "${SWITCH_INPUT_DIR}" -maxdepth 1 -name "*.py" 2>/dev/null | wc -l | tr -d ' ')
    if [ "$si_count" -gt 0 ]; then
        echo "  switch_input/ already contains ${si_count} file(s) — skipping move (rerun)."
    else
        echo "  Warning: no .py files found in output folder or switch_input/."
    fi
fi
echo ""

# =========================================================================
# Step 4: Apply Unity Catalog table namespace mapping to local files
# =========================================================================

if [ -n "$TABLE_MAPPING" ] || [ -n "$UC_CATALOG" ]; then
    echo "Step 4: Applying UC table namespace mapping to switch_input files..."

    tables_mapped=0
    shopt -s nullglob
    switch_py_files=("${SWITCH_INPUT_DIR}"/*.py)
    shopt -u nullglob

    UC_MAPPER_SCRIPT=$(mktemp /tmp/uc_mapper_XXXXXX.py)
    CLEANUP_FILES+=("$UC_MAPPER_SCRIPT")
    cat > "$UC_MAPPER_SCRIPT" << 'PYEOF'
import sys, re

tmp_file = sys.argv[1]
mapping_file = sys.argv[2]
uc_catalog = sys.argv[3] if len(sys.argv) > 3 else ''
uc_schema = sys.argv[4] if len(sys.argv) > 4 else ''

with open(tmp_file, 'r') as f:
    content = f.read()

original = content
table_map = {}

if mapping_file:
    with open(mapping_file, 'r') as mf:
        for line in mf:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(',', 1)
            if len(parts) == 2:
                src = parts[0].strip()
                tgt = parts[1].strip()
                if src and tgt:
                    table_map[src] = tgt

if table_map:
    for src, tgt in sorted(table_map.items(), key=lambda x: -len(x[0])):
        content = re.sub(
            r"(saveAsTable\s*\(\s*['\"])" + re.escape(src) + r"(['\"])",
            r'\1' + tgt + r'\2', content)
        content = re.sub(
            r"(forName\s*\(\s*spark\s*,\s*['\"])" + re.escape(src) + r"(['\"])",
            r'\1' + tgt + r'\2', content)
        for kw in ['FROM', 'JOIN', 'INTO', 'UPDATE']:
            content = re.sub(
                r'(\b' + kw + r'\s+)' + re.escape(src) + r'\b',
                r'\1' + tgt, content, flags=re.IGNORECASE)

elif uc_catalog and uc_schema:
    has_use_catalog = re.search(r'USE\s+CATALOG', content, re.IGNORECASE)
    if not has_use_catalog:
        use_block = (
            '\n# COMMAND ----------\n\n'
            f'spark.sql("USE CATALOG {uc_catalog}")\n'
            f'spark.sql("USE SCHEMA {uc_schema}")\n\n'
        )
        lines = content.split('\n')
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.startswith('import ') or line.startswith('from '):
                insert_idx = i + 1
        lines.insert(insert_idx, use_block)
        content = '\n'.join(lines)

if content != original:
    with open(tmp_file, 'w') as f:
        f.write(content)
    print('modified')
else:
    print('unchanged')
PYEOF

    for pyf in "${switch_py_files[@]}"; do
        modified=$(python3 "$UC_MAPPER_SCRIPT" "$pyf" "${TABLE_MAPPING:-}" "${UC_CATALOG:-}" "${UC_SCHEMA:-}" 2>&1) || modified="error"
        if [ "$modified" = "modified" ]; then
            echo "  Mapped tables in: $(basename "$pyf")"
            tables_mapped=$((tables_mapped + 1))
        elif [ "$modified" = "error" ]; then
            echo "  WARNING: UC mapper failed for: $(basename "$pyf")"
        fi
    done

    if [ "$tables_mapped" -eq 0 ]; then
        echo "  No table references needed mapping."
    else
        echo "  Mapped tables in ${tables_mapped} file(s)."
    fi
else
    echo "Step 4: Skipping UC table namespace mapping (not configured)."
fi
echo ""

# =========================================================================
# Step 5: Reconstruct job orchestration from the DataStage XML
#
# BladeBridge emits a Databricks-jobs JSON whose task list and dependency
# graph mirror the DataStage stage layout — including stages that have no
# Databricks equivalent (sequencers, condition gates, shell-script watermark
# fetches, terminators). This step uses the DataStage XML as the source of
# truth for the dependency graph, produces an equivalent Databricks task
# graph that connects only the stages backed by real notebooks, normalizes
# notebook paths to the flat workspace layout, renames legacy DataStage
# parameter names to the widget names BladeBridge generated, and adds the
# widgets downstream notebooks need at runtime (wkf_ProcessName,
# ctrl_catalog, ctrl_schema).
# =========================================================================

echo "Step 5: Reconstructing job orchestration from DataStage XML..."

shopt -s nullglob
job_json_files_35=("${JOBS_DIR}"/*.json)
shopt -u nullglob

NEW_WS_FOLDER="${OUTPUT_WS_FOLDER}"

for job_json in "${job_json_files_35[@]}"; do
    python3 -c "
import json, sys, os, re
import xml.etree.ElementTree as ET

job_json_path    = sys.argv[1]
new_ws_folder    = sys.argv[2]
switch_input_dir = sys.argv[3]
xml_dir          = sys.argv[4] if len(sys.argv) > 4 else None

with open(job_json_path, 'r') as f:
    job = json.load(f)

tasks = job.get('tasks', [])
if len(tasks) < 2:
    print(f'  Skipped {os.path.basename(job_json_path)} (not a sequence job)')
    sys.exit(0)

job_name = os.path.basename(job_json_path).replace('.json', '')

# Build set of filenames available in switch_input (without .py) for path resolution
switch_files = set()
if os.path.isdir(switch_input_dir):
    for fname in os.listdir(switch_input_dir):
        if fname.endswith('.py'):
            switch_files.add(fname[:-3])

def parse_xml_graph(xml_path):
    STAGE_RECORD_TYPES = {
        'JSJobActivity', 'JSSequencer', 'JSUserVarsActivity',
        'JSExecCmdActivity', 'JSCondition', 'JSTerminatorActivity',
        'JSMailActivity',
    }
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except Exception as e:
        print(f'  WARNING: could not parse XML {xml_path}: {e}')
        return {}, {}
    id_to_name = {}
    id_to_type = {}
    for rec in root.iter('Record'):
        rid = rec.get('Identifier', '')
        rtype = rec.get('Type', '')
        name_prop = rec.find(\"Property[@Name='Name']\")
        type_prop = rec.find(\"Property[@Name='StageType']\")
        if name_prop is not None and rtype in STAGE_RECORD_TYPES:
            id_to_name[rid] = name_prop.text.strip()
            if type_prop is not None:
                id_to_type[rid] = type_prop.text.strip()
    succ = {}
    for rec in root.iter('Record'):
        if rec.get('Type') != 'JSActivityOutput':
            continue
        partner_prop = rec.find(\"Property[@Name='Partner']\")
        if partner_prop is None or not partner_prop.text:
            continue
        src_pin_id = rec.get('Identifier', '')
        src_stage_id = re.sub(r'P\d+\$', '', src_pin_id)
        tgt_stage_id = partner_prop.text.split('|')[0]
        src_name = id_to_name.get(src_stage_id)
        tgt_name = id_to_name.get(tgt_stage_id)
        if src_name and tgt_name and src_name != tgt_name:
            succ.setdefault(src_name, set()).add(tgt_name)
    name_to_type = {id_to_name[i]: id_to_type.get(i, '') for i in id_to_name}
    pred = {name: set() for name in name_to_type}
    for src, targets in succ.items():
        for tgt in targets:
            pred.setdefault(tgt, set()).add(src)
    return name_to_type, pred

def kept_predecessors(stage_name, pred, kept_set):
    result = set()
    frontier = set(pred.get(stage_name, set()))
    visited = set()
    while frontier:
        current = frontier.pop()
        if current in visited:
            continue
        visited.add(current)
        if current in kept_set:
            result.add(current)
        else:
            frontier.update(pred.get(current, set()))
    return result

def has_execcmd_ancestor(stage_name, name_to_type, pred):
    visited = set()
    frontier = set(pred.get(stage_name, set()))
    while frontier:
        cur = frontier.pop()
        if cur in visited:
            continue
        visited.add(cur)
        if name_to_type.get(cur) == 'CExecCommandActivity':
            return True
        frontier.update(pred.get(cur, set()))
    return False

# ---- Parse DataStage XML graph (used for both bypass-type detection and BFS rebuild) ----
xml_path = os.path.join(xml_dir, job_name + '.xml') if xml_dir else None
name_to_type = {}
pred = {}
if xml_path and os.path.isfile(xml_path):
    name_to_type, pred = parse_xml_graph(xml_path)

KEEP_STAGE_TYPES = {'CJobActivity', 'CUserVarsActivity'}
BYPASS_STAGE_TYPES = {
    'CSequencer', 'CExecCommandActivity', 'CCondition',
    'CTerminatorActivity', 'CNotificationActivity', 'CMailActivity',
}

def find_xml_name(tk, name_to_type, job_name):
    for cand in (tk, f'{job_name}_{tk}', re.sub(r'^' + re.escape(job_name) + r'_', '', tk)):
        if cand and cand in name_to_type:
            return cand
    return None

# ---- Identify tasks to remove ----
remove_keys = set()

for t in tasks:
    nb = t.get('notebook_task', {}).get('notebook_path', '')
    tk = t['task_key']

    # Shell command tasks (ExecCmd watermark reads, Exec_Rm dataset cleanup)
    if '/shell/' in nb:
        remove_keys.add(tk)
        continue

    # Sequencer stub notebooks (OR/AND-gate sequencers)
    if '/sequencers/' in nb:
        remove_keys.add(tk)
        continue

    # Terminator notebooks (Ta_Abort)
    if '/terminators/' in nb:
        remove_keys.add(tk)
        continue

    # Specific failure-routing tasks by conventional name
    if tk in ('UsrFailed', 'Exec_Rm'):
        remove_keys.add(tk)
        continue

# XML-type-based removal: catch CCondition / CSequencer / CExecCommandActivity etc.
# even when BladeBridge emitted a generated stub notebook for them (so they would
# pass the path-based check). XML stage type is the source of truth.
if name_to_type:
    for t in tasks:
        tk = t['task_key']
        if tk in remove_keys:
            continue
        xml_name = find_xml_name(tk, name_to_type, job_name)
        if xml_name and name_to_type[xml_name] in BYPASS_STAGE_TYPES:
            remove_keys.add(tk)

# Phantom condition branch sinks: label-only phantom tasks BladeBridge emits for
# condition-gate pin labels. Only remove a task if it has no matching notebook in
# switch_input — real notebooks are preserved and their dependency graph is
# reconstructed from the DataStage XML below.
all_depended_on_pre = {d['task_key'] for t in tasks for d in t.get('depends_on', [])}
for t in tasks:
    tk = t['task_key']
    if tk in remove_keys:
        continue
    deps = t.get('depends_on', [])
    nb_last = t.get('notebook_task', {}).get('notebook_path', '').rsplit('/', 1)[-1]
    has_switch_file = (nb_last in switch_files
                       or f'{job_name}_{tk}' in switch_files
                       or tk in switch_files)
    if (deps
            and all('outcome' in d for d in deps)
            and tk not in all_depended_on_pre
            and 'notebook_task' in t
            and not has_switch_file):
        remove_keys.add(tk)

removed_count = len(remove_keys)

# ---- Remove identified tasks ----
tasks = [t for t in tasks if t['task_key'] not in remove_keys]

# After removing phantom sinks, any condition_task that has no remaining downstream
# task is an orphaned gate. Remove it.
all_depended_on_post = {d['task_key'] for t in tasks for d in t.get('depends_on', [])}
orphan_gates = {t['task_key'] for t in tasks
                if 'condition_task' in t and t['task_key'] not in all_depended_on_post}
tasks = [t for t in tasks if t['task_key'] not in orphan_gates]
removed_count += len(orphan_gates)

# ---- Rebuild depends_on from DataStage XML dependency graph ----
dep_edges_added = 0
if pred:
    name_to_task_key = {}
    for t in tasks:
        if 'notebook_task' not in t:
            continue
        tk = t['task_key']
        name_to_task_key[tk] = tk
        name_to_task_key[f'{job_name}_{tk}'] = tk
        stripped = re.sub(r'^' + re.escape(job_name) + r'_', '', tk)
        if stripped != tk:
            name_to_task_key[stripped] = tk
    kept_set = set(name_to_task_key.keys())
    for t in tasks:
        if 'notebook_task' not in t:
            continue
        tk = t['task_key']
        xml_name = find_xml_name(tk, pred, job_name)
        if xml_name is None:
            continue
        upstream_names = kept_predecessors(xml_name, pred, kept_set)
        upstream_keys = {name_to_task_key[n] for n in upstream_names
                         if n in name_to_task_key and name_to_task_key[n] != tk}
        if upstream_keys:
            t['depends_on'] = [{'task_key': k} for k in sorted(upstream_keys)]
            dep_edges_added += len(upstream_keys)
        elif 'depends_on' in t:
            del t['depends_on']
else:
    valid_keys = {t['task_key'] for t in tasks}
    for t in tasks:
        if 'depends_on' in t:
            t['depends_on'] = [d for d in t['depends_on'] if d.get('task_key') in valid_keys]
            if not t['depends_on']:
                del t['depends_on']

# ---- Fix notebook paths to flat workspace structure ----
# Switch uploads notebooks flat: OUTPUT_WS_FOLDER/<filename> (no subdirectories)
# Try to match each task to the corresponding notebook filename via:
#   1. Exact task_key match in switch_files
#   2. JOB_NAME_task_key match in switch_files
#   3. Last segment of old path (direct) in switch_files
#   4. Last segment stripped of job name prefix in switch_files
# Databricks Jobs notebook_task.notebook_path expects the /Users/... form,
# not /Workspace/Users/... The workspace API resolves both, but the Jobs UI
# and runtime path resolver reject the /Workspace/ prefix as not-found.
new_ws_path_no_slash = new_ws_folder.lstrip('/')
if new_ws_path_no_slash.startswith('Workspace/'):
    new_ws_path_no_slash = new_ws_path_no_slash[len('Workspace/'):]

path_fixes = 0
for t in tasks:
    if 'notebook_task' not in t:
        continue
    old_path = t['notebook_task'].get('notebook_path', '')
    tk = t['task_key']

    candidates = [
        tk,
        f'{job_name}_{tk}',
    ]
    if old_path:
        last_seg = old_path.rsplit('/', 1)[-1]
        candidates.append(last_seg)
        stripped = re.sub(r'^' + re.escape(job_name) + '_', '', last_seg, count=1)
        if stripped != last_seg:
            candidates.append(stripped)

    matched_name = None
    for c in candidates:
        if c in switch_files:
            matched_name = c
            break

    # Fuzzy prefix match: variant tasks (suffix _<SUFFIX>) often share a single
    # notebook generated by BladeBridge for all variants of the same stage.
    if matched_name is None:
        for sf in sorted(switch_files):
            if tk.startswith(sf + '_') or tk == sf:
                matched_name = sf
                break

    if matched_name is None:
        # Use task_key as fallback (correct for fresh bladebridge runs with flat override)
        matched_name = candidates[0]

    new_path = f'/{new_ws_path_no_slash}/{matched_name}'
    if new_path != old_path:
        t['notebook_task']['notebook_path'] = new_path
        path_fixes += 1

# Remove notebook_task entries for which no file exists in switch_input.
# These are typically parallel-job references whose own .dsx was not included
# in the bladebridge input. Substituting a pass-through stub would let the
# task succeed silently and misrepresent audit/error-logging behaviour.
missing_nb_keys = set()
for t in tasks:
    if 'notebook_task' not in t:
        continue
    nb_name = t['notebook_task']['notebook_path'].rsplit('/', 1)[-1]
    if nb_name not in switch_files:
        tk_warn = t['task_key']
        missing_nb_keys.add(tk_warn)
        print(f'  WARNING: no notebook for {tk_warn} ({nb_name}) — removing from workflow')

if missing_nb_keys:
    tasks = [t for t in tasks if t['task_key'] not in missing_nb_keys]
    removed_count += len(missing_nb_keys)
    valid_keys_final = {t['task_key'] for t in tasks}
    for t in tasks:
        if 'depends_on' in t:
            t['depends_on'] = [d for d in t['depends_on'] if d['task_key'] in valid_keys_final]
            if not t['depends_on']:
                del t['depends_on']

# ---- Parameter fixes ----
# 1. Strip DataStage BASIC expressions left in parameter values
for t in tasks:
    bp = t.get('notebook_task', {}).get('base_parameters', {})
    for key in list(bp):
        val = bp[key]
        if isinstance(val, str) and '__DOT__' in val:
            m = re.search(r'\{\{job\.parameters\.(\w+)\}\}', val)
            bp[key] = '{{job.parameters.' + m.group(1) + '}}' if m else ''

# 2. Add wkf_ProcessName to the process-selector UsrVar notebook
for t in tasks:
    if t['task_key'] in ('UsrVar', 'UsrVar_Sel_Process_only'):
        bp = t.setdefault('notebook_task', {}).setdefault('base_parameters', {})
        bp.setdefault('wkf_ProcessName', '{{job.parameters.ProcessName}}')

# Step 5 keeps the parameter list intact. Step 8 reconciles against actual
# notebook widget usage; doing pattern-based dropping here would drop
# parameters the notebooks still need (Unity Catalog schema qualifiers and
# operational widgets without inline defaults).

# 3. Add ctrl_catalog / ctrl_schema to any task whose XML stage has a
#    CExecCommandActivity ancestor — those notebooks need to read the Delta
#    watermark table at runtime.
for t in tasks:
    if 'notebook_task' not in t:
        continue
    tk = t['task_key']
    needs_ctrl = False
    if name_to_type:
        xml_name = find_xml_name(tk, name_to_type, job_name)
        if xml_name and has_execcmd_ancestor(xml_name, name_to_type, pred):
            needs_ctrl = True
    elif tk.startswith('LD_'):
        needs_ctrl = True
    if needs_ctrl:
        bp = t.setdefault('notebook_task', {}).setdefault('base_parameters', {})
        bp.setdefault('ctrl_catalog', '{{job.parameters.ctrl_catalog}}')
        bp.setdefault('ctrl_schema',  '{{job.parameters.ctrl_schema}}')

# 4. Ensure ctrl_catalog / ctrl_schema exist as job-level parameters (consumed
#    by Pattern A). Defaults are left empty; the operator supplies values at
#    job-trigger time.
existing = {p['name'] for p in job.get('parameters', [])}
for pname in ('ctrl_catalog', 'ctrl_schema'):
    if pname not in existing:
        job.setdefault('parameters', []).append({'name': pname, 'default': ''})

job['tasks'] = tasks

with open(job_json_path, 'r+') as f:
    f.seek(0)
    json.dump(job, f, indent=3)
    f.truncate()

print(f'  {os.path.basename(job_json_path)}: removed {removed_count} task(s) '
      f'({len(orphan_gates)} orphan gate(s), {len(missing_nb_keys)} missing notebook(s)), '
      f'{dep_edges_added} dep edge(s) added, '
      f'{path_fixes} path fix(es), '
      f'{len(tasks)} task(s) remaining')
" "$job_json" "$NEW_WS_FOLDER" "$SWITCH_INPUT_DIR" "$JOBS_XML_DIR"
done
echo ""

# =========================================================================
# Step 6: Pre-fix BladeBridge notebooks before the LLM pass
#
# Mechanical edits applied to each BladeBridge Python file before Switch
# picks it up — patterns the LLM either can't reliably translate or
# shouldn't be asked to (deterministic textual substitutions).
#
# Highlights:
#   - Resolve DataStage UsrVar.VarName cross-stage references to
#     dbutils.jobs.taskValues.get() calls using the Databricks task keys
#   - Disambiguate output paths shared between MHP and SHP variants
#   - Replace the DataStage ExecCmd watermark-fetch pattern with a Delta
#     control-table read
#   - Tag Load notebooks that should apply the LLM's Pattern A (Delta
#     watermark read at the top, MERGE write at the bottom) by injecting
#     a trigger comment derived from the DataStage XML
#   - Convert DataStage #VarName# placeholders and the {starttime} runtime
#     token to Python equivalents
#   - Fix unquoted CSV option keys, missing f-prefixes on path strings,
#     and the .ds → .csv extension on staging paths
# =========================================================================

echo "Step 6: Pre-fixing BladeBridge notebooks before the LLM pass..."

shopt -s nullglob
switch_py_all=("${SWITCH_INPUT_DIR}"/*.py)
shopt -u nullglob

fixed_prefixed=0

DS_PREFIXER_SCRIPT=$(mktemp /tmp/ds_prefixer_XXXXXX.py)
CLEANUP_FILES+=("$DS_PREFIXER_SCRIPT")
cat > "$DS_PREFIXER_SCRIPT" << 'PYEOF'
import sys, re, os, json as _json

path = sys.argv[1]
task_key_map  = _json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
watermark_map = _json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}

with open(path, 'r') as f:
    content = f.read()

original = content

notebook_stem = os.path.splitext(os.path.basename(path))[0]

# Watermark context injection: if this notebook was downstream of an ExecCmd→UsrVar chain,
# inject a trigger comment at the top so the LLM embeds Delta watermark read/write (Pattern A).
if notebook_stem in watermark_map:
    pipeline_name = watermark_map[notebook_stem]
    watermark_comment = (
        f"# DataStage: preceded by ExecCmd watermark fetch for pipeline '{pipeline_name}'."
        f" Embed watermark read at start and write at end.\n"
    )
    lines = content.split('\n')
    if lines and lines[0].startswith('# Databricks notebook source'):
        content = lines[0] + '\n' + watermark_comment + '\n'.join(lines[1:])
    else:
        content = watermark_comment + content

# Fix 5: Condition notebooks — resolve UsrVar.VarName / UsrVar_Suffix.VarName
# to dbutils.jobs.taskValues.get(taskKey=ACTUAL_KEY, key=VarName, minWaitMs=0)
# using the task key map from the Databricks job JSON (passed as sys.argv[2]).
def _resolve_usrvar(m):
    suffix = m.group(1)   # e.g. '' or 'Sel_Process_only'
    varname = m.group(2)  # e.g. 'ProcessNm', 'To_SHI'
    op = m.group(3)       # e.g. '= 0', "='Y'"
    fixed_op = re.sub(r'^=\s*', '== ', op.strip())

    lookup = 'UsrVar' + ('_' + suffix if suffix else '')
    actual_key = next((k for k in task_key_map if k == lookup), None)
    if actual_key is None:
        actual_key = lookup
        warning = f'    # WARNING: task "{lookup}" not found in job JSON; verify task_key\n'
    else:
        warning = ''

    varname_lower = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', varname).lower()
    return (
        f'{warning}'
        f'    {varname_lower} = dbutils.jobs.taskValues.get('
        f"taskKey='{actual_key}', key='{varname}', minWaitMs=0)\n"
        f'    if {varname_lower} {fixed_op}:'
    )

if re.search(r'if\s+UsrVar(?:_\w+)?\.\w+\s*=', content):
    content = re.sub(
        r'if\s+UsrVar(?:_(\w+))?\.(\w+)\s*(=+\s*\S+)\s*:',
        _resolve_usrvar,
        content
    )

# Fix 6: when two BladeBridge notebooks write to the same staged path,
# disambiguate by injecting a variant suffix derived from the filename so the
# paths don't collide.
fname_stem = os.path.basename(path)
m = re.search(r'_([A-Z]{2,5})\.py$', fname_stem)
if m:
    variant = m.group(1)
    content = re.sub(
        r"\{OraSchema\}\.ds",
        f"{variant}_{{OraSchema}}.ds",
        content
    )

# Fix 7: UsrVar notebooks with ExecCmd CommandOutput SQL.
# DataStage UsrVar stages parse ExecCmd stdout (pipe-delimited watermark file)
# into per-pipeline variables (begin timestamp, process name, etc.). In
# Databricks there is no ExecCmd; replace each variable with its Databricks
# equivalent:
#   - watermark timestamp     → Delta control-table read (Pattern A)
#   - process name / config   → widget read
# The notebook's own taskValues.set calls tell us exactly which keys to produce.
execmd_refs = re.findall(r'ExecCmd_[\w]+\.CommandOutput', content)
if execmd_refs:
    task_name = execmd_refs[0].split('.')[0]
    pipeline_name = task_name.rstrip('_').rsplit('_', 1)[-1].upper()
    set_keys = re.findall(r"dbutils\.jobs\.taskValues\.set\(key\s*=\s*['\"](\w+)['\"]", content)

    wm_written = False
    cells = []
    for key in set_keys:
        if key.lower() in ('begintranstst', 'transactiondate', 'begintransactiondate',
                           'begintransactiontst', 'begin_trans_tst'):
            if not wm_written:
                cells.append(
                    "ctrl_catalog  = dbutils.widgets.get(\"ctrl_catalog\")\n"
                    "ctrl_schema   = dbutils.widgets.get(\"ctrl_schema\")\n"
                    f"pipeline_name = '{pipeline_name}'\n"
                    "_wm = spark.sql(\n"
                    "    f\"SELECT COALESCE(last_processed_ts, TIMESTAMP '1900-01-01') AS begin_trans_tst\"\n"
                    "    f\" FROM {ctrl_catalog}.{ctrl_schema}.pipeline_watermarks\"\n"
                    "    f\" WHERE pipeline_name = '{pipeline_name}'\"\n"
                    ").collect()\n"
                    "begin_trans_tst = str(_wm[0]['begin_trans_tst']) if _wm else '1900-01-01 00:00:00'\n"
                    f"dbutils.jobs.taskValues.set(key='{key}', value=begin_trans_tst)\n"
                )
                wm_written = True
        else:
            cells.append(
                f"{key} = dbutils.widgets.get(\"{key}\")\n"
                f"dbutils.jobs.taskValues.set(key='{key}', value={key})\n"
            )

    if not cells:
        cells.append("pass  # TODO: no taskValues keys detected — review original DataStage UsrVar stage\n")

    content = (
        "# Databricks notebook source\n"
        "# DataStage ExecCmd watermark fetch replaced with Delta control table read.\n\n"
        + "".join("# COMMAND ----------\n\n" + cell + "\n" for cell in cells)
    )

# Fix 8: Replace DataStage {starttime} headless-SQL pattern with current_timestamp().
# {starttime} is a DataStage internal runtime variable; not a Python variable.
content = re.sub(
    r"df\s*=\s*spark\.sql\([\"']SELECT '\{starttime\}'[\"']\)\s*;?\s*\n"
    r"\s*data\s*=\s*df\.collect\(\)\s*\n"
    r"\s*val\s*=\s*data\[0\]\[0\]",
    'val = str(spark.sql("SELECT current_timestamp()").collect()[0][0])',
    content
)
content = re.sub(
    r"spark\.sql\([\"']SELECT '\{starttime\}'[\"']\)",
    'spark.sql("SELECT current_timestamp()")',
    content
)

# Fix 9: Fix .ds staging CSV paths:
#   1. Fix unquoted sep key in .option(sep,...)
#   2. Rename .ds extension to .csv in all path strings
#   3. Add f-prefix to write/read paths that contain brace variables but lack f-prefix
content = re.sub(r"\.option\(sep,", ".option('sep',", content)
content = re.sub(r"\.ds(['\"])", r".csv\1", content)
content = re.sub(
    r"\.csv\('(\{[A-Za-z]\w*\}[^']*\.csv)'\)",
    lambda m: f".csv(f'{m.group(1)}')",
    content
)
content = re.sub(
    r"spark\.read\.csv\('(\{[A-Za-z]\w*\}[^']*)'",
    lambda m: f"spark.read.csv(f'{m.group(1)}'",
    content
)

# Fix 10: Convert DataStage #VarName# parameter placeholders to Python f-string {VarName}.
# Uppercase-leading identifier = DataStage parameter convention.
# Only converts reference syntax; widget reads are already emitted by BladeBridge.
content = re.sub(r'#([A-Z][A-Za-z0-9_]*)#', r'{\1}', content)
# Ensure spark.sql() strings that now contain {VarName} have the f-prefix.
def _ensure_f_prefix(m):
    s = m.group(0)
    if re.search(r'\{[A-Za-z]\w*\}', s) and not re.match(r'spark\.sql\(f', s):
        s = s.replace('spark.sql(', 'spark.sql(f', 1)
    return s
content = re.sub(
    r'spark\.sql\((?:f?)(?:"""|\'\'\').*?(?:"""|\'\'\')(?=\s*\))',
    _ensure_f_prefix, content, flags=re.DOTALL
)

if content != original:
    with open(path, 'w') as f:
        f.write(content)
    print('modified')
else:
    print('unchanged')
PYEOF

# Build task_key_map JSON from all job JSONs in JOBS_DIR
TASK_KEY_MAP=$(JOBS_DIR="${JOBS_DIR}" python3 - <<'EOF'
import json, glob, os
m = {}
for jf in glob.glob(os.environ['JOBS_DIR'] + '/*.json'):
    try:
        d = json.load(open(jf))
        for t in d.get('tasks', []):
            stem = t.get('notebook_task', {}).get('notebook_path', '').split('/')[-1]
            if stem:
                m[t['task_key']] = stem
    except Exception:
        pass
print(json.dumps(m))
EOF
)

# Build watermark_map: notebook_stem → pipeline_name for notebooks that should apply
# Pattern A (Delta watermark read/write). Detection is XML-based: a stage qualifies
# when it has a CExecCommandActivity ancestor in the DataStage graph. The pipeline
# name is the trailing uppercase suffix on the stage name. Falls back to no watermark
# injection when XML is unavailable.
WATERMARK_MAP=$(JOBS_DIR="${JOBS_DIR}" JOBS_XML_DIR="${JOBS_XML_DIR}" python3 - <<'EOF'
import json, glob, os, re
import xml.etree.ElementTree as ET

jobs_dir = os.environ['JOBS_DIR']
xml_dir  = os.environ.get('JOBS_XML_DIR', '')

STAGE_RECORD_TYPES = {
    'JSJobActivity', 'JSSequencer', 'JSUserVarsActivity',
    'JSExecCmdActivity', 'JSCondition', 'JSTerminatorActivity', 'JSMailActivity',
}
PIPELINE_NAME_RE = re.compile(r'_([A-Z]{2,5})$')

def parse_xml_graph(xml_path):
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except Exception:
        return {}, {}
    id_to_name, id_to_type = {}, {}
    for rec in root.iter('Record'):
        rid = rec.get('Identifier', '')
        rtype = rec.get('Type', '')
        name_prop = rec.find("Property[@Name='Name']")
        type_prop = rec.find("Property[@Name='StageType']")
        if name_prop is not None and rtype in STAGE_RECORD_TYPES:
            id_to_name[rid] = name_prop.text.strip()
            if type_prop is not None:
                id_to_type[rid] = type_prop.text.strip()
    succ = {}
    for rec in root.iter('Record'):
        if rec.get('Type') != 'JSActivityOutput':
            continue
        partner_prop = rec.find("Property[@Name='Partner']")
        if partner_prop is None or not partner_prop.text:
            continue
        src_pin_id = rec.get('Identifier', '')
        src_stage_id = re.sub(r'P\d+$', '', src_pin_id)
        tgt_stage_id = partner_prop.text.split('|')[0]
        sn = id_to_name.get(src_stage_id)
        tn = id_to_name.get(tgt_stage_id)
        if sn and tn and sn != tn:
            succ.setdefault(sn, set()).add(tn)
    name_to_type = {id_to_name[i]: id_to_type.get(i, '') for i in id_to_name}
    pred = {n: set() for n in name_to_type}
    for sn, ts in succ.items():
        for tn in ts:
            pred.setdefault(tn, set()).add(sn)
    return name_to_type, pred

def has_execcmd_ancestor(stage_name, name_to_type, pred):
    visited = set()
    frontier = set(pred.get(stage_name, set()))
    while frontier:
        cur = frontier.pop()
        if cur in visited:
            continue
        visited.add(cur)
        if name_to_type.get(cur) == 'CExecCommandActivity':
            return True
        frontier.update(pred.get(cur, set()))
    return False

def find_xml_name(tk, name_to_type, job_name):
    for cand in (tk, f'{job_name}_{tk}', re.sub(r'^' + re.escape(job_name) + r'_', '', tk)):
        if cand and cand in name_to_type:
            return cand
    return None

wmap = {}
for jf in glob.glob(f'{jobs_dir}/*.json'):
    try:
        d = json.load(open(jf))
        tasks = d.get('tasks', [])
        job_name = os.path.basename(jf).replace('.json', '')
        xml_path = os.path.join(xml_dir, job_name + '.xml') if xml_dir else ''
        name_to_type, pred = parse_xml_graph(xml_path) if xml_path and os.path.isfile(xml_path) else ({}, {})
        if not pred:
            continue
        for t in tasks:
            tk = t['task_key']
            stem = t.get('notebook_task', {}).get('notebook_path', '').split('/')[-1]
            if not stem:
                continue
            xml_name = find_xml_name(tk, name_to_type, job_name)
            if not xml_name or not has_execcmd_ancestor(xml_name, name_to_type, pred):
                continue
            m = PIPELINE_NAME_RE.search(tk) or PIPELINE_NAME_RE.search(xml_name)
            wmap[stem] = m.group(1) if m else 'DEFAULT'
    except Exception:
        pass
print(json.dumps(wmap))
EOF
)

for pyf in "${switch_py_all[@]}"; do
    fname=$(basename "$pyf")
    result=$(python3 "$DS_PREFIXER_SCRIPT" "$pyf" "$TASK_KEY_MAP" "$WATERMARK_MAP" 2>&1) || result="error"
    if [ "$result" = "modified" ]; then
        fixed_prefixed=$((fixed_prefixed + 1))
        echo "  Pre-fixed: ${fname}"
    elif [ "$result" = "error" ]; then
        echo "  WARNING: pre-fix failed for: ${fname}"
    fi
done

echo "  Notebooks pre-fixed: ${fixed_prefixed}"
echo ""

# =========================================================================
# Step 7: Drop redundant watermark-writer tasks
#
# In DataStage, EXT_TransactionDt_Fetch_* stages run after each Load to
# record the new high-water mark. In Databricks the equivalent MERGE
# happens inside the Load notebook itself (Pattern A applied in Step 3.6
# and Switch), so these tasks no longer carry any work.
# =========================================================================

echo "Step 7: Dropping redundant watermark-writer tasks..."

JOBS_DIR="${JOBS_DIR}" python3 - <<'EOF'
import json, glob, os

jobs_dir = os.environ['JOBS_DIR']

for jf in glob.glob(f'{jobs_dir}/*.json'):
    d = json.load(open(jf))
    tasks = d.get('tasks', [])
    by_key = {t['task_key']: t for t in tasks}

    ext_fetch_keys = set()
    for t in tasks:
        lk = t['task_key'].lower()
        if lk.startswith('ext') and ('transactiondt' in lk or 'fetch' in lk):
            ext_fetch_keys.add(t['task_key'])

    if not ext_fetch_keys:
        continue

    # For each removed EXT_Fetch, its dependents will be rewired to the EXT_Fetch's
    # own predecessors (so the chain through it is preserved).
    rewire = {tk: [dep['task_key'] for dep in by_key[tk].get('depends_on', [])
                   if dep['task_key'] not in ext_fetch_keys and dep['task_key'] in by_key]
              for tk in ext_fetch_keys}

    new_tasks = []
    for t in tasks:
        if t['task_key'] in ext_fetch_keys:
            continue
        new_deps = []
        seen = set()
        for dep in t.get('depends_on', []):
            dk = dep['task_key']
            if dk not in ext_fetch_keys:
                if dk not in seen:
                    new_deps.append(dep)
                    seen.add(dk)
            else:
                for rk in rewire.get(dk, []):
                    if rk not in seen:
                        new_deps.append({'task_key': rk})
                        seen.add(rk)
        if new_deps:
            t['depends_on'] = new_deps
        elif 'depends_on' in t:
            del t['depends_on']
        new_tasks.append(t)

    d['tasks'] = new_tasks
    with open(jf, 'w') as f:
        json.dump(d, f, indent=2)

    print(f'  {os.path.basename(jf)}: removed {len(ext_fetch_keys)} EXT_Fetch task(s), '
          f'{len(new_tasks)} task(s) remaining')
EOF

echo ""

# =========================================================================
# Step 8: Reconcile job parameters with notebook widget usage
#
# Reads each pre-Switch notebook in SWITCH_INPUT_DIR (BladeBridge output
# after Step 6 prefixer fixes), determines which widgets each notebook
# actually declares or fetches, then drops parameters the notebooks do not
# need:
#   - task base_parameters whose key is not needed by the notebook,
#   - job-level parameters that no remaining base_parameter references.
# Mirrors the LLM's Rule 12 by also dropping credential widgets (names
# ending in DSN/UserId/UserNm/User/Pwd/Password) up front, since Switch
# will strip those declarations during the LLM pass.
# =========================================================================

echo "Step 8: Reconciling job parameters with notebook widget usage..."

JOBS_DIR="${JOBS_DIR}" SWITCH_INPUT_DIR="${SWITCH_INPUT_DIR}" python3 - <<'EOF'
import json, glob, os, re

jobs_dir = os.environ['JOBS_DIR']
nb_dir   = os.environ['SWITCH_INPUT_DIR']

# A notebook "needs" a widget if it either declares it (positional or keyword
# form) or fetches it via dbutils.widgets.get(). Either form means the job
# has to supply that parameter.
DECL_RE = re.compile(
    r'dbutils\.widgets\.(?:text|dropdown|combobox|multiselect)\s*\(\s*'
    r'(?:name\s*=\s*)?[\'"](\w+)[\'"]'
)
GET_RE = re.compile(r'dbutils\.widgets\.get\s*\(\s*[\'"](\w+)[\'"]')
# Mirror prompt Rule 12: credential widgets the LLM removes during Switch.
CREDENTIAL_SUFFIX_RE = re.compile(r'(DSN|UserId|UserNm|User|Pwd|Password)$', re.IGNORECASE)
# Widgets the LLM injects during Switch (prompt Rule 13 / Pattern A) — they
# aren't yet declared in the pre-Switch source but will be needed at runtime.
LLM_INJECTED = {'ctrl_catalog', 'ctrl_schema'}

def widgets_needed(src):
    names = set(DECL_RE.findall(src)) | set(GET_RE.findall(src)) | LLM_INJECTED
    return {w for w in names if not CREDENTIAL_SUFFIX_RE.search(w)}

per_nb = {}
if os.path.isdir(nb_dir):
    for nb in glob.glob(os.path.join(nb_dir, '*.py')):
        stem = os.path.basename(nb)[:-3]
        with open(nb) as f:
            per_nb[stem] = widgets_needed(f.read())

if not per_nb:
    print('  No notebooks found in ' + nb_dir + ' — skipping.')
    raise SystemExit(0)

JOB_PARAM_REF = re.compile(r'\{\{job\.parameters\.(\w+)\}\}')

total_bp_dropped = 0
total_jp_dropped = 0
for jf in glob.glob(os.path.join(jobs_dir, '*.json')):
    with open(jf) as f:
        d = json.load(f)
    tasks = d.get('tasks', [])

    # 1. Drop task base_parameters whose key is not needed by the notebook.
    bp_dropped = 0
    for t in tasks:
        nt = t.get('notebook_task')
        if not nt:
            continue
        stem = nt.get('notebook_path', '').rsplit('/', 1)[-1]
        if stem not in per_nb:
            continue
        needed = per_nb[stem]
        bp = nt.get('base_parameters', {})
        for key in list(bp):
            if key not in needed:
                del bp[key]
                bp_dropped += 1

    # 2. Drop job-level parameters that no remaining base_parameter references.
    refs = set()
    for t in tasks:
        for v in t.get('notebook_task', {}).get('base_parameters', {}).values():
            if isinstance(v, str):
                refs.update(JOB_PARAM_REF.findall(v))
    before = len(d.get('parameters', []))
    d['parameters'] = [p for p in d.get('parameters', []) if p['name'] in refs]
    jp_dropped = before - len(d['parameters'])

    with open(jf, 'w') as f:
        json.dump(d, f, indent=3)
    total_bp_dropped += bp_dropped
    total_jp_dropped += jp_dropped
    print(f'  {os.path.basename(jf)}: dropped {bp_dropped} base_parameter(s), '
          f'{jp_dropped} job-level parameter(s)')

print(f'  Total: {total_bp_dropped} base_parameter(s), {total_jp_dropped} job-level parameter(s)')
EOF

echo ""

# =========================================================================
# Step 9: Place custom prompt at the path Switch reads from and update
#         switch_config.yml. On a cluster web terminal both paths are workspace
#         filesystem paths, so the import is a workspace-to-workspace copy.
#         On a local run it pushes the file from local disk to the workspace.
# =========================================================================

if [ "$SKIP_SWITCH" = true ]; then
    echo "Step 9: Skipping prompt placement (Switch not running)."
    echo ""
    echo "Step 10: Skipping Switch LLM conversion."
    echo ""
else
echo "Step 9: Placing custom prompt and updating Switch configuration..."

if [ ! -f "$CUSTOM_PROMPT" ]; then
    echo "Error: custom prompt file '${CUSTOM_PROMPT}' not found."
    exit 1
fi
PROMPT_FILENAME="$(basename "$CUSTOM_PROMPT")"
WS_PROMPT_DIR="/Workspace/Users/${USER_EMAIL}/Prompts"
WS_PROMPT_PATH="${WS_PROMPT_DIR}/${PROMPT_FILENAME}"

# Ensure workspace output folder exists (Switch writes notebooks here)
echo "  Ensuring workspace output folder: ${OUTPUT_WS_FOLDER}"
databricks workspace mkdirs "${OUTPUT_WS_FOLDER}" $PROFILE_FLAG 2>/dev/null || true

# Ensure Switch UC catalog / schema / volume exist
echo "  Ensuring Switch UC resources: /Volumes/${CATALOG}/${SCHEMA}/${VOLUME}/"

if databricks catalogs get "${CATALOG}" $PROFILE_FLAG &>/dev/null; then
    echo "  Catalog exists:  ${CATALOG}"
else
    if databricks catalogs create --name "${CATALOG}" $PROFILE_FLAG 2>/dev/null; then
        echo "  Created catalog: ${CATALOG}"
    else
        echo "  WARNING: Could not create catalog '${CATALOG}' (may need metastore admin — create it manually)."
    fi
fi

if databricks schemas get "${CATALOG}.${SCHEMA}" $PROFILE_FLAG &>/dev/null; then
    echo "  Schema exists:   ${CATALOG}.${SCHEMA}"
else
    if databricks schemas create --catalog-name "${CATALOG}" --name "${SCHEMA}" $PROFILE_FLAG 2>/dev/null; then
        echo "  Created schema:  ${CATALOG}.${SCHEMA}"
    else
        echo "  WARNING: Could not create schema '${CATALOG}.${SCHEMA}'."
    fi
fi

if databricks volumes read "${CATALOG}.${SCHEMA}.${VOLUME}" $PROFILE_FLAG &>/dev/null; then
    echo "  Volume exists:   /Volumes/${CATALOG}/${SCHEMA}/${VOLUME}/"
else
    vol_create_out=$(databricks volumes create \
        --json "{\"catalog_name\": \"${CATALOG}\", \"schema_name\": \"${SCHEMA}\", \"name\": \"${VOLUME}\", \"volume_type\": \"MANAGED\"}" \
        $PROFILE_FLAG 2>&1)
    if echo "$vol_create_out" | grep -q '"volume_type"'; then
        echo "  Created volume:  /Volumes/${CATALOG}/${SCHEMA}/${VOLUME}/"
    else
        echo "  ERROR: Could not create Switch volume. Details:"
        echo "    ${vol_create_out}"
        echo "  Create it manually then re-run:"
        echo "    databricks volumes create --json '{\"catalog_name\":\"${CATALOG}\",\"schema_name\":\"${SCHEMA}\",\"name\":\"${VOLUME}\",\"volume_type\":\"MANAGED\"}' $PROFILE_FLAG"
        exit 1
    fi
fi
echo ""

if ! databricks workspace mkdirs "${WS_PROMPT_DIR}" $PROFILE_FLAG 2>&1; then
    echo "  WARNING: Failed to create workspace directory ${WS_PROMPT_DIR}. Continuing..."
fi
databricks workspace import "${WS_PROMPT_PATH}" \
    --file "$CUSTOM_PROMPT" \
    --format AUTO \
    --overwrite \
    $PROFILE_FLAG
echo "  Prompt placed at: ${WS_PROMPT_PATH}"

SWITCH_CONFIG_WS_PATH="/Users/${USER_EMAIL}/.lakebridge/switch/resources/switch_config.yml"
SWITCH_CONFIG_LOCAL="${OUTPUT_FOLDER}/switch_config.yml"
cat > "$SWITCH_CONFIG_LOCAL" <<SWITCHEOF
# Switch configuration file
# Auto-generated by datastage_pipeline run.sh

target_type: "notebook"
source_format: "generic"
comment_lang: "English"
log_level: "INFO"
token_count_threshold: 20000
concurrency: 4
max_fix_attempts: 1

conversion_prompt_yaml: ${WS_PROMPT_PATH}

output_extension:
sql_output_dir:
request_params: '{"max_tokens": 8192}'
sdp_language: "python"
SWITCHEOF

databricks workspace import "${SWITCH_CONFIG_WS_PATH}" \
    --file "$SWITCH_CONFIG_LOCAL" \
    --format AUTO \
    --overwrite \
    $PROFILE_FLAG
echo "  Updated switch_config.yml at: ${SWITCH_CONFIG_WS_PATH}"
echo ""

# =========================================================================
# Step 10: Run Switch LLM conversion
# =========================================================================

echo "Step 10: Running Switch LLM transpiler (this may take a while)..."
echo ""

databricks labs lakebridge llm-transpile \
    --accept-terms true \
    --input-source "${SWITCH_INPUT_DIR}" \
    --output-ws-folder "${OUTPUT_WS_FOLDER}" \
    --source-dialect unknown_etl \
    --catalog-name "${CATALOG}" \
    --schema-name "${SCHEMA}" \
    --volume "${VOLUME}" \
    --foundation-model "${FOUNDATION_MODEL}" \
    $PROFILE_FLAG

echo ""
echo "  Switch has launched a Databricks job that converts the notebooks asynchronously."
echo "  The CLI returns immediately; the actual conversion is still running."
echo "  Notebooks will appear in: ${OUTPUT_WS_FOLDER}"
echo ""

fi  # end SKIP_SWITCH guard (Steps 9 and 10)


# =========================================================================
# Step 11: Place supplemental module at the workspace path notebooks import
#          from. On a cluster web terminal both paths are workspace filesystem
#          paths (workspace-to-workspace copy); on a local run it pushes the
#          file from local disk to the workspace.
# =========================================================================

SUPPLEMENTS_FILE="${SUPPLEMENTS_DIR}/databricks_conversion_supplements.py"
if [ -f "$SUPPLEMENTS_FILE" ]; then
    echo "Step 11: Placing databricks_conversion_supplements.py at workspace path..."
    databricks workspace mkdirs "${OUTPUT_WS_FOLDER}" $PROFILE_FLAG 2>/dev/null || true
    databricks workspace import "${OUTPUT_WS_FOLDER}/databricks_conversion_supplements.py" \
        --file "$SUPPLEMENTS_FILE" \
        --format AUTO \
        --overwrite \
        $PROFILE_FLAG
    echo "  Module placed at: ${OUTPUT_WS_FOLDER}/databricks_conversion_supplements.py"
    echo ""
else
    echo "Step 11: No supplemental module to place."
    echo ""
fi

# =========================================================================
# Step 12: Create Databricks jobs
# =========================================================================

shopt -s nullglob
job_json_files=("${JOBS_DIR}"/*.json)
shopt -u nullglob

if [ ${#job_json_files[@]} -gt 0 ]; then
    echo "Step 12: Creating Databricks jobs..."
    echo ""
    if [ "$SKIP_SWITCH" = true ]; then
        echo "  Note: Switch was skipped — job JSON notebook paths must exist in the workspace (or edit JSON before create)."
        echo ""
    fi

    if [ "$COMPUTE_TYPE" = "serverless" ]; then
        echo "  Converting job definitions to serverless compute..."
        for f in "${job_json_files[@]}"; do
            python3 -c "
import json, sys
with open(sys.argv[1], 'r+') as f:
    job = json.load(f)
    job.pop('job_clusters', None)
    for task in job.get('tasks', []):
        task.pop('job_cluster_key', None)
    f.seek(0); json.dump(job, f, indent=3); f.truncate()
" "$f"
        done
        echo ""
    fi

    WS_HOST=""
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

    success=0
    failed=0
    for f in "${job_json_files[@]}"; do
        job_name=$(basename "$f" .json)

        echo "  Creating job: ${job_name}..."
        if output=$(databricks jobs create --json @"$f" $PROFILE_FLAG -o json 2>&1); then
            job_id=$(echo "$output" | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")
            if [ -n "$WS_HOST" ]; then
                echo "    Created: ${WS_HOST}/jobs/${job_id}"
            else
                echo "    Created job_id: ${job_id}"
            fi
            success=$((success + 1))
        else
            echo "    ERROR: ${output}"
            failed=$((failed + 1))
        fi
    done

    echo ""
    echo "  Jobs: ${success} created, ${failed} failed."
else
    echo "Step 12: No JSON job files to create."
fi

echo ""
echo "============================================"
echo "  Pipeline Complete"
echo "============================================"
echo "  Notebooks:     ${OUTPUT_WS_FOLDER}"
echo "  BladeBridge:   ${OUTPUT_FOLDER}"
echo "  First pass:    ${FIRST_PASS_DIR}"
echo "  Job JSONs:     ${JOBS_DIR}"
echo "  Supplements:   ${SUPPLEMENTS_DIR}"
echo "============================================"
