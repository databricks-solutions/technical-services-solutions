# Informatica → Databricks jobs

End-to-end helper script: **Informatica PowerCenter** exports → BladeBridge → Switch LLM → Databricks notebooks, supplemental Python, and **Databricks jobs** created from BladeBridge-generated job JSON. Includes optional Unity Catalog table renaming.

**Prerequisite:** [Lakebridge](https://databrickslabs.github.io/lakebridge) (`databricks labs install lakebridge`) and a configured Databricks CLI profile. Environment setup (Python, Java, workspace access) is in the [installation guide](https://databrickslabs.github.io/lakebridge/docs/installation/). This pipeline **installs the transpilers** (BladeBridge and Switch) on first run when you accept the install prompts; afterward use skip flags to avoid reinstalling.

**Prerequisite (shell):** `run.sh` is a **Bash** script. Run it from a **Bash-capable environment**: a **Databricks cluster web terminal**, **Linux or macOS terminal**, or **Git Bash** on Windows. Windows Command Prompt and PowerShell do not run `run.sh` directly; use Git Bash, WSL, or `bash run.sh` / `bash run.txt`.

Use these scripts as a starting point. Tune paths, overrides, and **Switch prompts for your workload** (mapping/session patterns and coding conventions vary), then validate in your workspace before production.

## Files

| File | Role |
| --- | --- |
| `run.sh` | Orchestrates install (optional), BladeBridge, staging, Switch, upload of supplements, and job creation. |
| `informatica_to_jobs_prompt.yml` | Default Switch prompt; override with `-x`. |
| `sample_override.json` | Default BladeBridge override for this folder; override with `-r` or start from `../bladebridge-overrides/sample_override_informatica.json`. |
| `table_mapping.csv` | Optional `source_table,catalog.schema.target_table` mapping; auto-detected next to `run.sh` or pass `--table-mapping`. |
| `run.txt` | Same script as `run.sh`, stored as `.txt` when `.sh` downloads are blocked; after copy, rename to `run.sh` and `chmod +x`, or run `bash run.txt`. |

## How to run

```bash
cd informatica-to-databricks-jobs-pipeline
./run.sh              # interactive prompts
./run.sh --help       # print all flags (-h is equivalent)
```

The script is **interactive**: every setting below can be supplied ahead of time as a **flag**. Run `./run.sh --help` for the authoritative short option names. When a prompt shows a value in **\[brackets\]**, press Enter to accept that default.

### Auth and what to run

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| Databricks CLI profile | `-p`, `--profile` | `DEFAULT` | Which entry in `~/.databrickscfg` authenticates the CLI. Use `DEFAULT` when that profile is already correct (for example on a cluster). |
| User email (for workspace paths / overrides) | `-e`, `--user-email` | auto-detected from profile | Override if auto-detection fails or paths must match a specific user. |
| Run Switch LLM conversion? (Y/n) | `--skip-switch` | Y (run Switch) | **N** keeps only deterministic BladeBridge output. Pass `--skip-switch` to skip Switch entirely. |
| Install Switch LLM transpiler first? (y/N) | `--skip-llm-install` | N after first run | **y** the first time; later **N**, or pass `--skip-llm-install` to skip Switch reinstall. |
| Run BladeBridge deterministic conversion? (Y/n) | `--skip-bladebridge` | Y | **N** reuses existing BladeBridge output (for example while iterating on the Switch prompt). |
| Install BladeBridge transpiler first? (y/N) | `--skip-det-install` | N after first run | **y** the first time; later **N**, or pass `--skip-det-install` to skip BladeBridge reinstall only. |

### Source and output

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| Path to Informatica source files | `-i`, `--input-source` | (prompted) | Directory of Informatica PowerCenter exports or a single file. Used by BladeBridge. |
| Workspace output folder (on cluster) | `-o`, `--output-folder` | (prompted) | On a **cluster** web terminal this must start with `/Workspace/...`. The script uses a `pipeline/` staging area and a `notebooks/` folder under your chosen base path. |
| Output folder (local) | `-o`, `--output-folder` | (prompted) | On a **local** machine, local path for BladeBridge and staging; you are also prompted for a workspace folder for notebooks. |
| Workspace folder for notebooks (local only) | `-w`, `--output-ws-folder` | (prompted) | Must start with `/Workspace/...`; where converted notebooks and Switch targets live when you run locally. |

### BladeBridge configuration

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| BladeBridge target technology | `-t`, `--target-tech` | `PYSPARK` | `PYSPARK`: Python notebooks. `SPARKSQL`: SQL-oriented notebooks. `SPARKSQL` is the BladeBridge enum and is preserved verbatim. `PYSPARK` is the usual choice. |
| BladeBridge override JSON | `-r`, `--overrides-file` | `sample_override.json` in this directory | Replace `<username>` and paths in a copy as needed; see `../bladebridge-overrides/README.md`. |
| BladeBridge error log path | `--error-file-path` | `<output-folder>/errors.log` | Where BladeBridge writes conversion errors. |
| BladeBridge config.yml path | `--transpiler-config-path` | bundled default under `~/.databricks/labs/remorph-transpilers/...` | Pass an explicit `config.yml` if resolution fails. |
| Omit transpiler config path | `--no-transpiler-config-path` | off | Let Lakebridge choose the BladeBridge config path instead of passing `--transpiler-config-path`. |

### Switch (LLM) configuration

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| Catalog name for Switch artifacts | `-c`, `--catalog` | `lakebridge` | Unity Catalog catalog for Switch working state (created if missing; requires sufficient privileges). |
| Schema name for Switch artifacts | `-s`, `--schema` | `switch` | Schema inside that catalog (auto-created when possible). |
| UC Volume name for Switch artifacts | `-v`, `--volume` | `switch_volume` | Volume under that schema where Switch stages files during the LLM run. |
| Foundation model endpoint | `-m`, `--foundation-model` | `databricks-claude-sonnet-4-5` | Model-serving endpoint Switch calls; must be reachable from your workspace. |
| Custom Switch prompt YAML | `-x`, `--custom-prompt` | `informatica_to_jobs_prompt.yml` here | Point to your own prompt file when you need different instructions or examples. |

### Compute for the generated Databricks jobs

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| Generated job compute type | `--compute` | `serverless` | `serverless` is recommended. `classic` if you need a specific node type or networking. |
| Cloud provider | `--cloud` | auto-detected from workspace URL (classic only) | `azure`, `aws`, or `gcp`. |
| Worker node type | `--node-type` | cloud default (`Standard_D4ds_v5` / `i3.xlarge` / `n1-standard-4`) | Only for **classic** compute. |

### Table namespace mapping (optional)

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| Table mapping file found … Use it? (Y/n) | `--table-mapping` | none | Points to a CSV: each row **`source_table,catalog.schema.target_table`** rewrites table references in converted notebooks. If `table_mapping.csv` sits next to `run.sh` with data, the script offers to use it. |

### Final confirmation

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| Proceed? (y/N) | *(none)* | N | Summarizes resolved settings; press **y** to start. |

When the run completes, converted notebooks land under your chosen workspace layout and **one Databricks job is created per Informatica workflow** job JSON.

## What to change

- **BladeBridge behavior:** Edit `-r` JSON (component mappings, skips) or merge ideas from `../bladebridge-overrides/sample_override_informatica.json`.
- **Switch / LLM output:** Replace or fork `informatica_to_jobs_prompt.yml` and pass `-x`. Expect to iterate: defaults are not optimized for every workload — add rules and examples that reflect your mappings and session patterns.
- **UC naming:** Maintain a CSV and pass `--table-mapping` so generated code targets the right `catalog.schema.table`.
- **Target technology:** `-t PYSPARK` vs `SPARKSQL` changes BladeBridge's target output type (`SPARKSQL` is the BladeBridge enum, preserved verbatim).
- **Iterating:** Use `--skip-bladebridge` or `--skip-switch` to rerun only the phase you are debugging.
