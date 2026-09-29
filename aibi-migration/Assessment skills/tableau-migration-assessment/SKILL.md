---
name: tableau-migration-assessment
description: >
  Bulk profiling and migration-readiness assessment for Tableau files
  (.twb / .twbx workbooks and .tds / .tdsx data sources)
  before converting them to Databricks AI/BI dashboards. Load this skill when the user
  asks to assess, profile, audit, or evaluate Tableau files for migration complexity,
  or when bulk-importing Tableau files from a Unity Catalog Volume.
---

# Tableau Migration Assessment Skill

This skill guides a **read-only profiling pass** over one or more Tableau files
— workbooks (`.twb` / `.twbx`) and data sources (`.tds` / `.tdsx`).
It produces, for a batch of files, **one individual Migration Assessment Report per file**
plus **one Migration Summary Report** that rolls the individual reports up into a
high-level cross-file view. The **automation estimate is anchored to the `/importBI`
migration agent** — the intended execution path for Tableau → Databricks AI/BI
conversions. Every ✅/⚠️/🔧 classification reflects what `/importBI` can handle today.
The **Automation Uplift** section in each individual report then shows how applying
[uc-semantics-patterns](https://github.com/databricks-solutions/uc-semantics-patterns)
recipes during migration can raise the automatable share further.

The reports focus on blockers, frictions, and the auto vs. manual split — without
performing any conversion.

> **CRITICAL — MANDATORY REPORT FORMAT**: You MUST produce the reports using the
> EXACT section headings and table structures defined in the "Report Structure"
> section below. Do NOT invent your own numbered sections (Part 1, Part 2, 1, 2, 3…),
> do NOT add sections not in the template, and do NOT omit required sections.
> The Automation Classification and Automation Uplift sections are MANDATORY in
> every individual report. Violation of this format makes the reports unusable.
>
> **TWO KINDS OF REPORT**: Produce (1) an **Individual Workbook Report** for EACH
> file, and (2) a single **Migration Summary Report** that summarizes all of them
> at a high level. Never fold individual detail into the summary, and never make the
> summary the only output.
>
> **CONCISENESS RULE**: Reports must be SHORT. Summarize counts by category
> (e.g. "Simple aggregations (SUM, AVG, etc.) | 18 | ✅ Auto"). NEVER list
> individual calculated-field names — no field-by-field listings. NEVER list
> individual relationships or joins one by one. Group and count.

## When to Use

- User attaches one or more `.twb`, `.twbx`, `.tds`, or `.tdsx` files and asks to assess or profile them
- User points to a UC Volume path containing Tableau files and asks for bulk assessment
- User asks about migration complexity, blockers, or readiness for Tableau → AI/BI migration

## Workflow

### Step 1 — Enumerate Files

If the user provides a Volume path (e.g. `/Volumes/catalog/schema/volume/`):
1. List all `.twb`, `.twbx`, `.tds`, and `.tdsx` files in that path
2. Report the count and file names before proceeding
3. If no Tableau files are found, inform the user and stop

If the user attaches files directly, use those.

> **Note on file types**: `.twb` is raw workbook XML; `.twbx` is a zipped package
> (workbook XML + extracts + resources). `.tds` is a raw Tableau data-source
> definition (connection + calculated fields, no worksheets/dashboards); `.tdsx`
> is a zipped package (`.tds` + extract). All four are profiled the same way —
> the workbook/data-source XML is the source of truth for calculated fields,
> data sources, and (for workbooks) worksheets, dashboards, and actions.
> `.tds` / `.tdsx` data sources have no worksheets, dashboards, filters, or
> actions, so they are inherently **model-only** — apply the Empty Report
> Handling callout for their visual/interaction sections.

### Step 2 — Prerequisites Check

Before profiling, scan data-source connections and flag blocking prerequisites:

- **Connection strings / parameters**: List all data-source connections and any
  workbook parameters that must resolve to concrete values before conversion
  (server hostname, HTTP path, catalog, initial SQL). Flag which must resolve.
- **Non-Databricks sources**: Flag any SQL Server, Oracle, Snowflake, Excel/CSV,
  Google Sheets, published/extract data sources, or other non-Databricks
  connections requiring data migration, federation, or upload.
- **Extracts (.hyper)**: Flag `.hyper` extracts — they are point-in-time snapshots;
  AI/BI dashboards query live UC data, so extracts are informational only and the
  underlying live source must be identified.
- **Source table inventory**: List UC schema.table references (and non-UC tables)
  so the user can verify accessibility.

### Step 3 — Profile Each File

For each Tableau file, hand off to the `/importBI` migration specialist on a
**temporary or existing dashboard** with a `continueMessage` that:
- Begins with `/importBI`
- Explicitly states: **"Profile only — do NOT convert. Return the full analysis
  of data sources, data model, calculated fields, LOD expressions, table
  calculations, visualizations, filters, and interactivity. Do not create any
  datasets or widgets."**
- Includes the file name or path

**Parallelize when more than one file is present.** If the volume (or attachment
set) contains **2 or more** files, profile them in **parallel batches of up to 4
files at a time**: dispatch one profiling task per file (each an independent
`/importBI` handoff) as concurrent subagents, up to 4 running at once. When a
batch finishes, start the next batch until all files are profiled. Each subagent
must carry the same read-only, profile-only `continueMessage` above and return
its analysis output. Collect every batch's results before producing reports.

If **only one** file is present, profile it directly with a single `/importBI`
handoff (no batching needed).

> **Hard constraint**: Do NOT allow any specialist or subagent to create datasets,
> widgets, or perform any conversion. This is a read-only assessment, whether run
> sequentially or in parallel.

### Step 4 — Produce Reports

1. For EACH file, produce a self-contained **Individual Workbook Report** using
   the template below.
2. After all individual reports, produce ONE **Migration Summary Report** that
   summarizes every file at a high level (no re-inventory of features).

Return all reports in the chat: the individual reports first, then the summary.

## Deduplication Rules

Each fact or feature appears in exactly ONE place.

**Within an individual report:**
1. **Executive Overview** names each complexity driver once with count and brief
   resolution. No full technical detail — that belongs in the Inventory.
2. **Feature Inventory** is the single detailed listing. Each feature lives in
   exactly one sub-section:
   - LOD expressions, table calcs, sets/groups/bins/hierarchies, blends → Data Modeling only
   - Quick filters / filter controls → Filters only (not also Interactivity)
   - Dashboard actions (filter/highlight/URL/navigation/parameter) → Interactivity only
3. **Automation Classification** references Inventory rows by feature name and
   adds the auto/manual column — no re-description.

**Across reports:**
4. The **Migration Summary Report** contains ONLY high-level cross-file roll-ups
   and one-line-per-file summaries. It NEVER re-inventories features or repeats
   an individual report's tables — it references each file by name.

## Empty Report Handling

When a file has **0 worksheets/visuals** — a data-source-only or connection-only
workbook, or any `.tds` / `.tdsx` data source — collapse Visualizations,
Interactivity, and Filters into one callout in that file's individual report:

> **Model-only workbook** — this file contains data-source connections and
> calculated fields with no worksheets, dashboards, filters, or actions. The
> dashboard must be designed from scratch after conversion. Visual/interaction
> inventory is N/A.

Do NOT print empty tables for each section.

## Report Structure

**You MUST use the EXACT headings and tables below.** These are not examples
— they are the mandatory output formats. Copy the heading hierarchy verbatim.
Do NOT use numbered sections (## Part 1, ## 1. Model Overview, etc.). Do NOT
add sections like "Fact-Domain Grouping" or "Relationship Analysis" — those
details belong INSIDE the tables below.

**Anti-patterns (DO NOT do these)**:
- ❌ Listing individual calculated-field names (e.g. "`Profit Ratio`, `Sales YTD`…")
- ❌ Listing individual relationships/joins one by one
- ❌ Listing individual LOD expressions with full formula text
- ❌ Using ✅/⚠️/❌ — use ✅/⚠️/🔧 (Auto / Auto+workaround / Manual)
- ❌ Producing > 400 lines per individual report
- ❌ Omitting the Automation Classification or Automation Uplift sections from an individual report
- ❌ Skipping individual reports and returning only the summary

**Correct patterns**:
- ✅ "Simple aggregations (SUM, AVG, etc.) | 18 | ✅ Auto"
- ✅ "Relationships (physical joins) | 13 | ✅ Auto | Direct metric-view joins"
- ✅ "INCLUDE/EXCLUDE LODs | 6 | 🔧 Manual | Context-dependent, redesign"

### Template A — Individual Workbook Report (produce one per file)

```markdown
# Migration Assessment Report — <Workbook Name>

**Date scanned**: <date> | **Source path**: <path> | **File type**: <.twb / .twbx / .tds / .tdsx>

| Metric | Count |
|---|---|
| Worksheets | ... |
| Dashboards | ... |
| Data sources | ... |
| Physical data connections | ... |
| Calculated fields | ... |
| LOD expressions | ... |
| Table calculations | ... |

## Prerequisites

### Connections & Parameters

| Connection / Parameter | Status | Action |
|---|---|---|
| catalog (workbook parameter) | Unresolved | Resolve to concrete catalog |
| .hyper extract | Point-in-time | Informational — identify live source |

### Source Tables

| Schema.Table | Used By | Accessible |
|---|---|---|
| catalog.schema.table | Orders (data source) | To verify |

### Non-Databricks Sources

<list or "None — all sources are Databricks">

## Executive Overview

**Complexity**: <Low / Medium / High>

**Rationale**: <2–3 sentences>

### Complexity Drivers (ranked by impact)

| # | Driver | Count | Impact | Resolution |
|---|---|---|---|---|
| 1 | ... | ... | 🔴/🟠/🟡 | ... |

## Feature Inventory

Each feature appears ONCE. Only list features that have non-zero occurrences.

### Data Sources

| Connection Type | Count | Databricks? | Migration Impact |
|---|---|---|---|
| Databricks (live, passthrough) | ... | Yes | No migration needed |
| Databricks (with custom SQL / transforms) | ... | Yes | Source view needed |
| Extract (.hyper) | ... | Depends | Identify & point at live source |
| Non-Databricks (SQL Server, Excel, etc.) | ... | No | Requires migration / federation / upload |

> Clearly distinguish **physical connections** from Tableau **logical/federated
> groupings** (relationships/noodle model): count physical joins separately from
> logical relationships.

### Data Modeling

| Feature | Count | Classification | Note |
|---|---|---|---|
| Simple aggregations (SUM, AVG, etc.) | ... | ✅ Auto | ... |
| Row-level calculated fields (arithmetic, IF/CASE) | ... | ✅ Auto | ... |
| Measures / dimensions | ... / ... | ✅ Auto | ... |
| Relationships / joins | ... / ... | ✅ Auto | Direct metric-view joins |
| FIXED LODs | ... | ⚠️ Workaround | Precompute in source view |
| INCLUDE / EXCLUDE LODs | ... | 🔧 Manual | Context-dependent redesign |
| Table calculations | ... | ⚠️/🔧 | Window functions where possible |
| Data blending / cross-datasource calcs | ... | 🔧 Manual | ... |
| Parameters / parameterized calcs | ... | ⚠️ Workaround | Dashboard variables |
| Sets / groups / bins | ... | ⚠️ Workaround | CASE bands / precompute |
| Hierarchies | ... | ✅ Auto | ... |
| Field / value-level aliases | ... | ⚠️ Workaround | Map in source or dashboard |
| ... only list features with count > 0 ... |

### Visualizations

| Visual / Mark Type | Count | AI/BI Equivalent | Issues |
|---|---|---|---|
| ... only non-trivial or problematic visuals ... |
| Dual-axis / combined multi-mark | ... | Layered chart | Verify axis sync |
| Maps (filled / symbol / custom geocoding) | ... | Map viz | Custom geocoding = 🔧 |
| KPI / counter (BAN) | ... | Counter | ... |
| Reference lines / bands / annotations | ... | Partial | Some manual |
| Custom / rare marks | ... | — | Manual redesign |

If model-only: use Empty Report Handling callout.

### Interactivity & Filters

| Feature | Count | Status |
|---|---|---|
| Filter controls (quick filters) | ... | ✅/⚠️ |
| Context filters | ... | ⚠️ |
| Cascading / dependent filters | ... | ⚠️/🔧 |
| Dashboard filter actions | ... | ⚠️ |
| Highlight actions | ... | 🔧 |
| URL / navigation / drill actions | ... | 🔧 |
| Parameter actions | ... | 🔧 |
| ... only features present, excluding items in Data Modeling ... |

If model-only: use Empty Report Handling callout.

## Automation Classification

<!-- MANDATORY — do NOT omit this section -->
Classify every Inventory feature into one of three buckets (see Legend in the
skill). The classification reflects `/importBI`'s current capabilities as the
migration execution path — not theoretical possibility. Only classify ✅ or ⚠️
if `/importBI` has a documented, tested pattern for it; otherwise 🔧 Manual.

### Feature Classification

| Feature (from Inventory) | Count | Bucket | /importBI Behavior |
|---|---|---|---|
| ... | ... | ✅/⚠️/🔧 | One-line description of what happens |

### Automation Summary

| Bucket | Features | Calculated fields / LODs / table calcs | % of Calcs |
|---|---|---|---|
| ✅ Auto | ... | ... | ... |
| ⚠️ Auto + workaround | ... | ... | ... |
| 🔧 Manual | ... | ... | ... |

## Automation Uplift with Reference Patterns

<!-- MANDATORY — do NOT omit this section -->
The baseline above reflects what `/importBI` handles today. Some 🔧 Manual items
can be reclassified as ⚠️ Auto + workaround when the migration additionally applies
documented UC semantics patterns from
[uc-semantics-patterns](https://github.com/databricks-solutions/uc-semantics-patterns).
These patterns are UC metric-view recipes (source-agnostic), so Tableau LODs, table
calculations, and blends map onto them directly. This estimates the **additional**
automation achievable beyond `/importBI`'s built-in capabilities.

| 🔧 Feature | Calcs | Applicable Pattern | Reclassified To | Recipe |
|---|---|---|---|---|
| <e.g. YoY/prior-period table calcs> | <n> | Period-over-period growth | ⚠️ Auto + workaround | Explicit prior-period metric-view measures using `window` + `offset` |
| <e.g. Running total / moving avg table calcs> | <n> | Moving calculations / Period-to-date totals | ⚠️ Auto + workaround | `range: period_to_date` / rolling `window` measures |
| <e.g. RANK / INDEX table calcs> | <n> | Ranking | ⚠️ Auto + workaround | `rank` window measure |
| <e.g. FIXED LOD segmentation> | <n> | Static segmentation | ⚠️ Auto + workaround | CASE-band dimension / precomputed metric-view column |
| <e.g. currency-converted measures> | <n> | Currency conversion | ⚠️ Auto + workaround | FX-rate join + converted measure |

**Revised Automation Summary (with patterns)**:

| Bucket | Calcs (baseline) | Calcs (with patterns) | % Baseline | % With Patterns |
|---|---|---|---|---|
| ✅ Auto | ... | ... | ...% | ...% |
| ⚠️ Auto + workaround | ... | ... | ...% | ...% |
| 🔧 Manual | ... | ... | ...% | ...% |

> **Automation uplift**: Applying
> [uc-semantics-patterns](https://github.com/databricks-solutions/uc-semantics-patterns)
> recipes during migration can raise the automatable share from **<baseline>%** to
> **<with-patterns>%** (a **+<delta>pp** improvement), potentially shifting the
> complexity from <baseline rating> to <new rating>.

## Readiness Summary

**Primary blockers** (🔧 only):
- <list>

**Data prerequisites** (Unity Catalog):
- <UC tables/sources that must exist before conversion; extracts to re-point at live sources>

**Semantic-model remediation** (🔧 only, before conversion):
- <LODs/blends/table calcs that must be redesigned before /importBI can process the rest>

**Visualization / interaction redesign** (🔧 visuals/interaction):
- <unsupported visuals, custom geocoding, parameter/highlight/URL actions, analytics objects>

**Recommended next steps**:
1. Resolve prerequisites (connections, parameters, source access, extract → live source)
2. Complete 🔧 Manual items (semantic redesign)
3. Run /importBI for ✅ and ⚠️ items
4. Verify ⚠️ workaround results
5. Build net-new visuals if model-only workbook

### Specific Risks
- <workbook-specific list>

### Validation Checks
- <list of things to verify after conversion>
```

### Template B — Migration Summary Report (produce one overall)

High-level roll-up ONLY. Reference each file by name; never re-inventory features
or repeat an individual report's detailed tables.

```markdown
# Migration Summary Report

**Date scanned**: <date> | **Files**: <count> | **File type(s)**: <.twb / .twbx / .tds / .tdsx>

## Portfolio Totals

| Metric | Count |
|---|---|
| Workbooks | ... |
| Worksheets | ... |
| Dashboards | ... |
| Data sources | ... |
| Calculated fields | ... |
| LOD expressions | ... |
| Table calculations | ... |

## Complexity Distribution

| Complexity | Workbooks | % of Total |
|---|---|---|
| Low | ... | ...% |
| Medium | ... | ...% |
| High | ... | ...% |

**Overall portfolio complexity**: <Low / Medium / High> — <1–2 sentence rationale>

## Per-File Summary

One row per file. Automation % is the ✅ + ⚠️ share of that file's calcs.

| Workbook | File Type | Complexity | Automation % | Top Drivers | Key Blockers |
|---|---|---|---|---|---|
| ... | .twb / .twbx / .tds / .tdsx | Low/Med/High | ...% | ... | ... |

## Cross-Cutting Findings

**Common blockers** (🔧 appearing across multiple files):
- <blocker> — affects <N> workbooks

**Aggregate data prerequisites** (Unity Catalog):
- <UC tables/sources required across the portfolio; extracts to re-point>

**Non-Databricks sources across portfolio**:
- <list or "None">

## Recommended Migration Sequence

1. <e.g. Start with Low-complexity, all-Databricks workbooks (quick wins)>
2. <e.g. Resolve shared prerequisites / source access>
3. <e.g. Tackle Medium workbooks after ⚠️ workarounds validated>
4. <e.g. Plan manual redesign effort for High-complexity workbooks>
```

> **REMINDER**: The markdown above defines the COMPLETE reports. Do NOT add any
> sections beyond what is shown. The Automation Classification section is a
> MANDATORY part of EVERY individual report. If you find yourself writing section
> numbers (## Part 1, ## 1., ## 2.) you are violating the format.

## Automation Classification Legend

Used by the Automation Classification section of every individual report.

- ✅ **Auto** — /importBI converts this with no user intervention.
  (Simple aggregations, arithmetic/IF/CASE calculated fields, live Databricks
  passthrough connections, physical joins, standard chart/mark types, basic
  discrete/continuous filters, hierarchies.)
- ⚠️ **Auto + workaround** — /importBI converts this by applying a known
  workaround automatically (source SQL view, precomputed column, window
  function, decomposition). User should verify but does not build anything
  manually. (FIXED LODs, simple table calcs — running total, percent of total,
  rank — parameters → dashboard variables, static sets/groups/bins, field/value
  aliases, context filters, dual-axis layering.)
- 🔧 **Manual** — /importBI cannot convert this. Must be redesigned after
  automated conversion completes. (INCLUDE/EXCLUDE LODs with nested context,
  data blending / cross-datasource calcs, complex table calcs with custom
  addressing/partitioning, parameter actions, highlight/URL/navigation actions,
  custom geocoding, analytics objects — forecast, cluster, trend/distribution
  bands — sheet swapping / dynamic zone visibility.)

## Complexity Rating Criteria

### Low
- < 5 calculated fields, all simple aggregations / arithmetic
- Single Databricks source (live)
- Standard visuals (bar/line/table), < 3 worksheets, 1 dashboard
- No LODs, table calcs, blends, or actions
- **Expected automation**: 90%+ ✅ Auto

### Medium
- 5–20 calculated fields with FIXED LODs or simple table calcs
- 2–3 sources, some non-Databricks or extracts
- Some dual-axis, context filters, filter/parameter actions
- **Expected automation**: 50–90% ✅ or ⚠️

### High
- 20+ calculated fields with INCLUDE/EXCLUDE LODs, nested LODs, or complex
  table calcs (custom addressing/partitioning)
- Multiple sources needing migration/federation/upload; data blending
- Parameter/highlight/URL/navigation actions, custom geocoding, analytics
  objects (forecast, cluster, trend/reference distributions)
- Sheet swapping / dynamic zone visibility
- **Expected automation**: < 50% ✅ or ⚠️

## Important Guardrails

- **MANDATORY FORMAT**: Use the exact report structures above. Do NOT invent
  your own sections. Do NOT use numbered headings (## Part 1, ## 1., ## 2.).
- **TWO REPORT KINDS**: Always produce an individual report per file AND a single
  Migration Summary Report. The Automation Classification and Automation Uplift
  sections MUST appear in every individual report.
- **CONCISE — NO INDIVIDUAL LISTINGS**: Never list individual calculated-field
  names, individual relationships/joins, or individual LOD/table-calc formulas.
  Always group and count (e.g. "Simple aggregations | 18 | ✅ Auto"). Target
  < 300 lines per individual report; keep the summary shorter still.
- **USE ✅/⚠️/🔧 ONLY**: Do NOT use ❌. The three buckets are:
  ✅ Auto, ⚠️ Auto + workaround, 🔧 Manual.
- **Read-only**: Never convert, create datasets, or create widgets.
- **No duplication**: Each feature in exactly ONE section per Deduplication Rules;
  the summary never re-inventories features.
- **Classification anchored on `/importBI`**: The ✅/⚠️/🔧 buckets reflect what
  the `/importBI` migration agent handles today. Only classify ✅ or ⚠️ if
  `/importBI` has a documented pattern for it. When uncertain, classify 🔧 Manual.
  The Automation Uplift section then shows the delta from applying reference
  patterns on top of `/importBI`'s baseline.
- **No unevidenced claims**: Do not claim AI/BI support or provide an ETA for a
  feature unless it is evidenced by the workbook context or supplied
  documentation. When unsure, mark it 🔧 Manual / Unknown and say so.
- **Tableau terminology**: calculated fields, LOD expressions (FIXED/INCLUDE/
  EXCLUDE), table calculations, marks, worksheets, dashboards, data blending,
  quick filters, context filters, dashboard actions — not Power BI/DAX terms.
- **Tableau only**: This skill is for `.twb` / `.twbx` workbooks and
  `.tds` / `.tdsx` data sources. Power BI files use a different assessment
  framework (`pbi-migration-assessment`).

## Reference Patterns

When classifying 🔧 Manual items, check whether any can be reclassified as
⚠️ Auto + workaround by applying patterns from the
[UC Semantics Patterns](https://github.com/databricks-solutions/uc-semantics-patterns)
reference repository. This repo provides tested, production-ready YAML
templates for UC metric views. The patterns are source-agnostic, so Tableau
LODs, table calculations, and blends map onto them directly.

### Pattern Catalog

| Pattern | Repo Folder | Unlocks Migration Of (Tableau) |
|---|---|---|
| **Period-over-period growth** (YoY, QoQ, MoM, WoW) | `Time Intelligence/Period-over-period growth/` | `LOOKUP`/`ZN(...) - LOOKUP(...)` prior-period table calcs; YoY calculated fields |
| **Period-to-date totals** (YTD, QTD, MTD) | `Time Intelligence/Period-to-date totals/` | `RUNNING_SUM` within date partitions; YTD/MTD table calcs |
| **Period-to-date growth** (YOYTD, QOQTD) | `Time Intelligence/Period-to-date growth/` | Combined period-to-date + prior-period table calcs |
| **Moving calculations** (rolling 7d, 1m, 1q, 1y) | `Time Intelligence/Moving calculations/` | `WINDOW_AVG` / `WINDOW_SUM` rolling table calcs |
| **Semi-additive calculations** (first/last date, opening/closing balance) | `Semi-additive calculations/` | `LAST()`/`FIRST()`-based balance snapshots; inventory levels |
| **Ranking** (RANK, DENSE_RANK, NTILE, PERCENT_RANK) | `Ranking/` | `RANK`, `INDEX`, `RANK_DENSE`, `RANK_PERCENTILE` table calcs |
| **Static segmentation** (CASE bands, config-table bands) | `Static segmentation/` | Static `IF`/`CASE` groups, bins, and FIXED-LOD segmentation |
| **Currency conversion** (FX rates, multi-currency) | `Currency conversion/` | Multi-currency calculated fields with FX-rate blends |

### LOD Decomposition Recipe

LOD expressions are the most common high-impact Tableau blocker. Map them by type:

1. **FIXED LODs** — precompute the fixed-grain aggregate as a metric-view
   dimension-level measure or a source SQL view column. These become
   ⚠️ Auto + workaround (Static segmentation pattern where the FIXED result
   drives a band/classification).
2. **INCLUDE LODs** — often expressible as a finer-grain measure aggregated up;
   evaluate case-by-case. Frequently ⚠️ with a source view, sometimes 🔧.
3. **EXCLUDE LODs** — depend on removing dimensions from the viz context;
   these are context-sensitive and usually 🔧 Manual (redesign as explicit
   partitioned window measures where the partition is known).

### Table-Calculation Recipe

Table calculations map onto UC metric-view **window functions**:

- `RUNNING_SUM` / `RUNNING_AVG` → `window` cumulative measures (Period-to-date).
- `WINDOW_SUM` / `WINDOW_AVG` over N rows → rolling `window` measures (Moving calculations).
- `LOOKUP(..., -1)` prior-period → `offset` window measures (Period-over-period).
- `RANK` / `INDEX` → `rank` window measures (Ranking).
- Custom addressing/partitioning that does not map to a fixed partition → 🔧 Manual.

### How to Use in the Report

In each individual report, after the baseline Automation Summary, always include
an **Automation Uplift** section that:
1. Lists each 🔧 item that has a matching pattern from the catalog above.
2. States the reclassified bucket and the recipe name.
3. Shows a revised Automation Summary table (baseline vs. with-patterns).
4. Calculates the percentage-point uplift and whether it changes the
   complexity rating.
5. Links to the repo: `https://github.com/databricks-solutions/uc-semantics-patterns`
