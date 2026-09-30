---
name: aibi-migration-map
description: Turn raw Tableau workbooks (`.twbx`/`.tdsx`) or Power BI templates (`.pbit`/`.pbix`) — or a hand-filled inventory — into a shareable single-file HTML migration map. Parses the files directly, clusters them on their shared fact tables, routes every workbook/report to the Databricks asset that replaces it (Lakeview dashboard / Genie space / App / SQL Alert), shows the mirror view (each asset and the workbooks it absorbs), and seeds a Metric View blueprint for the semantic layer from the real calculated fields / DAX measures (including detected metric drift). Use when planning a Tableau→AI/BI or Power BI→AI/BI migration, consolidating a large BI estate, or presenting a migration direction to a customer. Triggers on 'migration map', 'tableau to databricks map', 'power bi to databricks map', 'consolidate this BI estate', 'AIBI migration plan', 'what does each workbook become', 'build a migration map'.
user-invocable: true
---

# AI/BI Migration Map

## Overview

Teams migrating a large Tableau or Power BI estate to Databricks AI/BI ask the same two
questions: **"what does each of my reports become?"** and **"where do the semantics live so
answers stay consistent?"** This skill answers both with a single self-contained HTML deliverable
you can present live and share for review in detail.

It produces three mirrored views in one file:

1. **Workbook → Databricks asset** — every workbook, its complexity/source, and the end-state
   asset users open (Lakeview dashboard, Genie space, Databricks App, or SQL Alert).
2. **Asset → workbooks** — the mirror: each end-state asset and every workbook it consolidates.
3. **Metric View blueprint** — the semantic layer as *concepts* (not code): what each Metric
   View standardizes, the metric drift it resolves, and every report you must open to build it.

The routing is **deterministic and defensible** — a documented rule (see
`references/routing-rule.md`) decides dashboard vs. Genie vs. App vs. Alert from signals read
straight out of the workbook XML. The **judgment** parts — subject-area grouping, asset naming,
and Metric View concepts — are yours to curate; the skill scaffolds them and gets out of the way.

This skill answers **"what was each report doing, and what should it become on Databricks?"** — it
deliberately does **not** score migration complexity, effort, or Tableau→Databricks compatibility.
The output is a target design (consolidated assets + a shared Metric View layer), not a sizing estimate.

> See it first: open `examples/example_report.html` in a browser — that is the exact output
> shape. `examples/mapping.example.yaml` is the curated input that produced it.

## Inputs (any of these — see `references/input-schema.md`)

- **Raw Tableau files** (preferred) — a folder of `.twbx` workbooks (and any `.tdsx` shared
  datasources). `scripts/parse_twbx.py` reads them directly: worksheets, dashboards, upstream
  tables (from custom SQL + physical relations), calculated fields, parameters, and mark types.
  Point it at wherever the exported files live — a local folder or a mounted Volume of workbooks.
  **No manual data entry.**
- **Raw Power BI files** (`.pbit`, `.pbix`) — a folder of reports. `scripts/parse_pbit.py` reads
  the tabular model (`DataModelSchema`): tables, relationships, and **DAX measures**, plus the
  report pages. It clusters on the fact table (the relationship hub → its upstream physical table
  via the Power Query source) and seeds Metric Views from the DAX. One file = one report.
  - **`.pbit` (template)** is the best input — its model is readable JSON.
  - **`.pbix` and thin/live-connection `.pbit`** are supported on a **cheap path**: their model is
    either a **binary blob** (`.pbix` import mode — not machine-readable) or **absent** (live
    connection to a shared dataset). The parser still routes the report and its source, but **emits
    no measures / Metric View** and prints a warning telling you what to export to recover them
    (the dataset's `.pbit`, or `model.bim` via Tabular Editor / pbi-tools). Watch for that warning —
    it means the map is missing that report's semantics until you export the model.
- **Hand-filled template** — for estates with no raw files: a small CSV
  (`workbook,group,worksheets,datasources,text_pct,params,n_calcs,purpose,source`) handed to
  `scripts/route.py`.

## Prerequisites

- **Python 3** with **`pyyaml`** (`pip install pyyaml`) — every script needs it. Parsing uses only
  the Python standard library otherwise (`zipfile`, `xml.etree`).
- **An input** in one of the forms above — most often just the folder (or Volume) of `.twbx` /
  `.pbit` files exported from the estate.
- **A browser** to view the rendered HTML. No auth, no network, no Databricks connection required —
  the whole pipeline runs locally and the output is a static file.

## Workflow

**Output location — always.** Write **both** deliverables into an `output/` directory at the root
of the analysis folder (the folder that holds the input files), and create it first. Both artifacts
— `output/mapping.yaml` (the curated source) **and** `output/report.html` (the rendered map) — are
outputs; deliver both, never just the HTML. So for an analysis dir `<DIR>`:

```bash
mkdir -p <DIR>/output
```

### 1 — Parse + route (deterministic, scripted)

```bash
python3 scripts/parse_twbx.py <DIR> -o <DIR>/output/mapping.yaml --account "<Customer>"   # Tableau
python3 scripts/parse_pbit.py <DIR> -o <DIR>/output/mapping.yaml --account "<Customer>"   # Power BI
```

Point the matching parser at the folder of raw files (multiple paths / individual files also work).
Both emit the same `mapping.yaml` shape, so steps 2–4 are identical regardless of source tool.
It reads every workbook's XML, **clusters workbooks on their shared fact table** (the "group on
shared fact tables, not folders" methodology — done automatically because raw files expose the
SQL), applies the routing rule, and writes a **starter `mapping.yaml`**:

