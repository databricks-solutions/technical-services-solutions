#!/bin/bash
# End-to-end automation for Informatica-to-Databricks migration using Lakebridge.
#
# Prerequisite: Lakebridge must be installed (`databricks labs install lakebridge`)
#
# This script handles everything else:
#   1. Installs BladeBridge transpiler and Switch LLM transpiler
#   2. Runs BladeBridge to produce initial PySpark conversion
#   3. Separates JSON job definitions and supplemental files
#   4. Uploads custom prompt and updates switch_config.yml on workspace
#   5. Runs Switch LLM transpiler to convert .py files to notebooks
#   6. Uploads the supplemental Python module to the workspace
#   7. Creates Databricks jobs from the JSON definitions
#
# Default override JSON and prompt YAML are located alongside this script.
# Pass -r or -x to use files from other locations.
#
# Usage:
#   ./run.sh [options]
#
# Options:
#   -i, --input-source       Local path to Informatica source files (XML exports)
#   -o, --output-folder      Local path for BladeBridge output
#   -w, --output-ws-folder   Workspace folder for notebooks (must start with /Workspace/)
#   -e, --user-email         User email override (default: auto-detected from Databricks profile)
#   -p, --profile            Databricks CLI profile (default: DEFAULT)
#   -c, --catalog            Databricks catalog name (default: lakebridge)
#   -s, --schema             Databricks schema name (default: switch)
#   -v, --volume             UC Volume name (default: switch_volume)
#   -m, --foundation-model   Foundation model endpoint (default: databricks-claude-sonnet-4-5)
#   -t, --target-tech        BladeBridge target technology: PYSPARK or SPARKSQL (default: PYSPARK)
#   -r, --overrides-file     Override JSON for BladeBridge (default: sample_override.json in script dir)
#   -x, --custom-prompt      Custom Switch prompt YAML (default: informatica_to_databricks_prompt.yml in script dir)
#       --compute            Job compute type: serverless or classic (default: serverless)
#       --cloud              Cloud provider: azure, aws, or gcp (only used with classic compute)
#       --table-mapping      CSV file mapping source tables to UC 3-level names
#       --skip-det-install   Skip BladeBridge installation only (still run conversion)
#       --skip-llm-install   Skip Switch LLM installation only (still run conversion)
#       --skip-bladebridge   Skip BladeBridge entirely (install + conversion; use existing output)
#       --skip-switch        Skip Switch LLM entirely (install + conversion)
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
CUSTOM_PROMPT=""
CLOUD=""
COMPUTE_TYPE=""
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
        -x|--custom-prompt)      CUSTOM_PROMPT="$2"; shift 2 ;;
        --cloud)                 CLOUD="$2"; shift 2 ;;
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
    CUSTOM_PROMPT="${SCRIPT_DIR}/informatica_to_databricks_prompt.yml"
fi
if [ ! -f "$CUSTOM_PROMPT" ]; then
    echo "Error: custom prompt file '${CUSTOM_PROMPT}' not found."
    exit 1
fi

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

# --- BladeBridge (deterministic transpiler) ---
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

# --- Switch (LLM transpiler) ---
if [ "$SKIP_SWITCH" = false ]; then
    read -rp "Run Switch LLM cleanup? (Y/n): " run_switch_answer
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

if [ "$SKIP_BLADEBRIDGE" = false ]; then
    if [ -z "$INPUT_SOURCE" ]; then
        read -rp "Local path to Informatica source files: " INPUT_SOURCE
    fi
    if [ ! -e "$INPUT_SOURCE" ]; then
        echo "Error: input source '${INPUT_SOURCE}' does not exist."
        exit 1
    fi
fi

if [ -z "$OUTPUT_FOLDER" ]; then
    read -rp "Local output folder for BladeBridge results: " OUTPUT_FOLDER
fi
if [ -z "$OUTPUT_FOLDER" ]; then
    echo "Error: output folder is required."
    exit 1
fi

if [ -z "$OUTPUT_WS_FOLDER" ]; then
    read -rp "Workspace output folder (must start with /Workspace/): " OUTPUT_WS_FOLDER
