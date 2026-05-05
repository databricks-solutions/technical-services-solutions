# Informatica → Databricks jobs

Converts **Informatica PowerCenter** exports through BladeBridge and Switch into Databricks notebooks, supplemental Python, and **Databricks jobs** created from BladeBridge-generated job JSON.

**Prerequisite:** [Lakebridge](https://databrickslabs.github.io/lakebridge) (`databricks labs install lakebridge`) and a configured Databricks CLI profile. Environment setup (Python, Java, workspace access) is in the [installation guide](https://databrickslabs.github.io/lakebridge/docs/installation/). This pipeline **installs the transpilers** (BladeBridge and Switch) on first run when you accept the install prompts; afterward use skip flags to avoid reinstalling.

Use these scripts as a starting point. Validate notebooks and jobs in a development workspace before production.

## Files

| File | Role |
| --- | --- |
| `run.sh` | Full pipeline: install (optional), BladeBridge, split artifacts, Switch, upload supplements, create jobs. |
| `informatica_to_databricks_prompt.yml` | Default Switch prompt; override with `-x`. |
| `sample_override.json` | Default BladeBridge override; override with `-r` or use `../bladebridge-overrides/sample_override_informatica.json` as a richer starting point. |
| `table_mapping.csv` | Optional `source_table,uc_table` mapping; pass with `--table-mapping`. |
| `run.txt` | Same script as `run.sh`, stored as `.txt` when `.sh` downloads are blocked; after copy, rename to `run.sh` and `chmod +x`, or run `bash run.txt`. |

## How to run

```bash
cd informatica-to-databricks-jobs-pipeline
./run.sh
./run.sh --help
```

## What to change

- **Prompt tuning:** `informatica_to_databricks_prompt.yml` is a template—tune it for **your workload** (mappings, session patterns, and coding conventions vary). Pass `-x` with a customized YAML when defaults miss recurring issues.
- **Unity Catalog names:** Populate or extend `table_mapping.csv` and pass `--table-mapping` so generated SQL uses the right three-part names.
- **BladeBridge:** `-r` pointing at your override JSON; compare with `../bladebridge-overrides/sample_override_informatica.json` for extra `workflow_specs` / `skip_component_types`.
- **Compute:** `--compute` (serverless vs classic), `--cloud`, `--node-type` for job clusters created from JSON.
- **BladeBridge output type:** `-t` / `--target-tech` `PYSPARK` (default) or `SPARKSQL` when the export benefits from SQL-target conversion.
- **Partial reruns:** `--skip-bladebridge`, `--skip-switch`, or install-skip flags to avoid reinstalling tools while you iterate.
