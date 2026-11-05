# STS Lakebridge Lineage

Folder and command: `sts-lb-lineage`.


Table-level lineage and migration insights from the **Lakebridge Analyzer** (BladeBridge) JSON output, for SQL and ETL estates (Informatica, DataStage, SSIS, Talend, SAS, ADF, Oracle, Teradata, and the other analyzer sources). It writes JSON, CSV, Mermaid, and one self-contained HTML viewer.

Run it on a **laptop or jump host**, next to the analyzer output. It does not need Databricks, unless you choose to push the lineage into Unity Catalog.

## Safety rules

| Rule | Why |
|---|---|
| Read-only on the source | It reads analyzer JSON (and, with `--run`, the source folder you point the analyzer at). It never changes source code. |
| Writes only to `-o` | Every output goes to the output folder you give (default `lineage/`). Nothing is deleted. |
| Offline viewer | `lineage.html` makes no network requests. Open it from `file://`. |
| No installs | It never installs software beyond its own pinned Python dependencies, which uv fetches. |
| AI is opt-in and local | AI-assisted impact analysis runs only with `--serve`. The viewer is served on `127.0.0.1` only, and only the selected impact result goes to the endpoint you name, in your workspace. |
| Unity Catalog writes are opt-in | Nothing is sent to a workspace unless you pass `--uc-push <profile>` and confirm. It only creates objects; it never updates or deletes. |
| No customer data in git | Keep analyzer output and generated files out of the repo. `fixtures/` holds synthetic data only. |

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) (it fetches Python 3.10-3.13 and the dependencies).
- Lakebridge Analyzer JSON: `databricks labs lakebridge analyze ... --generate-json true`, or run the analyzer through this tool with `--run`.
- For `--uc-push` only: a Databricks CLI profile with `CREATE EXTERNAL METADATA` on the metastore.

## Quick start

```sh
uv run sts_lb_lineage.py analyzer-output.json --open                 # build lineage/ and open the viewer
uv run sts_lb_lineage.py sql.json etl.json -o out/                    # several reports at once (SQL and ETL can mix)
uv run sts_lb_lineage.py --run ./exports --platform "Informatica - PC" --open   # run the analyzer first
```

All options: `uv run sts_lb_lineage.py --help`.

## Viewer

`lineage.html` is one file (about 3 MB), built with the Databricks design system (dbui). A left navigation groups the pages:

| Group | Page | What you get |
|---|---|---|
| Summary | Overview | Estate counts, object roles, sources to ingest by schema, most shared tables, most connected processes, and how far to trust the scan. |
| Summary | Statistics | Lines of code, SQL statements, dynamic SQL, loops, parameters, programs by technology and type, analyzer complexity levels, top transformations and functions, most read and most fed tables, tables by schema. |
| Explore | Process map | One node per top-level process; shared tables connect them. Filter by technology, search, and a coupling matrix. Self-contained processes are hidden by default. |
| Explore | Objects | Every table and job. Group by process, technology, schema, or type. List or graph. Selector bar, for example `role:source`, `process:wf_sales`, `complexity:high`, `+dw.fact_orders+`. |
| Analyze | Impact analysis | Downstream impact, upstream sources, or the path between two objects or processes, with a CSV report. Opens with suggested starting points. With `--serve`, an AI assistant explains the impact, flags risks, and answers questions. |

Use the search box at the top of every page to jump to any process, table, or job. Drawers show the details of an object (role, process, upstream, downstream, programs, suggested UC target) or a process (programs and the analyzer drivers behind their complexity, objects, shared tables, dependencies). Every view is in the URL hash, so you can share a link to it.

The tool reports facts from the scan. It does not estimate effort or plan migration waves.

## AI-assisted impact analysis (optional)

```sh
uv run sts_lb_lineage.py analyzer-output.json --serve --profile <profile> --endpoint <chat-endpoint>
```

This builds the lineage, then serves the viewer at `http://127.0.0.1:8765/` (`--port` to change). On the Impact analysis page, pick a target, then use **Explain impact and risks** or ask a question. The answer is a short summary, the affected processes and objects, risk flags (shared tables, dependency cycles, approximate job-level edges, dynamic SQL, loops, high analyzer complexity), and what to check first.

- **Endpoint**: any chat serving endpoint in the workspace, for example a Foundation Model or external model behind Unity AI Gateway, so the gateway's permissions, rate limits, guardrails, and usage tracking apply.
- **Auth**: the Databricks CLI profile, through the Databricks SDK. The credential stays in the Python process and never reaches the browser.
- **What is sent**: only the selected impact result, at most 300 objects with their names, roles, processes, and the involved programs' technology, analyzer complexity, and dynamic-SQL / loop counts. No source code or SQL text.
- **Local server protections**: binds to `127.0.0.1` only; checks the `Host` header; requires a per-run session token that only the served page has; accepts JSON only and caps the request size and question length. The answer is rendered as text, never as HTML.
- The model is told to use only the context it receives. AI output can still be wrong; check it against the lineage.
- Without `--serve`, the HTML file works as before, with no AI panel and no network access.

## Outputs

| File | Content |
|---|---|
| `lineage.json` | Nodes, edges, programs, and `insights` (summary, processes, process edges, shared tables, statistics, trust checks) |
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
uv run sts_lb_lineage.py report.json --uc-catalog main --uc-pattern "{catalog}.{layer}_{schema}.{table}"

# table volumes (CSV columns: table, rows, bytes), for example exported from a Lakebridge Profiler extract
uv run sts_lb_lineage.py report.json --volumes volumes.csv

# push the legacy lineage as Unity Catalog external lineage
uv run sts_lb_lineage.py report.json --source-system TERADATA --uc-prefix legacy --uc-push <profile>
```

- **Mapping**: a suggestion only. Temp tables and orphans get no target.
- **Volumes**: matched on the full name. A bare name matches only when one side has no schema.
- **External lineage**: one external metadata object per legacy table (`<prefix>__<name>`, with the legacy name, role, process, and suggested target as properties) and one relationship per table-to-table edge. `--uc-push` prints the workspace and counts, asks you to type `yes` (`--yes` skips the prompt), checks the per-metastore limits (10,000 objects, 100,000 relationships), and skips objects that already exist, so reruns are safe. See [external lineage](https://docs.databricks.com/aws/en/data-governance/unity-catalog/external-lineage).

## Analyzer quirks handled (databricks-bb-analyzer 0.3.1)

- SSIS, Talend, and SAS JSON can fail the analyzer's own schema check. `--run` warns and uses the JSON anyway.
- SSIS `objectRel` has shifted fields (`action` holds the table, `object` the task, `count` the direction); the tool repairs it.
- SAS can emit the off-schema level `COMPLEX`; it is kept and counted in the trust checks.

## Limits

- Job-grain ETL edges link all inputs of a job to all its outputs, so multi-flow mappings over-link. The trust checks count them.
- No column-level lineage (not in the analyzer JSON).
- Names come through as the analyzer writes them (ETL instance names, unqualified SQL variables).

## Maintainers

```sh
uv run --with pytest pytest -q                       # tests (synthetic fixtures)
cd viewer && npm ci --legacy-peer-deps && npm run build   # rebuild lineage_viewer.html
cp ../path/to/lineage.json public/sample.json && npm run dev   # live preview
```

`npm audit` reports a zod advisory (GHSA-mrhx-c7xc-m3w5) through `@databricks/design-system`. zod is not in the built `lineage_viewer.html`; it only affects the build machine.