fi
if [[ ! "$OUTPUT_WS_FOLDER" == /Workspace/* ]]; then
    echo "Error: workspace output folder must start with /Workspace/"
    exit 1
fi

if [ -z "$TARGET_TECH" ]; then
    read -rp "BladeBridge target technology (PYSPARK or SPARKSQL) [default: PYSPARK]: " TARGET_TECH
    TARGET_TECH="${TARGET_TECH:-PYSPARK}"
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

if [ -z "$COMPUTE_TYPE" ]; then
    read -rp "Job compute type (serverless or classic) [default: serverless]: " COMPUTE_TYPE
    COMPUTE_TYPE="${COMPUTE_TYPE:-serverless}"
fi
COMPUTE_TYPE=$(echo "$COMPUTE_TYPE" | tr '[:upper:]' '[:lower:]')
if [ "$COMPUTE_TYPE" != "serverless" ] && [ "$COMPUTE_TYPE" != "classic" ]; then
    echo "Error: compute type must be serverless or classic."
    exit 1
fi

if [ "$COMPUTE_TYPE" = "classic" ]; then
    if [ -z "$CLOUD" ]; then
        read -rp "Cloud provider (azure, aws, gcp) [default: azure]: " CLOUD
        CLOUD="${CLOUD:-azure}"
    fi
    CLOUD=$(echo "$CLOUD" | tr '[:upper:]' '[:lower:]')
    case "$CLOUD" in
        azure) NODE_TYPE="Standard_D4ds_v5" ;;
        aws)   NODE_TYPE="i3.xlarge" ;;
        gcp)   NODE_TYPE="n1-standard-4" ;;
        *)     echo "Error: cloud must be azure, aws, or gcp."; exit 1 ;;
    esac
fi

# --- Table mapping for Unity Catalog 3-level namespace ---

if [ -z "$TABLE_MAPPING" ]; then
    # Check for a mapping file in the script directory
    default_mapping="${SCRIPT_DIR}/table_mapping.csv"
    if [ -f "$default_mapping" ]; then
        # Check if mapping file has actual entries (non-comment, non-empty lines)
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
echo "  Informatica-to-Databricks Migration"
echo "============================================"
echo "  Profile:            ${PROFILE}"
echo "  User email:         ${USER_EMAIL}"
[ "$SKIP_BLADEBRIDGE" = false ] && echo "  Input source:       ${INPUT_SOURCE}"
echo "  Output folder:      ${OUTPUT_FOLDER}"
echo "  Workspace folder:   ${OUTPUT_WS_FOLDER}"
echo "  Target technology:  ${TARGET_TECH}"
echo "  Override file:      ${OVERRIDES_FILE}"
echo "  Custom prompt:      ${CUSTOM_PROMPT}"
echo "  Catalog:            ${CATALOG}"
echo "  Schema:             ${SCHEMA}"
echo "  Volume:             ${VOLUME}"
echo "  Foundation model:   ${FOUNDATION_MODEL}"
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
    databricks labs lakebridge install-transpile --interactive false $PROFILE_FLAG
    echo ""
else
    echo "Step 1a: Skipping BladeBridge install."
fi

if [ "$SKIP_LLM_INSTALL" = false ]; then
    echo "Step 1b: Installing LLM transpiler (Switch)..."
    databricks labs lakebridge install-transpile --include-llm-transpiler true --interactive false $PROFILE_FLAG
    echo ""
else
    echo "Step 1b: Skipping Switch LLM install."
fi
echo ""

# =========================================================================
# Step 2: Run BladeBridge transpilation
# =========================================================================

if [ "$SKIP_BLADEBRIDGE" = false ]; then
    echo "Step 2: Running BladeBridge transpilation..."
    echo ""

    mkdir -p "${OUTPUT_FOLDER}"
    databricks labs lakebridge transpile \
        --source-dialect "informatica (desktop edition)" \
        --target-technology "${TARGET_TECH}" \
        --input-source "${INPUT_SOURCE}" \
        --output-folder "${OUTPUT_FOLDER}" \
        --overrides-file "${OVERRIDES_FILE}" \
        --skip-validation true \
        $PROFILE_FLAG

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
SUPPLEMENTS_DIR="${OUTPUT_FOLDER}/supplements"

# Move JSON files (skip any override file that ended up in output)
shopt -s nullglob
json_files=("${OUTPUT_FOLDER}"/*.json)
shopt -u nullglob

if [ ${#json_files[@]} -gt 0 ]; then
    mkdir -p "${JOBS_DIR}"
    for f in "${json_files[@]}"; do
        mv "$f" "${JOBS_DIR}/"
        echo "  Moved: $(basename "$f") -> databricks_jobs/"
    done
fi

# Move supplemental python file
if [ -f "${OUTPUT_FOLDER}/databricks_conversion_supplements.py" ]; then
    mkdir -p "${SUPPLEMENTS_DIR}"
    mv "${OUTPUT_FOLDER}/databricks_conversion_supplements.py" "${SUPPLEMENTS_DIR}/"
    echo "  Moved: databricks_conversion_supplements.py -> supplements/"
fi

# Move remaining .py files to switch_input folder for LLM conversion
SWITCH_INPUT_DIR="${OUTPUT_FOLDER}/switch_input"
mkdir -p "${SWITCH_INPUT_DIR}"

shopt -s nullglob
py_files=("${OUTPUT_FOLDER}"/*.py)
shopt -u nullglob

if [ ${#py_files[@]} -eq 0 ]; then
    echo "Error: no .py files remaining in ${OUTPUT_FOLDER} for LLM conversion."
    exit 1
fi

for f in "${py_files[@]}"; do
    mv "$f" "${SWITCH_INPUT_DIR}/"
    echo "  Moved: $(basename "$f") -> switch_input/"
done

echo "  ${#py_files[@]} Python file(s) ready for LLM conversion."

# Drop params files that contain only Informatica system variables (never referenced).
# Start is already excluded by skip_component_types in the override.
# Clean up any dangling dependency references in the job JSON.
SYSTEM_VAR_SUFFIXES="(StartTime|EndTime|Status|PrevTaskStatus|ErrorCode|ErrorMsg|SrcSuccessRows|SrcFailedRows|TgtSuccessRows|TgtFailedRows|TotalTransErrors|FirstErrorCode|FirstErrorMsg)"

shopt -s nullglob
job_json_files_step3=("${JOBS_DIR}"/*.json)
shopt -u nullglob

for job_json in "${job_json_files_step3[@]}"; do
    wf_name=$(basename "$job_json" .json)
    params_file="${SWITCH_INPUT_DIR}/${wf_name}_params.py"
    drop_params=false

    # Check if params file should be dropped (system-only variables)
    if [ -f "$params_file" ]; then
        user_vars=$(sed -n "s/.*declare_workflow_param('\([^']*\)'.*/\1/p" "$params_file" \
            | grep -vE "wkf_.*_${SYSTEM_VAR_SUFFIXES}$" || true)
        if [ -z "$user_vars" ]; then
            drop_params=true
            echo "  Removing system-only params file: $(basename "$params_file")"
            rm "$params_file"
        fi
    fi

    # Update job JSON: remove params task if dropped, clean dangling depends_on refs
    python3 -c "
import json, sys

drop_params = sys.argv[2] == 'true'

with open(sys.argv[1], 'r+') as f:
    job = json.load(f)
    tasks = job.get('tasks', [])

    remove_keys = set()
    if drop_params:
        for t in tasks:
            nb = t.get('notebook_task', {}).get('notebook_path', '')
            if nb.endswith('_params') or nb.endswith('_params.py'):
                remove_keys.add(t['task_key'])

    # Also remove any dangling depends_on references (e.g. to skipped Start task)
    valid_keys = {t['task_key'] for t in tasks} - remove_keys
    job['tasks'] = [t for t in tasks if t['task_key'] not in remove_keys]
    for t in job['tasks']:
        if 'depends_on' in t:
            t['depends_on'] = [d for d in t['depends_on']
                               if d.get('task_key') in valid_keys]
            if not t['depends_on']:
                del t['depends_on']
    f.seek(0); json.dump(job, f, indent=3); f.truncate()
" "$job_json" "$drop_params"

    if [ "$drop_params" = true ]; then
        echo "  Updated ${wf_name}.json: removed params task + dangling refs"
    fi
done

echo ""

# =========================================================================
# Step 3b: Apply Unity Catalog table namespace mapping to local files
# =========================================================================

if [ -n "$TABLE_MAPPING" ] || [ -n "$UC_CATALOG" ]; then
    echo "Step 3b: Applying UC table namespace mapping to switch_input files..."

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
        # saveAsTable('table') or saveAsTable("table")
        content = re.sub(
            r"(saveAsTable\s*\(\s*['\"])" + re.escape(src) + r"(['\"])",
            r'\1' + tgt + r'\2', content)
        # DeltaTable.forName(spark, 'table')
        content = re.sub(
            r"(forName\s*\(\s*spark\s*,\s*['\"])" + re.escape(src) + r"(['\"])",
            r'\1' + tgt + r'\2', content)
        # SQL: FROM/JOIN/INTO/UPDATE table
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
    echo "Step 3b: Skipping UC table namespace mapping (not configured)."
fi
echo ""

# =========================================================================
# Step 3c: Inject PARAMS_TASK_KEY into local files before Switch
# =========================================================================

# The LLM prompt tells Switch to convert get_workflow_param() calls using a
# PARAMS_TASK_KEY variable for the taskKey argument.  That variable must exist
# in each mapping file.  We know the real task key from the job JSON, so inject
# the constant into local .py files now -- before they are sent to Switch.

echo "Step 3c: Injecting PARAMS_TASK_KEY into local switch_input files..."

shopt -s nullglob
job_json_files_3c=("${JOBS_DIR}"/*.json)
shopt -u nullglob

injections_made=0
for job_json in "${job_json_files_3c[@]}"; do
    wf_name=$(basename "$job_json" .json)

    params_key=$(python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    job = json.load(f)
for t in job.get('tasks', []):
    nb = t.get('notebook_task', {}).get('notebook_path', '')
    if nb.endswith('_params') or nb.endswith('_params.py'):
        print(t['task_key'])
        break
" "$job_json" 2>/dev/null) || true

    if [ -z "$params_key" ]; then
        continue
    fi

    shopt -s nullglob
    mapping_files=("${SWITCH_INPUT_DIR}/${wf_name}"_*.py)
    shopt -u nullglob

    for pyf in "${mapping_files[@]}"; do
        base=$(basename "$pyf")
        if [[ "$base" == *_params.py ]]; then
            continue
        fi

        if ! grep -q 'get_workflow_param' "$pyf"; then
            continue
        fi

        # Inject the constant after the first COMMAND separator (i.e. after imports)
        python3 -c "
import sys
path, key = sys.argv[1], sys.argv[2]
with open(path, 'r') as f:
    content = f.read()
marker = '# COMMAND ----------'
idx = content.find(marker)
if idx >= 0:
    insert_pos = content.find('\n', idx) + 1
    line = f'PARAMS_TASK_KEY = \"{key}\"\n'
    content = content[:insert_pos] + '\n' + line + content[insert_pos:]
else:
    content = f'PARAMS_TASK_KEY = \"{key}\"\n\n' + content
with open(path, 'w') as f:
    f.write(content)
" "$pyf" "$params_key"

        echo "  Injected PARAMS_TASK_KEY=\"${params_key}\" into: ${base}"
        ((injections_made++))
    done
done

if [ "$injections_made" -eq 0 ]; then
    echo "  No files reference get_workflow_param (no injection needed)."
else
    echo "  Injected PARAMS_TASK_KEY into ${injections_made} file(s)."
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
cat > "$SWITCH_CONFIG_LOCAL" <<SWITCHEOF
# Switch configuration file
# Auto-generated by informatica_switch_pipeline run.sh

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
request_params:
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
# Step 5: Run Switch LLM conversion
# =========================================================================

echo "Step 5: Running Switch LLM transpiler (this may take a while)..."
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
echo "  LLM conversion is in progress. Notebooks at: ${OUTPUT_WS_FOLDER} when completed"
echo ""

fi  # end SKIP_SWITCH guard (Steps 4, 5)


# =========================================================================
# Step 6: Upload supplemental module to workspace
# =========================================================================

SUPPLEMENTS_FILE="${SUPPLEMENTS_DIR}/databricks_conversion_supplements.py"
if [ -f "$SUPPLEMENTS_FILE" ]; then
    echo "Step 6: Uploading databricks_conversion_supplements.py to workspace..."
    databricks workspace import "${OUTPUT_WS_FOLDER}/databricks_conversion_supplements.py" \
        --file "$SUPPLEMENTS_FILE" \
        --format AUTO \
        --overwrite \
        $PROFILE_FLAG
    echo "  Uploaded to: ${OUTPUT_WS_FOLDER}/databricks_conversion_supplements.py"
    echo ""
else
    echo "Step 6: No supplemental file to upload."
    echo ""
fi

# =========================================================================
# Step 7: Create Databricks jobs
# =========================================================================

shopt -s nullglob
job_json_files=("${JOBS_DIR}"/*.json)
shopt -u nullglob

if [ ${#job_json_files[@]} -gt 0 ]; then
    echo "Step 7: Creating Databricks jobs..."
    echo ""

    # Strip classic cluster config from job JSONs when using serverless
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

    # Detect workspace host URL for job links
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
    echo "Step 7: No JSON job files to create."
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
