# T-SQL (MSSQL) → Databricks SDP or SQL Warehouse Job

Converts **T-SQL** procedures/functions (`.sql` files) through BladeBridge + Switch. **`--switch-style sdp`** (default): LDP SQL notebooks and a **Lakeflow Declarative Pipeline**. **`--switch-style sql`**: Spark SQL **FILE** artifacts and a **SQL Warehouse Job** with inferred task dependencies.

**Prerequisite:** [Lakebridge](https://databrickslabs.github.io/lakebridge) (`databricks labs install lakebridge`) and a configured Databricks CLI profile. Environment setup (Python, Java, workspace access) is in the [installation guide](https://databrickslabs.github.io/lakebridge/docs/installation/). This pipeline **installs the transpilers** (BladeBridge and Switch) on first run when you accept the install prompts; afterward use skip flags to avoid reinstalling.

Use these scripts as a starting point. Align catalog and schema settings with your medallion layout and test thoroughly before production.

## Files

| File | Role |
| --- | --- |
| `run.sh` | Orchestrates BladeBridge (optional skip), Switch, and pipeline or job creation. |
| `mssql_sp_to_sdp_switch_prompt.yml` | Default Switch prompt for `--switch-style sdp`. |
| `mssql_to_sparksql_file_prompt.yml` | Default Switch prompt for `--switch-style sql`. |
| `sample_override_tsql.json` | Default BladeBridge override for T-SQL; pass `-r` to substitute. |
| `run.txt` | Same script as `run.sh`, stored as `.txt` when `.sh` downloads are blocked; after copy, rename to `run.sh` and `chmod +x`, or run `bash run.txt`. If `run.sh` and `run.txt` ever disagree, treat `run.sh --help` as authoritative. |

## How to run

```bash
cd tsql-to-databricks-pipeline
./run.sh
./run.sh --help
```

## What to change

- **Prompt tuning:** `mssql_sp_to_sdp_switch_prompt.yml` and `mssql_to_sparksql_file_prompt.yml` are starting points—adjust them for **your workload** (procedure shapes, dynamic SQL, and organizational SQL style differ). Use `-x` for a custom prompt.
- **Destination pattern:** `--switch-style sdp` vs `sql` (pipeline vs warehouse job). This drives which default `.yml` prompt `run.sh` selects unless `-x` is set.
- **BladeBridge:** `-r` with a customized override JSON; compare with `../bladebridge-overrides` only if you share patterns across tools.
- **Skip deterministic pass:** `--skip-bladebridge` to feed existing or hand-written `.sql` into Switch only.
- **Medallion / parameters:** `--single-catalog` vs per-layer prompts; in sdp mode, `--pipeline-catalog` / `--pipeline-target`; in sql mode, `--warehouse-id`, `--job-name`, `--skip-job-create`, `--wait`.
- **Iteration:** Install-skip flags and `--skip-switch` / `--skip-bladebridge` for partial reruns.

See [../README.md](../README.md) for detailed behavior and troubleshooting.
