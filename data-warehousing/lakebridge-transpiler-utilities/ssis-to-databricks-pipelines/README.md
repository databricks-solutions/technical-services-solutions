# SSIS → Databricks (Lakeflow SDP or Databricks SQL)

End-to-end helper script: **SQL Server Integration Services** packages (`.dtsx` or projects) → BladeBridge → Switch LLM → either a **Lakeflow Declarative Pipeline** (default) or **Databricks SQL** files orchestrated by a **SQL Warehouse Job** (alternate path).

**Prerequisite:** [Lakebridge](https://databrickslabs.github.io/lakebridge) (`databricks labs install lakebridge`) and a configured Databricks CLI profile. Environment setup (Python, Java, workspace access) is in the [installation guide](https://databrickslabs.github.io/lakebridge/docs/installation/). This pipeline **installs the transpilers** (BladeBridge and Switch) on first run when you accept the install prompts; afterward use skip flags to avoid reinstalling.

Use these scripts as a starting point. Tune paths, overrides, and **Switch prompts for your workload** (package idioms and SQL dialect edges differ by estate), then validate in your workspace before production.

## Files

| File | Role |
| --- | --- |
| `run.sh` | Orchestrates install (optional), BladeBridge, staging, Switch, and pipeline / SQL Warehouse Job creation. |
| `ssis_to_sdp_python_prompt.yml` | Default Switch prompt for `--ssis-output sdp` with `--sdp-language python` (Lakeflow SDP via `@dp` decorators). |
| `ssis_to_sdp_sql_prompt.yml` | Switch prompt for `--ssis-output sdp` with `--sdp-language sql` (LDP SQL syntax, no `@dp`). |
| `ssis_to_dbsql_prompt.yml` | Switch prompt for `--ssis-output dbsql` (one `.sql` file per input). |
| `sample_override.json` | Default BladeBridge override; override with `-r` or start from `../bladebridge-overrides/sample_override_ssis.json`. |
| `run.txt` | Same script as `run.sh`, stored as `.txt` when `.sh` downloads are blocked; after copy, rename to `run.sh` and `chmod +x`, or run `bash run.txt`. |

## How to run

```bash
cd ssis-to-databricks-pipelines
./run.sh              # interactive prompts
./run.sh --help       # print all flags (-h is equivalent)
```

The script is **interactive**: every setting below can be supplied ahead of time as a **flag**. Use `-y`/`--yes` to accept all defaults non-interactively (useful in CI).

### Auth and what to run

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| Databricks CLI profile | `-p`, `--profile` | `DEFAULT` | Which entry in `~/.databrickscfg` authenticates the CLI. |
| User email (for workspace paths) | `-e`, `--user-email` | auto-detected from profile | Override if auto-detection fails. |
| Run Switch LLM conversion? (Y/n) | `--skip-switch` | Y (run Switch) | **N** keeps only deterministic BladeBridge output. |
| Install Switch LLM transpiler first? (y/N) | `--skip-llm-install` | N after first run | **y** the first time; later **N**. |
| Run BladeBridge deterministic conversion? (Y/n) | `--skip-bladebridge` | Y | **N** reuses existing BladeBridge output. |
| Install BladeBridge transpiler first? (y/N) | `--skip-det-install` | N after first run | **y** the first time; later **N**. |
| Non-interactive mode | `-y`, `--yes` | off | Skip all y/n prompts; accept defaults. |

### Source and output

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| Path to SSIS packages | `-i`, `--input-source` | (prompted) | `.dtsx` files or a project folder. |
| Workspace output folder (on cluster) | `-o`, `--output-folder` | (prompted) | On a **cluster** web terminal this must start with `/Workspace/...`. The script uses a `pipeline/` staging area and a `notebooks/` folder under your chosen base path. |
| Output folder (local) | `-o`, `--output-folder` | (prompted) | On a **local** machine, local path for BladeBridge and staging. |
| Workspace folder for notebooks (local only) | `-w`, `--output-ws-folder` | (prompted) | Must start with `/Workspace/...`; where Switch writes converted output when you run locally. |

### BladeBridge configuration

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| BladeBridge override JSON | `-r`, `--overrides-file` | `sample_override.json` in this directory | Replace `<username>` and paths in a copy as needed; see `../bladebridge-overrides/README.md`. |
| BladeBridge config.yml path | `--transpiler-config-path` | bundled default | Pass an explicit `config.yml` if resolution fails. |
| Omit transpiler config path | `--no-transpiler-config-path` | off | Let Lakebridge choose the BladeBridge config path. |

### Switch (LLM) configuration

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| Catalog for Switch artifacts | `-c`, `--catalog` | (required) | Unity Catalog catalog for Switch working state. |
| Schema for Switch artifacts | `-s`, `--schema` | `switch` | Schema inside that catalog. |
| UC Volume name | `-v`, `--volume` | `switch_volume` | Volume under that schema for Switch staging files. |
| Foundation model endpoint | `-m`, `--foundation-model` | `databricks-claude-sonnet-4-5` | Model-serving endpoint Switch calls. |
| Custom Switch prompt YAML | `-x`, `--custom-prompt` | from `--ssis-output` (see below) | Point to your own prompt file. |
| Switch sdp_language | `--sdp-language` | `python` (sdp) / `sql` (dbsql) | Output language for `--ssis-output sdp`: `python` for `@dp` decorators, `sql` for LDP SQL syntax. |
| Wait for Switch LLM to complete | `--wait` | async | Wait synchronously rather than fire-and-forget. |

### Output mode (`--ssis-output`)

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| SSIS Switch output: sdp / dbsql | `--ssis-output` | `sdp` | `sdp` → Lakeflow Declarative Pipeline (Python @dp or LDP SQL via `--sdp-language`); `dbsql` → one `.sql` file per `.py` input + a SQL Warehouse Job. |
| Create a SQL Warehouse Job? (Y/n) | `--skip-job-create` | Y (create) | **N** to skip Step 6 job creation in `dbsql` mode. |
| SQL warehouse ID | `--warehouse-id` | interactive selection (`dbsql` only) | Skip the warehouse picker. |
| Job name | `--job-name` | derived from last file in `switch_input/` | Override the auto-name. |

### Pipeline compute (Lakeflow SDP — `sdp` mode)

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| Pipeline compute — Serverless or Cluster Policy? | `--cluster-policy` | Serverless | Pass `--cluster-policy <ID>` to use a classic cluster policy; otherwise the pipeline runs serverless. |
| Pipeline name | `--pipeline-name` | derived from output folder | Override the auto-name. |

### Medallion architecture (optional, **sdp mode only**)

Medallion is supported only with `--ssis-output sdp`. In `dbsql` mode the script forces a flat layout (`-c` / `-s` for everything) and rejects `--medallion`/`--single-catalog`.

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| Use medallion architecture? (y/N) | `--medallion` | N | Default off — uses `-c/--catalog` and `-s/--schema` for all layers. **y** (or `--medallion`) splits into bronze/silver/gold. Only fires in `sdp` mode. |
| All data layers in same catalog? (Y/n) | `--single-catalog` | (when medallion is on) | Implies `--medallion`; share the Switch catalog across bronze/silver/gold. |
| Bronze / Silver / Gold catalog & schema | `--bronze-catalog` / `--bronze-schema` / `--silver-catalog` / `--silver-schema` / `--gold-catalog` / `--gold-schema` | bronze=schema, silver=schema, gold=schema (when single-catalog) | When medallion is on and not single-catalog, you can supply each layer explicitly. Bronze = raw / source, Silver = business-level entities (facts and dimensions), Gold = aggregated, BI-optimized. |

### Final confirmation

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| Proceed? (y/N) | *(none)* | N | Summarizes resolved settings; press **y** to start. |

## What to change

- **Prompt tuning:** The bundled `*_prompt.yml` files are starting points — edit or replace them so Switch matches **your workload** (package idioms, SQL dialect edges, and review standards differ by estate). Pass `-x` for a custom prompt.
- **Output mode:** `--ssis-output sdp` (Lakeflow SDP) vs `dbsql` (`.sql` files + SQL Warehouse Job). Prompt selection follows this flag unless you set `-x`.
- **BladeBridge:** `-r` for override JSON; `../bladebridge-overrides/sample_override_ssis.json` for a fuller SSIS-oriented override.
- **Medallion:** off by default. Pass `--medallion` (or answer **y** to the prompt) to split bronze/silver/gold; pair with `--single-catalog` for a shared catalog across layers, or per-layer flags for distinct catalogs/schemas.
- **Iteration:** `--skip-bladebridge`, `--skip-switch`, and install-skip flags to rerun only part of the flow; `--transpiler-config-path` if BladeBridge cannot locate `config.yml`.

See [../README.md](../README.md) for the cross-pipeline overview.
