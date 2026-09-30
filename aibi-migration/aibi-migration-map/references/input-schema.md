# Input schema — accepted forms

The skill accepts raw Tableau files (`.twbx`/`.tdsx`), raw Power BI templates (`.pbit`/`.pbix`),
or a hand-filled CSV. All produce the same starter `mapping.yaml`, so the curate → render steps
are identical regardless of source.

## A) Raw Tableau files — `.twbx` / `.tdsx` (preferred)

Point `scripts/parse_twbx.py` at a folder (or individual files). The folder can be anywhere the
exported files live — a local directory or a mounted Volume of workbooks. No manual entry.

```bash
python3 scripts/parse_twbx.py ~/estate_export/ -o mapping.yaml --account "Acme Retail"
```

For each workbook it opens the packaged `.twb` XML (never the `.hyper` data extract) and derives:

| Signal | Where it comes from in the XML | Used for |
|--------|--------------------------------|----------|
| worksheets / dashboards | `<worksheet>` / `<dashboard>` elements | sheet weight, sizing |
| upstream tables | custom-SQL `FROM`/`JOIN` targets + physical `<relation table=…>` | **fact-table clustering** (groups) |
| calculated fields | `<column><calculation class='tableau' formula=…>` | Metric View seed + drift + App rule |
| parameters | `Parameters` datasource + `param-domain-type` columns | App rule (`≥ 3`) |
| connection classes | `<connection class=…>` (redshift / athena / sqlproxy → published / hyper → extract) | source label, source count |
| mark types | `<mark class=…>` histogram (`Text` vs. all) | `text_pct` for the Genie rule |

`.tdsx` shared datasources are parsed for their name + dominant schema and offered as
"shared logic to fold in" on the Metric View of the matching fact-table group.

**Grouping:** workbooks are clustered on the **fact table** they share (`*_fct` / `*_data`,
preferring true `_fct` tables). The calendar/date dimension is treated as a conformed *time*
dimension (surfaced on the Metric View), never as a grouping key. A workbook with no discernible
fact table falls back to its source system. Rename these groups to business subject areas while curating.

> **Privacy:** raw workbooks embed real identifiers — customer/brand names, DB hostnames, catalogs,
> service-account usernames (occasionally access keys) in connection strings, and analyst desktop
> paths. Scrub before reusing a real workbook as a shared example.

## A2) Raw Power BI templates — `.pbit` / `.pbix`

Point `scripts/parse_pbit.py` at a folder (or individual `.pbit`/`.pbix` files). One file = one report.

```bash
python3 scripts/parse_pbit.py ~/estate_export/ -o mapping.yaml --account "Acme Retail"
```

It reads the tabular model (`DataModelSchema`) and report pages, deriving:

| Signal | Where it comes from | Used for |
|--------|---------------------|----------|
| DAX measures | `model.tables[].measures[].expression` | **Metric View seed + drift** |
| calculated columns | `model.tables[].columns[]` (type `calculated`) | `n_calcs` (App rule) |
| relationships | `model.relationships[]` | **fact-table clustering** (the hub) |
| upstream table | partition M source `… Name="X", Kind="Table" …` (or native `FROM`) | Metric View `core_source` |
| connector | M function (`Databricks.Catalogs`, `Sql.Database`, `Snowflake.…`) | source-system label |
| pages / visuals | `Report/definition/pages/**` | sheet weight, `text_pct` |

Prefer `.pbit` (File → Export → Power BI template) — its model is readable JSON. `.pbix` and
thin/live-connection `.pbit` are also accepted but on a **cheap path**: their model is a binary
blob (`.pbix` import) or absent (live connection), so the report + source are routed but **no
measures / Metric View** are seeded, and the parser prints a warning naming what to export (the
dataset's `.pbit`, or `model.bim` via Tabular Editor / pbi-tools). Model-only templates (measures,
no visuals) route to a dashboard by default — treat them as semantic-model / Metric-View candidates
while curating. A very large single model is flagged as a candidate to **split** into several
subject-area Metric Views (each with its own Genie space + dashboard).

## B) Hand-filled template (no raw files)

Minimum viable CSV, one row per workbook, for `scripts/route.py`:

```csv
workbook,group,worksheets,datasources,text_pct,params,n_calcs,purpose,source
Q3 Revenue by Region,Revenue,24,1,0.20,0,31,,redshift
Product Lookup Table,Revenue,3,1,1.0,0,4,lookup,redshift
Stock-out Monitor,Ops,4,1,0.90,0,6,exception monitor,snowflake
Pricing What-If Tool,Pricing,18,5,0.10,6,58,pricing tool,snowflake
```

| Column | Meaning | If unknown |
|--------|---------|-----------|
| `workbook` | name (required) | — |
| `group` | subject area (becomes the group; else a single bucket) | leave blank |
| `worksheets` | sheet count | `0` |
| `datasources` | distinct source count | `1` |
| `text_pct` | fraction of tabular/text views, `0`–`1` (or `crosstab`/`yes` → `1.0`) | `0` |
| `params` | parameter count (drives App detection) | `0` |
| `n_calcs` | calculated-field count (drives App detection) | `0` |
| `purpose` | short note; the word `monitor`/`error`/`status` triggers the Alert route | blank |
| `source` | source-system label shown in the table | `unknown` |

The more you fill in (`text_pct`, `params`, `n_calcs`, `purpose`), the better the routing. With
only names + groups, everything defaults to dashboards and you route by hand in the mapping.