- each workbook routed to a suggested asset (with a `_suggested:` note explaining *why*),
  placeholder assets auto-created one per (fact-table group × asset-kind);
- one **Metric View per group, seeded from the real calculated fields** found in those workbooks —
  candidate metrics, the shared calendar/time dimension, published datasources to fold in, and
  **detected drift** (the same metric defined with different formulas across workbooks).

> No raw files, only a spreadsheet inventory? Fill the template CSV (see `references/input-schema.md`)
> and run `scripts/route.py <csv>` instead — same output, same next steps.

Routing assumes **all reports are in use** and **all data is movable to Databricks** (external
sources are migration targets, not blockers) — so every workbook gets a real home. It is
**purpose-only**: it decides *what each report becomes*, never how hard the migration is. State
those assumptions to the customer; they are printed on the report.

### 2 — Curate (judgment — you + the customer's domain knowledge)

Edit `output/mapping.yaml` in place. This is where the value is; the script only gave you a scaffold:

- **Merge / rename / split assets.** The scaffold makes one asset per group×kind; real estates
  consolidate (many workbooks → one dashboard) and occasionally split (an oversized group → two
  dashboards). Give assets real names users will recognize.
- **Rename the fact-table groups to business subject areas.** The parser already clustered
  workbooks on the fact tables they share (e.g. `retail_dm.dm_sales_fct`) — rename those to what the
  business calls them ("Sales & Revenue"), and merge sibling facts that are really one area.
- **Refine each Metric View concept** — the metrics list, `time` dimension, and `drift` are
  **pre-seeded from the workbooks' real calc fields**; your job is to name it, write the purpose
  and grain, confirm the metric definitions, keep the drift worth resolving (same metric, different
  formulas across workbooks — the business case for the layer), and set the owner who must
  adjudicate. Mark the load-bearing ones (`load_bearing: true`) — the ones backing multiple assets.
- **Split a large single-source model into several Metric Views when it spans subject areas.**
  `parse_pbit.py` flags a group whose model is large and multi-domain (many measures across many
  display folders / measure tables) with a `⚠ Large model … consider SPLITTING` note in the MV
  purpose — e.g. a 4,000-measure Power BI model. That is rarely one Metric View: split it into
  several **subject-area** Metric Views (cluster the measures by display folder / measure table),
  and give each its **own Genie space and dashboard** rather than one catch-all. Not always right —
  a genuinely single-subject model stays one MV — so use judgment (or, in interactive mode, ask the
  user, below). To split in the YAML: add multiple `MV-*` entries and multiple `assets`, and point
  each workbook/subject at the right one.
- **Retire duplicates.** Set `target: RETIRE` and `survivor: <asset-id>` on copy-paste forks,
  dated snapshots, and `_test`/`_V2` siblings. They still carry semantics (they appear, struck
  through, on the Metric View that absorbs them) but don't survive as assets.

Use `examples/mapping.example.yaml` as the reference for a fully-curated file.

### 3 — Render (scripted)

```bash
python3 scripts/render.py <DIR>/output/mapping.yaml -o <DIR>/output/report.html
```

Emits one **self-contained** HTML file (all CSS/JS inline, no external references, both light/dark
themes, live search + asset-type filter, tabs, and in-page links from every Metric View reference
to its blueprint card). Safe to email or share — recipient just double-clicks it.

### 4 — Share

Deliver **both** files from `<DIR>/output/`: `report.html` (the presentable map — present it live,
then send it) **and** `mapping.yaml` (the editable source, so the mapping can be re-curated and
re-rendered later). Confirm both exist before finishing — the `.yaml` is easy to forget.

## Interactive mode (optional)

