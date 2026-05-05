# SSIS → Databricks (Lakeflow SDP or Spark SQL)

Converts **SQL Server Integration Services** packages (`.dtsx` or projects) via BladeBridge (SSIS → PySpark) and Switch. **Default:** Lakeflow Declarative Pipeline style output. **Alternate:** `--ssis-output sparksql` produces Spark SQL files and a SQL Warehouse Job instead of the DLP creation step.

**Prerequisite:** [Lakebridge](https://databrickslabs.github.io/lakebridge) (`databricks labs install lakebridge`) and a configured Databricks CLI profile. Environment setup (Python, Java, workspace access) is in the [installation guide](https://databrickslabs.github.io/lakebridge/docs/installation/). This pipeline **installs the transpilers** (BladeBridge and Switch) on first run when you accept the install prompts; afterward use skip flags to avoid reinstalling.

Use these scripts as a starting point. Review medallion catalog and schema choices for your environment and test before production.

## Files

| File | Role |
| --- | --- |
| `run.sh` | Orchestrates BladeBridge, Switch, and pipeline or job creation. |
| `ssis_to_databricks_sdp_prompt.yml` | Default Switch prompt for SDP / PySpark pipeline output. |
| `ssis_to_databricks_sdp_sql_prompt.yml` | Switch prompt when running SDP with the SQL-language path inside `run.sh`. |
| `ssis_to_sparksql_file_switch_prompt.yml` | Switch prompt for `--ssis-output sparksql`. |
| `sample_override.json` | Default BladeBridge override; use `-r` to substitute. |
| `run.txt` | Same script as `run.sh`, stored as `.txt` when `.sh` downloads are blocked; after copy, rename to `run.sh` and `chmod +x`, or run `bash run.txt`. |

## How to run

```bash
cd ssis-to-databricks-pipelines
./run.sh
./run.sh --help
```

## What to change

- **Prompt tuning:** The bundled `*_prompt.yml` files are starting points—edit or replace them so Switch matches **your workload** (package idioms, SQL dialect edges, and review standards differ by estate). Use `-x` / `--custom-prompt` for your fork.
- **Output mode:** `--ssis-output sdp` (Lakeflow DLP) vs `sparksql` (`.sql` files + SQL Warehouse Job). Prompt selection follows this flag unless you set `-x`.
- **BladeBridge:** `-r` for override JSON; `../bladebridge-overrides/sample_override_ssis.json` for a fuller SSIS-oriented override.
- **Medallion:** `--single-catalog` to collapse catalog prompts, or set bronze/silver/gold catalog and schema explicitly when prompted (or via flags where supported).
- **Spark SQL job:** `--warehouse-id`, `--wait`, `--skip-job-create` control warehouse attachment and whether the script waits for Switch or skips job creation.
- **Iteration:** `--skip-bladebridge`, `--skip-switch`, and install-skip flags to rerun only part of the flow; `--transpiler-config-path` if BladeBridge cannot locate `config.yml`.

See [../README.md](../README.md) for full flag lists and known Lakebridge CLI issues.
