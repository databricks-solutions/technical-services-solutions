# T-SQL (MSSQL) → Databricks SDP or SQL Warehouse Job

End-to-end helper script: **T-SQL** stored procedures, functions, and `.sql` files → BladeBridge → Switch LLM → either a **Lakeflow Declarative Pipeline** with LDP SQL notebooks (default) or **Databricks SQL** FILE artifacts driven by a **SQL Warehouse Job** with inferred task dependencies.

**Prerequisite:** [Lakebridge](https://databrickslabs.github.io/lakebridge) (`databricks labs install lakebridge`) and a configured Databricks CLI profile. Environment setup (Python, Java, workspace access) is in the [installation guide](https://databrickslabs.github.io/lakebridge/docs/installation/). This pipeline **installs the transpilers** (BladeBridge and Switch) on first run when you accept the install prompts; afterward use skip flags to avoid reinstalling.

Use these scripts as a starting point. Tune prompts and overrides for **your workload** (procedure shapes, dynamic SQL, and organizational SQL style differ), then validate in your workspace before production.

## Files

| File | Role |
| --- | --- |
| `run.sh` | Orchestrates install (optional), BladeBridge (optional), staging, table mapping, Switch, and pipeline / SQL Warehouse Job creation. |
| `tsql_to_sdp_prompt.yml` | Default Switch prompt for `--switch-style sdp`. |
| `tsql_to_dbsql_prompt.yml` | Default Switch prompt for `--switch-style dbsql`. |
| `sample_override.json` | Default BladeBridge override for T-SQL; pass `-r` to substitute. |
| `table_mapping.csv` | Optional `source_table,catalog.schema.target_table` mapping; auto-detected next to `run.sh` or pass `--table-mapping`. |
| `run.txt` | Same script as `run.sh`, stored as `.txt` when `.sh` downloads are blocked; after copy, rename to `run.sh` and `chmod +x`, or run `bash run.txt`. |

## How to run

```bash
cd tsql-to-databricks-pipeline
./run.sh              # interactive prompts
./run.sh --help       # print all flags (-h is equivalent)
```

The script is **interactive**: every setting below can be supplied ahead of time as a **flag**. Use `-y`/`--yes` to accept all defaults non-interactively.

### Auth and what to run

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| Databricks CLI profile | `-p`, `--profile` | `DEFAULT` | Which entry in `~/.databrickscfg` authenticates the CLI. |
| User email | `-e`, `--user-email` | auto-detected from profile | Override if auto-detection fails. |
| Run Switch LLM conversion? (Y/n) | `--skip-switch` | Y (run Switch) | **N** keeps only deterministic BladeBridge output. |
| Install Switch LLM transpiler first? (y/N) | `--skip-llm-install` | N after first run | **y** the first time; later **N**. |
| Run BladeBridge deterministic conversion? | `--skip-bladebridge` | depends on `--switch-style` | For `sdp` the default is **Y**; for `dbsql` the default is **N** because BladeBridge often fails on complex stored procedures and feeding raw `.sql` to Switch usually works better. |
| Install BladeBridge transpiler first? (y/N) | `--skip-det-install` | N after first run | **y** the first time; later **N**. |
| Non-interactive mode | `-y`, `--yes` | off | Skip all y/n prompts; accept defaults. |

### Source and output

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| Path to `.sql` file or directory | `-i`, `--input-source` | (prompted) | Single `.sql` file or directory of `.sql` files. |
| Workspace output folder (on cluster) | `-o`, `--output-folder` | (prompted) | On a **cluster** web terminal this must start with `/Workspace/...`. The script uses a `pipeline/` staging area and a `notebooks/` folder under your chosen base path. |
| Output folder (local) | `-o`, `--output-folder` | (prompted) | On a **local** machine, local path for staged files. |
| Workspace folder for converted files (local only) | `-w`, `--output-ws-folder` | (prompted) | Must start with `/Workspace/...`; where Switch writes converted output when you run locally. |

### BladeBridge configuration

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| BladeBridge override JSON | `-r`, `--overrides-file` | `sample_override.json` in this directory | Replace `<username>` in a copy as needed. The bundled override is intentionally minimal — T-SQL inherits most behavior from Lakebridge's built-in `mssql2sparksql.json` base. |
| BladeBridge error log path | `--error-file-path` | `<output-folder>/errors.log` | Where BladeBridge writes conversion errors. |
| BladeBridge config.yml path | `--transpiler-config-path` | bundled default | Pass an explicit `config.yml` if resolution fails. |
| Omit transpiler config path | `--no-transpiler-config-path` | off | Let Lakebridge choose the BladeBridge config path. |

### Switch (LLM) configuration

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| Catalog for Switch artifacts | `-c`, `--catalog` | (required) | Unity Catalog catalog for Switch working state. |
| Schema for Switch artifacts | `-s`, `--schema` | `switch` | Schema inside that catalog. |
| UC Volume name | `-v`, `--volume` | `switch_volume` | Volume under that schema for Switch staging files. |
| Foundation model endpoint | `-m`, `--foundation-model` | `databricks-claude-sonnet-4-5` | Model-serving endpoint Switch calls. |
| Custom Switch prompt YAML | `-x`, `--custom-prompt` | from `--switch-style` | `sdp` → `tsql_to_sdp_prompt.yml`; `dbsql` → `tsql_to_dbsql_prompt.yml`. |
| Wait for Switch LLM to complete | `--wait` | async | Wait synchronously rather than fire-and-forget. |

### Output mode (`--switch-style`)

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| Switch target: sdp / dbsql | `--switch-style` | `sdp` | `sdp` → Lakeflow Declarative Pipeline with LDP SQL notebooks; `dbsql` → Databricks SQL FILE objects + SQL Warehouse Job with inferred task dependencies. |
| Create a SQL Warehouse Job? (Y/n) | `--skip-job-create` | Y (create) | **N** to skip Step 6 job creation in `dbsql` mode. |
| SQL warehouse ID | `--warehouse-id` | interactive selection (`dbsql` only) | Skip the warehouse picker. |
| Job name | `--job-name` | derived from first `.sql` basename | Override the auto-name. |

### Pipeline compute (Lakeflow SDP — `sdp` mode)

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| Lakeflow SDP catalog | `--pipeline-catalog` | same as `-c` | Catalog for the pipeline definition. |
| Lakeflow SDP target schema | `--pipeline-target` | `default` | Target schema. |
| Pipeline compute — Serverless or Cluster Policy? | `--cluster-policy` | Serverless | Pass `--cluster-policy <ID>` for classic compute; otherwise the pipeline runs serverless. |
| Pipeline name | `--pipeline-name` | derived from first `.sql` basename | Override the auto-name. |

### Table namespace mapping (optional)

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| Table mapping file found … Use it? (Y/n) | `--table-mapping` | none | Points to a CSV: each row **`source_table,catalog.schema.target_table`** rewrites table references in staged `.sql` files before Switch runs. If `table_mapping.csv` sits next to `run.sh` with data, the script offers to use it. |
| Default UC catalog and schema | *(no CLI flag)* | skipped | If you do **not** use a mapping file, you can type a default catalog and schema and the rewriter prefixes unqualified table references with `catalog.schema.`. |

### Medallion architecture (optional, **sdp mode only**)

Medallion is supported only with `--switch-style sdp`. In `dbsql` mode the script forces a flat layout (`-c` / `-s` for everything) and rejects `--medallion`/`--single-catalog`.

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| Use medallion architecture? (y/N) | `--medallion` | N | Default off — uses `-c/--catalog` and `-s/--schema` for all layers. **y** (or `--medallion`) splits into bronze/silver/gold. Only fires in `sdp` mode. |
| All data layers in same catalog? | `--single-catalog` | (when medallion is on) | Implies `--medallion`; share the Switch catalog across bronze/silver/gold. |
| Bronze / Silver / Gold catalog & schema | *(prompted when `--medallion` is on)* | bronze=schema, silver=schema, gold=schema (single-catalog) | Bronze = raw / source, Silver = business-level entities (facts and dimensions), Gold = aggregated, BI-optimized. |

### Final confirmation

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| Proceed? (y/N) | *(none)* | N | Summarizes resolved settings; press **y** to start. |

## What to change

- **Prompt tuning:** `tsql_to_sdp_prompt.yml` and `tsql_to_dbsql_prompt.yml` are starting points — adjust them for **your workload** (procedure shapes, dynamic SQL, and organizational SQL style differ). Use `-x` for a custom prompt.
- **Destination pattern:** `--switch-style sdp` vs `dbsql` (pipeline vs warehouse job). This drives which default `.yml` prompt `run.sh` selects unless `-x` is set.
- **BladeBridge:** `-r` with a customized override JSON; the default is intentionally minimal because the Lakebridge built-in T-SQL base is comprehensive. For richer overrides, see `../bladebridge-overrides/sample_override_tsql.json`.
- **Skip deterministic pass:** `--skip-bladebridge` to feed existing or hand-written `.sql` directly into Switch (recommended for complex stored procs that BladeBridge struggles with).
- **UC naming:** Maintain a CSV and pass `--table-mapping` so generated SQL targets the right `catalog.schema.table`.
- **Medallion:** off by default. Pass `--medallion` to split bronze/silver/gold; otherwise both `-c/--catalog` and `-s/--schema` are used for all tier references.
- **Iteration:** Install-skip flags and `--skip-switch` / `--skip-bladebridge` for partial reruns.

See [../README.md](../README.md) for the cross-pipeline overview.