By default the flow is **one-shot** (parse → render → deliver) — right for unattended runs. When
the user asks to "walk me through it" / "do this interactively" / "review before rendering", insert
**one checkpoint between parse and render** (the mapping is where judgment lives — don't gate every
phase):

1. Run the parser → `<DIR>/output/mapping.yaml` **silently** (don't render yet).
2. **Present the draft for review**, in chat:
   - the discovered files, detected **source tool** (Tableau / Power BI), and account;
   - the fact-table **groups** and how many workbooks/reports each consolidates;
   - each workbook/report's **routing** (asset kind), flagging any that look like duplicates;
   - the **seeded Metric Views** — candidate metrics, the time dimension, and any detected drift.

   Then ask the user to adjust: rename/merge/split groups, name/consolidate assets, mark duplicates
   `RETIRE` (+ `survivor:`), and refine Metric View titles / owners / metrics.
   - **If the parser flagged a large model** (`⚠ Large model … consider SPLITTING` in an MV purpose),
     explicitly ask the user whether to **split it into several subject-area Metric Views** (each
     with its own Genie space + dashboard) or keep it as one — then apply their choice. Outside
     interactive mode, make this call by judgment.
   - **If any report was flagged thin** (`⚠` export warning — a `.pbix` or live-connection report),
     tell the user its measures are missing and what to export to recover them.
3. **Apply the edits** to `output/mapping.yaml` directly, then run `render.py`. If the user has no
   edits ("looks good"), render as-is.
4. Deliver **both** `output/report.html` and `output/mapping.yaml`.

## Notes

- **Requires `pyyaml`** (`pip install pyyaml`); parsing otherwise uses only the standard library.
- **`.twbx` extracts are read structurally, not for data.** `parse_twbx.py` reads only the `.twb`
  XML (structure, SQL, calc formulas) — it never opens the packaged `.hyper` data extracts, so no
  row-level data is touched.
- **Anonymize before sharing externally as an example.** Raw `.twbx`/`.tdsx`/`.pbit` embed real
  identifiers — customer/brand names, DB hostnames and catalogs, service-account usernames (and
  occasionally access keys) in connection strings, analyst desktop paths (`C:/Users/<name>/…`), and
  the `.hyper` data itself. If you reuse a real workbook as a teaching example, scrub all of these.
- **The two tables mirror by construction** — both are generated from the one `mapping.yaml`, so
  they never disagree. Report counts on the blueprint can exceed live-asset counts because retired
  duplicates still carry semantics.

## Examples

- **"Build a migration map from these Tableau workbooks"** — with the files in `~/export/`, run
  `mkdir -p ~/export/output && python3 scripts/parse_twbx.py ~/export/ -o ~/export/output/mapping.yaml --account "Acme Retail"`,
  curate `~/export/output/mapping.yaml` (rename fact-table groups, name/consolidate assets, refine
  the seeded Metric Views, mark duplicate workbooks `RETIRE`), then
  `python3 scripts/render.py ~/export/output/mapping.yaml -o ~/export/output/report.html` and share
  **both** files from `~/export/output/`.
- **"We only have a spreadsheet of report names"** — fill the template CSV
  (`references/input-schema.md`), then
  `python3 scripts/route.py ~/estate/inventory.csv -o ~/estate/output/mapping.yaml`, and follow the
  same curate → render flow into `~/estate/output/`.
- **"Show me what the output looks like"** — open `examples/example_report.html` (the synthetic
  Acme Retail example) and its curated source `examples/mapping.example.yaml`.

## Resources

- `scripts/parse_twbx.py` — **Tableau input:** folder of raw `.twbx`/`.tdsx` → starter
  `mapping.yaml` (parse + fact-table clustering + routing + Metric View seeding from calc fields).
- `scripts/parse_pbit.py` — **Power BI input:** folder of `.pbit`/`.pbix` → starter `mapping.yaml`
  (tabular-model parse + fact-hub clustering + routing + Metric View seeding from DAX measures).
- `scripts/parse_common.py` — shared parse helpers (metric detection, drift, fact/dim
  classification) used by both parsers, so Tableau and Power BI outputs stay consistent.
- `scripts/route.py` — the routing rule + mapping builder (shared library); also the CSV entry
  point for a hand-filled `inventory.csv`.
- `scripts/render.py` — curated `mapping.yaml` → single self-contained HTML.
- `templates/report_template.html` — the report shell (inline CSS/JS; meta-driven).
- `references/routing-rule.md` — the dashboard/Genie/App/Alert routing rule + rationale.
- `references/input-schema.md` — all input contracts (raw `.twbx`, raw `.pbit`, hand-filled template).
- `examples/` — `mapping.example.yaml` (fully-curated, synthetic) and `example_report.html`
  (the rendered map — open this first).
