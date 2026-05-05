# DataStage → Databricks jobs

End-to-end helper script: **IBM DataStage** XML exports → BladeBridge → Switch LLM → Databricks notebooks and **job definitions**. Includes optional Unity Catalog table renaming, DataStage-specific job JSON cleanup, and mechanical notebook fixes before/after Switch.

Use these scripts as a starting point. Tune paths, overrides, and **Switch prompts for your workload** (stage patterns and notebook conventions vary), then validate in your workspace before production.

## Files

| File | Role |
| --- | --- |
| `run.sh` | Orchestrates install (optional), BladeBridge, staging, mapping, JSON fixes, Switch, uploads, and job creation. |
| `datastage_to_databricks_prompt.yml` | Default Switch prompt; override with `-x`. |
| `sample_override.json` | Default BladeBridge override for this folder; override with `-r` or start from `../bladebridge-overrides/sample_override_datastage.json`. |
| `run.txt` | Long-form commented reference for the same pipeline (do not substitute for `run.sh` execution). |

## How to run

```bash
cd datastage-to-databricks-jobs-pipeline
./run.sh              # interactive prompts
./run.sh --help       # print all flags (-h is equivalent)
```

The script is **interactive**: every setting below can be supplied ahead of time as a **flag**. Run `./run.sh --help` for the authoritative short option names. When a prompt shows a value in **\[brackets\]**, press Enter to accept that default.

### Auth and what to run

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| Databricks CLI profile | `-p`, `--profile` | `DEFAULT` | Which entry in `~/.databrickscfg` authenticates the CLI. Use `DEFAULT` when that profile is already correct (for example on a cluster). |
| User email (for workspace paths / overrides) | `-e`, `--user-email` | auto-detected from profile | Override if auto-detection fails or paths must match a specific user. |
| Run Switch LLM conversion? (Y/n) | `--skip-switch` | Y (run Switch) | **N** keeps only deterministic BladeBridge output; you finish LLM-oriented edits yourself. Pass `--skip-switch` to skip Switch entirely. |
| Install Switch LLM transpiler first? (y/N) | `--skip-llm-install` | N after first run | **y** the first time you install Switch; later use **N**, or pass `--skip-llm-install` to skip reinstall. |
| Run BladeBridge deterministic conversion? (Y/n) | `--skip-bladebridge` | Y | **N** reuses existing BladeBridge output (for example while iterating on the Switch prompt or post-processing). |
| Install BladeBridge transpiler first? (y/N) | `--skip-det-install` | N after first run | **y** the first time; later **N**, or pass `--skip-det-install` to skip BladeBridge reinstall only. |

### Source and output

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| Path to DataStage source files (XML exports) | `-i`, `--input-source` | (prompted) | Directory of DataStage XML exports or a single file. Used for BladeBridge and for dependency-graph reconstruction. |
| Workspace output folder (on cluster) | `-o`, `--output-folder` | (prompted) | On a **cluster** web terminal this must start with `/Workspace/...`. The script uses a `pipeline/` staging area and a `notebooks/` folder under your chosen base path. |
| Output folder (local) | `-o`, `--output-folder` | (prompted) | On a **local** machine, local path for BladeBridge and staging; you are also prompted for a workspace folder for notebooks. |
| Workspace folder for notebooks (local only) | `-w`, `--output-ws-folder` | (prompted) | Must start with `/Workspace/...`; where converted notebooks and Switch targets live when you run locally. |

### BladeBridge configuration

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| BladeBridge target technology | `-t`, `--target-tech` | `PYSPARK` | `PYSPARK`: Python notebooks using Spark DataFrame APIs. `SPARKSQL`: SQL-oriented notebooks. `PYSPARK` is the usual choice for DataStage migrations. |
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
| Custom Switch prompt YAML | `-x`, `--custom-prompt` | `datastage_to_databricks_prompt.yml` here | Point to your own prompt file when you need different instructions or examples. |

### Compute for the generated Databricks jobs

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| Generated job compute type | `--compute` | `serverless` | `serverless` is recommended. `classic` if you need a specific node type or networking. |
| Cloud provider | `--cloud` | auto-detected from workspace URL (classic only) | `azure`, `aws`, or `gcp`. |
| Worker node type | `--node-type` | cloud default (`Standard_D4ds_v5` / `i3.xlarge` / `n1-standard-4`) | Only for **classic** compute. |

### Table namespace mapping (optional)

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| Table mapping file found … Use it? (Y/n) | `--table-mapping` | none | Points to a CSV: each row **`source_table,catalog.schema.target_table`** rewrites table references in converted notebooks. If `table_mapping.csv` sits next to `run.sh` with data, the script offers to use it; you can also pass `--table-mapping` explicitly. |
| Default UC catalog \[skip\] and **Default UC schema** | *(no CLI flag)* | skipped | If you do **not** use a mapping file, you can type a default catalog and schema for unqualified table names, or press Enter on the catalog prompt to leave names unchanged. A schema is required whenever you enter a catalog. |

### Final confirmation

| Prompt | Flag | Default | Explanation |
| --- | --- | --- | --- |
| Proceed? (y/N) | *(none)* | N | Summarizes resolved settings; press **y** to start. |

When the run completes, converted notebooks land under your chosen workspace layout and **one Databricks job is created per DataStage sequence** job JSON.

## What to change

- **BladeBridge behavior:** Edit `-r` JSON (component mappings, skips) or merge ideas from `../bladebridge-overrides/sample_override_datastage.json`.
- **Switch / LLM output:** Replace or fork `datastage_to_databricks_prompt.yml` and pass `-x`. Expect to iterate: defaults are not optimized for every DataStage workload—add rules and examples that reflect your jobs.
- **UC naming:** Maintain a CSV and pass `--table-mapping` so generated code targets the right `catalog.schema.table`.
- **Target technology:** `-t PYSPARK` vs `SPARKSQL` changes BladeBridge’s target output type when your export needs it.
- **Iterating:** Use `--skip-bladebridge` or `--skip-switch` to rerun only the phase you are debugging; adjust intermediate job JSON or notebooks in the output folder if you need manual fixes between steps.
