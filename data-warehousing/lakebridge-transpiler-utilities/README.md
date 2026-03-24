# Lakebridge utilities

Utilities for migrating legacy ETL (SSIS and Informatica) to Databricks using [Lakebridge](https://databrickslabs.github.io/lakebridge) (BladeBridge transpiler + Switch LLM transpiler).

**Prerequisite:** Lakebridge must be installed (`databricks labs install lakebridge`).

These scripts are example automation for efficient Lakebridge usage and are intended as reference. Do not run them in production without custom tuning for your environment.

---

## Quick start

1. Install Lakebridge: `databricks labs install lakebridge`.
2. For **SSIS → Lakeflow pipelines:**  
   `cd ssis-to-databricks-pipelines && ./run.sh`
3. For **Informatica → jobs:**  
   `cd informatica-to-databricks-jobs-pipeline && ./run.sh `

Use the sample overrides in **bladebridge-overrides** when you need to customize BladeBridge behavior or copy config into your own override file.

---

## Contents

| Folder | Purpose |
|--------|--------|
| **bladebridge-overrides** | Sample BladeBridge override JSONs used to configure source-specific translation (workflow component mapping, config variables). |
| **ssis-to-databricks-pipelines** | End-to-end automation: SSIS packages to Lakeflow Declarative Pipelines. |
| **informatica-to-databricks-jobs-pipeline** | End-to-end automation: Informatica mappings to Databricks notebooks and jobs. |

---

## bladebridge-overrides

Reusable override configurations for BladeBridge:

- **sample_override_ssis.json** — SSIS-specific: `config_variables` (e.g. `ROOT_DELTA_DIR`, `NODE_TYPE`, `TASK_PATH`), `workflow_specs` with mappings for `EXECUTE_SQL_TASK`, `EXECUTE_SQL`, `EXECUTE_PACKAGE`, `PIPELINE`, and other SSIS component types.
- **sample_override_informatica.json** — Informatica-specific: mappings for `SESSION`, `SUBJOB`, `LOAD_PARAMETERS`, `WORKLET`, `SET_VARIABLE`, and related component types; `skip_component_types` (e.g. email, die, synchronize).

Use these as references or pass them to Lakebridge at this prompt "Specify the config file to override the default[Bladebridge] config - press <enter> for none" or the `-r` / `--overrides-file` flags.

---

## ssis-to-databricks-pipelines

Converts SSIS packages (`.dtsx` or project folders) into **Lakeflow Declarative Pipeline** modules using the `pyspark.pipelines` API (`@dp` decorators).

**Files:**

- **run.sh** — Main automation script. It:
  1. Installs BladeBridge and Switch (unless skipped),
  2. Runs BladeBridge on the SSIS input,
  3. Prepares `.py` files for Switch and uploads the custom prompt,
  4. Runs the Switch LLM transpiler,
  5. Creates the Lakeflow Declarative Pipeline (with bronze/silver/gold catalogs and schemas).

- **ssis_to_databricks_prompt.yml** — Switch system prompt and few-shot examples. It defines:
  - Converting BladeBridge SSIS PySpark to `@dp.table`, `@dp.temporary_view`, `@dp.materialized_view`,
  - Table reference rules (no `spark.read`; use `spark.sql(...)` with catalog/schema from `spark.conf.get(...)`),
  - Medallion layer assignment (bronze/silver/gold),
  - T-SQL and SSIS expression to Spark SQL translation,
  - Removal of metadata (e.g. `StartTime`, `PackageName`) and unused imports.

- **sample_override.json** — Default BladeBridge override for this pipeline (can be overridden with `-r`).

**Running the script:**

- Run `./run.sh` **interactively** to be prompted for required values (Databricks profile, input path, output folder, workspace folder).
- Run `./run.sh` **with command line flags** to specify all options directly.
  - Use `-h` for full help.
  - Common options include:
    - `-i`: input SSIS path
    - `-o`: BladeBridge output folder
    - `-w`: workspace folder for notebooks
    - `-r`: override JSON
    - `-x`: custom prompt YAML
    - Catalog and schema flags for bronze/silver/gold medallion layers
- A `run.txt` copy of the script is provided for environments that restrict downloading `.sh` files.
- On Windows, use WSL or Git Bash to execute the script.
- To test the converted code, ensure all referenced tables already exist in Databricks (either as federated sources or pre-created tables).
- You can also run individual steps from the script manually.

---

## informatica-to-databricks-jobs-pipeline

Converts Informatica PowerCenter mappings to **Databricks notebooks** and **Databricks jobs** (from BladeBridge-generated job JSONs).

**Files:**

- **run.sh** — Main automation script. It:
  1. Installs BladeBridge and Switch (unless skipped),
  2. Runs BladeBridge on the Informatica source (e.g. XML exports),
  3. Splits out job JSONs and supplemental files,
  4. Uploads the custom Switch prompt and runs the LLM transpiler on mapping notebooks,
  5. Uploads the supplemental Python module (e.g. `databricks_conversion_supplements.py`),
  6. Creates Databricks jobs from the JSON definitions.

- **informatica_to_databricks_prompt.yml** — Switch system prompt and few-shot examples. It defines:
  - Fixes for BladeBridge output: `sys_row_id` column references (string literals to `col().cast('string')`), comment-code concatenation, widget defaults, cell separators,
  - Preserving mapping structure (double-select pattern, `conform_df_columns`),
  - Oracle/Teradata to Spark SQL dialect translation,
  - Workflow parameter usage (`get_workflow_param` / `set_workflow_param` vs `dbutils.jobs.taskValues`),
  - Removal of duplicate target writes and low-priority cleanup (e.g. `quit()` → “Notebook execution complete”).

- **sample_override.json** — Default BladeBridge override for this pipeline (can be overridden with `-r`).

- **table_mapping.csv** — Optional CSV mapping source table names to Unity Catalog three-level names (`catalog.schema.table`). Format: `source_table,uc_table`. Lines starting with `#` are comments. Pass the path via `--table-mapping` when running the script.

**Running the script:**

- Run `./run.sh` **interactively** to be prompted for profile, Informatica input path, output folder, and workspace folder.
- Run `./run.sh` **with command line flags** to supply all options directly.
  - Use `-h` for full help.
  - Common options include:
    - `-i`: Informatica source
    - `-o`: output folder
    - `-w`: workspace folder
    - `-r`: override JSON
    - `-x`: custom prompt YAML
    - `--compute`: specify compute type (serverless/classic)
    - `--cloud`: specify cloud provider
    - `--table-mapping`: CSV mapping source tables to UC names
- A `run.txt` copy of the script is provided for environments where downloading `.sh` is restricted.
- On Windows, use WSL or Git Bash to run the script.
- Individual steps from the script can also be executed manually.
- To test the converted code, ensure all referenced tables already exist in Databricks (either as federated sources or pre-created tables).


