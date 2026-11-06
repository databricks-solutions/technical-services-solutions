# STS Lakebridge Lineage

Python package and command: `sts-lb-lineage`.

Table-level lineage and migration insights from the **Lakebridge Analyzer** JSON output, for SQL and ETL estates. It covers the 36 source technologies of the Lakebridge Analyzer; see [Supported technologies](#supported-technologies). It writes JSON, CSV, Mermaid, and one self-contained HTML viewer.

Run it on a **laptop or jump host**, next to the Lakebridge Analyzer output. It does not need Databricks, unless you choose to push the lineage into Unity Catalog or use the AI assistant.

## Safety rules

| Rule | Why |
|---|---|
| Read-only on the source | It reads Lakebridge Analyzer JSON (and, with `--run`, the source folder you point the Lakebridge Analyzer at). It never changes source code. A Profiler extract is opened read-only. |
| Writes only to `-o` | Every local output goes to the output folder you give (default `lineage/`). Nothing local is deleted. |
| Offline viewer | `lineage.html` makes no network requests. Open it from `file://`. |
| No installs | It never installs software beyond its own pinned Python dependencies. |
| AI is opt-in and local | AI-assisted impact analysis runs only with `--serve`. The viewer is served on `127.0.0.1` only, and only the selected impact result goes to the endpoint you name, in your workspace. |
| Workspace writes are opt-in | Nothing is sent to a workspace unless you pass `--uc-push`, `--uc-export`, or `--uc-remove`. Each one prints the workspace and a plan, then asks you to type `yes`. |
| Deletes are scoped | `--uc-remove` deletes only external metadata named `<uc-prefix>__*` and its relationships. It never deletes tables. `--uc-export` replaces only the `lineage_*` tables in the schema you name. |
| No customer data in git | Keep Lakebridge Analyzer output and generated files out of the repo. `tests/fixtures/` and `tests/e2e/sources/` hold synthetic data only. |

## Install

Needs [uv](https://docs.astral.sh/uv/getting-started/installation/) (or pip) and Python 3.10-3.13. From a clone of this repo:

```sh
uv tool install "./dw-migration/sts-lb-lineage[all]"     # installs the sts-lb-lineage command
uvx --from "./dw-migration/sts-lb-lineage[all]" sts-lb-lineage --help   # or run it without installing
```

The core needs only the standard library. Extras add optional features:

| Extra | Adds | For |
|---|---|---|
| `analyzer` | Lakebridge Analyzer (`databricks-bb-analyzer`) | `--run` (run the Lakebridge Analyzer first) |
| `databricks` | databricks-sdk | `--serve`, `--uc-push`, `--uc-remove`, `--uc-export` |
| `columns` | sqlglot | `--columns` |
| `profiler` | duckdb | `--profiler` |
| `all` | all of the above | |

Lakebridge Analyzer JSON comes from `databricks labs lakebridge analyze ... --generate-json true`, or from `--run`.

## Quick start

```sh
sts-lb-lineage analyzer-output.json --open                 # build lineage/ and open the viewer
sts-lb-lineage sql.json etl.json -o out/                    # several reports at once (SQL and ETL can mix)
sts-lb-lineage --run ./exports --platform "Informatica - PC" --open   # run the Lakebridge Analyzer first
sts-lb-lineage --run ./exports --platform Datastage --extension xml    # sources that need a file extension
python -m sts_lb_lineage --help                             # all options
```

## Viewer

`lineage.html` is one file (about 3 MB), built with the Databricks design system (dbui). A left navigation groups the pages:

| Group | Page | What you get |
|---|---|---|
| Summary | Overview | Estate counts, object roles, sources to ingest by schema, most shared tables, most connected processes, and how far to trust the scan. |
| Summary | Statistics | Lines of code, SQL statements, dynamic SQL, loops, parameters, programs by technology and type, analyzer complexity levels, top transformations and functions, most read and most fed tables, tables by schema. |
| Explore | Process map | One node per top-level process; shared tables connect them. Filter by technology, search, and a coupling matrix. Self-contained processes are hidden by default. |
| Explore | Objects | Every table and job. Group by process, technology, schema, or type. List or graph. Selector bar, for example `role:source`, `process:wf_sales`, `complexity:high`, `+dw.fact_orders+`. |
| Analyze | Impact analysis | Downstream impact, upstream sources, or the path between two objects or processes, with a CSV report. Opens with suggested starting points. With `--serve`, an AI assistant explains the impact, flags risks, and answers follow-up questions. |
| Compare | Changes | Only with `--compare`: new and removed processes, objects, and relationships, and objects that moved to another process. |

Use the search box at the top of every page to jump to any process, table, or job. Drawers show the details of an object (role, process, upstream, downstream, programs, columns with `--columns`, suggested UC target) or a process (programs and the analyzer drivers behind their complexity, objects, shared tables, dependencies). Every view is in the URL hash, so you can share a link to it. Scoped graphs show at most 1,500 objects; focus on an object to explore beyond that.

The tool reports facts from the scan. It does not estimate effort or plan migration waves.

## Lineage accuracy (optional)

```sh
sts-lb-lineage report.json --search-path dbo,dw          # qualify unqualified names: orders -> dbo.orders
sts-lb-lineage report.json --collapse-instances          # fold ETL instance names: SQ_CUSTOMER, CUSTOMER_1 -> CUSTOMER
sts-lb-lineage report.json --columns                     # column lineage from the SQL embedded in ETL programs
sts-lb-lineage report.json --compare old/lineage.json    # what changed since a previous scan
```

- **Search path**: a name is qualified only when exactly one schema on the path has a table with that name.
- **Instances**: folded only into a base table that exists in the scan. Both rewrites tag the result `merged` and count it in the trust checks.
- **Columns**: parses `INSERT INTO ... SELECT` and `CREATE TABLE ... AS SELECT` with sqlglot. Statements that do not parse are skipped and counted.
- **Compare**: keeps only the file name of the previous scan in the output.

## AI-assisted impact analysis (optional)

```sh
sts-lb-lineage analyzer-output.json --serve --profile <profile> --endpoint <chat-endpoint>
```

This builds the lineage, then serves the viewer at `http://127.0.0.1:8765/` (`--port` to change). On the Impact analysis page, pick a target, then use **Explain impact and risks** or ask a question. The answer is a short summary, the affected processes and objects, risk flags (shared tables, dependency cycles, approximate job-level edges, dynamic SQL, loops, high analyzer complexity), and what to check first. Object and process names in the answer link to their details. Follow-up questions keep the last 3 turns.

- **Endpoint**: any chat serving endpoint in the workspace, for example a Foundation Model or external model behind Unity AI Gateway, so the gateway's permissions, rate limits, guardrails, and usage tracking apply. Requests carry the usage context `client=sts-lb-lineage`.
- **Auth**: the Databricks CLI profile, through the Databricks SDK. The credential stays in the Python process and never reaches the browser.
- **What is sent**: only the selected impact result, at most 300 objects with their names, roles, processes, and the involved programs' technology, analyzer complexity, and dynamic-SQL / loop counts, plus up to 3 earlier questions and answers. No source code or SQL text.
- **Local server protections**: binds to `127.0.0.1` only; checks the `Host` header; requires a per-run session token that only the served page has; accepts JSON only and caps the request size, question length, and history. The answer is rendered as text, never as HTML.
- Answers are not streamed: the server returns the full answer, which keeps the local server simple.
- The model is told to use only the context it receives. AI output can still be wrong; check it against the lineage.
- Without `--serve`, the HTML file works as before, with no AI panel and no network access.

## Outputs

| File | Content |
|---|---|
| `lineage.json` | Nodes, edges, programs, `insights` (summary, processes, process edges, shared tables, statistics, trust checks), and `columns` / `diff` when asked |
| `nodes.csv`, `edges.csv` | Lineage, ready to load into Delta |
| `processes.csv`, `hubs.csv` | Process summary and shared tables |
| `uc_mapping.csv` | Suggested Unity Catalog target per table |
| `uc_external_lineage.json` | Unity Catalog external lineage payload (dry run) |
| `lineage.mmd` | Mermaid flowchart, one subgraph per process |
| `lineage.html` | The viewer |

CSV cells that start with `=`, `+`, `-`, or `@` get a leading `'` so spreadsheets do not run them as formulas.

## How the lineage is built

| Report | Edge | Grain |
|---|---|---|
| SQL (`object_lineage`) | each source -> target, via the file | statement |
| ETL embedded SQL (`sqlStatements[].objectRel`) | each read/source/lookup x write/target/create in one statement, via the job | statement |
| ETL job (`objectRel`) | each source/lookup/read x target/write/create in a job, via the job | job |
| ETL `subJobInfo`, `execute` | parent job -> child job | orchestration |

- **Parent process**: the top of the orchestration chain (Informatica workflow, top-level DataStage sequence, Talend parent job). A SQL file is its own process.
- **Shared table**: a table that more than one process writes or reads. It is the contract between those processes.
- **Roles**: source (read, never written: ingestion scope), terminal (written, never read: outputs or dead-code candidates), intermediate, orphan.
- **Dependency cycle**: processes that feed each other (strongly connected components of the process graph).

## Unity Catalog

```sh
# suggested targets: layer from the role (source -> bronze, intermediate -> silver, terminal -> gold)
sts-lb-lineage report.json --uc-catalog main --uc-pattern "{catalog}.{layer}_{schema}.{table}"

# table volumes: a CSV (columns: table, rows, bytes) or a Lakebridge Profiler DuckDB extract
sts-lb-lineage report.json --volumes volumes.csv
sts-lb-lineage report.json --profiler profiler_extract.db

# push the legacy lineage as Unity Catalog external lineage, and link it to migrated UC tables
sts-lb-lineage report.json --source-system TERADATA --uc-prefix legacy --uc-push <profile> --uc-link

# remove what --uc-push created with this prefix
sts-lb-lineage --uc-prefix legacy --uc-remove <profile>

# export the lineage and insights to Delta tables
sts-lb-lineage report.json --uc-export <catalog>.<schema> --profile <profile> --warehouse <warehouse-id>
```

- **Mapping**: a suggestion only. Temp tables and orphans get no target. When several legacy tables map to one target, the CLI warns, `uc_mapping.csv` fills `shared_with`, the object drawer shows the other tables, and the trust checks count it.
- **Volumes**: matched on the full name. A bare name matches only when one side has no schema. `--profiler` scans the extract for a table with a table-name column and a row-count or size column, and prints the table it used. CSV values win over Profiler values.
- **External lineage**: one external metadata object per legacy table (`<prefix>__<name>`, with the legacy name, role, process, and suggested target as properties) and one relationship per table-to-table edge. `--uc-link` also links each legacy table to its suggested UC table, when that table exists, so the Catalog Explorer lineage of the migrated table shows its legacy upstream. `--uc-push` prints the workspace and a plan (new and existing objects), asks you to type `yes` (`--yes` skips the prompt), checks the per-metastore limits (10,000 objects, 100,000 relationships), and skips objects that already exist, so reruns are safe. Needs `CREATE EXTERNAL METADATA` on the metastore. See [external lineage](https://docs.databricks.com/aws/en/data-governance/unity-catalog/external-lineage).
- **Delta export**: creates the schema and a volume `sts_lb_lineage_files` if missing, uploads the rows as JSON lines, and creates or replaces the tables `lineage_nodes`, `lineage_edges`, `lineage_processes`, `lineage_shared_tables`, `lineage_programs`, `lineage_columns`, and `lineage_summary`. Object names are data in the files, never SQL text; the catalog and schema must be plain identifiers.

## Supported technologies

The tool reads the JSON of every Lakebridge Analyzer source technology. How much lineage you get depends on what the Lakebridge Analyzer extracts. The end-to-end tests (`tests/e2e/`) run Lakebridge Analyzer 0.3.1 on one small synthetic sample per technology and record the result:

- **Table lineage**: table-to-table edges (and job links where the format has them).
- **Job links only**: orchestration between jobs, no tables.
- **Inventory only**: programs, complexity, and statistics, no edges.
- **Not parsed**: the analyzer found nothing in the synthetic sample. A real export may give more; the sample format is a best guess.

| Technology (`--platform`) | Result | Notes from the e2e sample |
|---|---|---|
| Athena, IBM DB2, Oracle, Presto, Redshift, MS SQL Server, Synapse, Teradata | Table lineage | Complete for `CREATE TABLE AS SELECT`, `INSERT ... SELECT`, and `SELECT INTO`. |
| BigQuery | Table lineage | With backtick names, a join source comes back as its alias. |
| Cloudera (Impala), Hive | Table lineage | `INSERT OVERWRITE TABLE` is not seen. |
| Greenplum, Netezza, Vertica | Table lineage | With a distribution clause (`DISTRIBUTED BY`, `DISTRIBUTE ON`, `SEGMENTED BY`), the first join table is lost. |
| Snowflake | Table lineage | `CREATE OR REPLACE TRANSIENT TABLE ... AS SELECT` is not seen. |
| PySpark | Table lineage | Only SQL inside `spark.sql()`; DataFrame API calls give no lineage. |
| PIG | Table lineage | Job-level relations, so inputs x outputs over-link. |
| SAS | Table lineage | `PROC SQL`; a DATA step `SET` was not captured. |
| Informatica - PC | Table lineage | Workflow, session, and mapping links. Job-level table names have no schema (a SQL override keeps it). Exports declared as Windows-1252 failed on macOS; UTF-8 works. |
| SSIS | Table lineage | Execute SQL tasks; the OLE DB destination is reported as a read. |
| PentahoDI | Table lineage | `<schema>` is ignored, so put `schema.table` in `<table>`. `.kjb` jobs give no links. |
| Oozie | Job links only | Only `workflow.xml` is read; Hive scripts and inline queries give no tables. |
| ADF | Job links only | Execute Pipeline links; Copy activities and datasets give no tables. |
| Jupyter Notebook, SQOOP, SAPHANA - CalcViews, SSRS, Alteryx, BODS | Inventory only | SQOOP needs `.txt` files. BODS reads XML exports; `.atl` fails. Alteryx captures inputs only. |
| SPSS | Inventory only | Needs `--extension sps`. |
| Datastage | Inventory only | Needs `--extension xml` (XML export); the text `.dsx` format fails. Stages are counted. |
| Informatica Cloud | Not parsed | Needs `--extension zip`. |
| Talend, ABInitio, Informatica - Big Data Edition, Oracle Data Integrator | Not parsed | |

`--extension` is needed because the Lakebridge Analyzer Python wrapper cannot pass the analyzer's file-extension option; with it, the tool runs the bundled analyzer binary directly. When an e2e case fails after a Lakebridge Analyzer upgrade, the analyzer may have improved: update the case in `tests/e2e/test_e2e.py` and this table.

## Lakebridge Analyzer quirks handled (version 0.3.1)

- SSIS, Talend, and SAS JSON can fail the Lakebridge Analyzer's own schema check. `--run` warns and uses the JSON anyway.
- SSIS `objectRel` has shifted fields (`action` holds the table, `object` the task, `count` the direction); the tool repairs it.
- SAS can emit the off-schema level `COMPLEX`; it is kept and counted in the trust checks.
- File and folder paths are absolute on the scanning machine; the tool keeps them relative to the scanned folder, so outputs carry no local paths.
- PIG keeps quotes around table names, and Oozie qualifies parent actions but not child actions; the tool normalizes both.

## Limits

- Job-grain ETL edges link all inputs of a job to all its outputs, so multi-flow mappings over-link. The trust checks count them. The Lakebridge Analyzer JSON gives only transformation counts per job, not the flow between them, so a finer grain is not possible.
- Column lineage needs embedded SQL. Mappings without SQL text have no column lineage.
- Without `--search-path` and `--collapse-instances`, names come through as the Lakebridge Analyzer writes them.

## Development

Run these from `dw-migration/sts-lb-lineage/`:

```sh
# unit tests (synthetic fixtures, no Lakebridge Analyzer needed)
uv run -p 3.13 --no-project --with-editable '.[test,columns,profiler,databricks]' pytest -q

# end-to-end tests (about 12 minutes): run the Lakebridge Analyzer on tests/e2e/sources/
uv run -p 3.12 --no-project --with-editable '.[test,analyzer]' pytest -q -m e2e

# rebuild the viewer into sts_lb_lineage/lineage_viewer.html
cd viewer && npm ci --legacy-peer-deps && npm run build

# live preview of the viewer with your own lineage.json
cp <your-output>/lineage.json viewer/public/sample.json && cd viewer && npm run dev
```

CI runs the unit tests on pull requests that touch this folder (`.github/workflows/sts-lb-lineage-tests.yml`). The end-to-end tests run only on demand.

`npm audit` reports a zod advisory (GHSA-mrhx-c7xc-m3w5) through `@databricks/design-system`. zod is not in the built `lineage_viewer.html`; it only affects the build machine.

## Maintainers

- Andres Garcia (andres.garcia@databricks.com), Shared Technical Services
