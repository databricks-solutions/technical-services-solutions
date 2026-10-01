---
name: pbi-migration-assessment
description: >
  Bulk profiling and migration-readiness assessment for Power BI reports (.pbit files)
  before converting them to Databricks AI/BI dashboards. Load this skill when the user
  asks to assess, profile, audit, or evaluate Power BI reports for migration complexity,
  or when bulk-importing Power BI files from a Unity Catalog Volume.
---

# Power BI Migration Assessment Skill

This skill guides a **read-only profiling pass** over one or more Power BI report files.
It produces a concise Migration Assessment Report whose **baseline automation estimate
is anchored to the `/importBI` migration agent** — the intended execution path for
Power BI → Databricks AI/BI conversions. Every ✅/⚠️/🔧 classification reflects
what `/importBI` can handle today. The **Automation Uplift** section then shows how
applying [uc-semantics-patterns](https://github.com/databricks-solutions/uc-semantics-patterns)
recipes during migration can raise the automatable share further.

The report focuses on blockers, frictions, and the auto vs. manual split — without
performing any conversion.

> **CRITICAL — MANDATORY REPORT FORMAT**: You MUST produce the report using the
> EXACT section headings and table structures defined in the "Report Structure"
> section below. Do NOT invent your own numbered sections (1, 2, 3…), do NOT
> add sections not in the template, and do NOT omit required sections.
> The Automation Classification and Automation Uplift sections are MANDATORY.
> Violation of this format makes the report unusable.
>
> **CONCISENESS RULE**: The report must be SHORT. Summarize counts by category
> (e.g. "Simple aggregations (SUM, COUNT, etc.) | 18 | ✅ Auto"). NEVER list
> individual measure names — no measure-by-measure listings. NEVER list
> individual relationship edges one by one. Group and count.

## When to Use

- User attaches one or more `.pbit` files and asks to assess or profile them
- User points to a UC Volume path containing Power BI files and asks for bulk assessment
- User asks about migration complexity, blockers, or readiness for Power BI → AI/BI migration

## Workflow

### Step 1 — Enumerate Files

If the user provides a Volume path (e.g. `/Volumes/catalog/schema/volume/`):
1. List all `.pbit` files in that path
2. Report the count and file names before proceeding
3. If no Power BI files are found, inform the user and stop

If the user attaches files directly, use those.

### Step 2 — Prerequisites Check

Before profiling, scan M-queries and flag blocking prerequisites:

- **M-query parameters**: List all parameters (`Databricks_ServerHostname`,
  `Databricks_HttpPath`, `Databricks_Catalog`, `RangeStart`, `RangeEnd`, etc.).
  Flag which must resolve to concrete values before conversion. `RangeStart` /
  `RangeEnd` (incremental refresh) are informational only — metric views query
  live UC data.
- **Non-Databricks sources**: Flag any `Sql.Database`, `PowerPlatform.Dataflows`,
  or other non-Databricks M-query sources requiring data migration or federation.
- **Source table inventory**: List UC schema.table references so the user can
  verify accessibility.

### Step 3 — Profile Each Report

For each Power BI file, hand off to the `/importBI` migration specialist on a
**temporary or existing dashboard** with a `continueMessage` that:
- Begins with `/importBI`
- Explicitly states: **"Profile only — do NOT convert. Return the full analysis
  of data sources, data model, DAX measures, visualizations, filters, and
  interactivity. Do not create any datasets or widgets."**
- Includes the file name or path

Process files sequentially (one `/importBI` handoff per file). Collect the
analysis output from each before proceeding to the next.

> **Hard constraint**: Do NOT allow the specialist to create datasets, widgets,
> or perform any conversion. This is a read-only assessment.

### Step 4 — Consolidate and Report

After all files are profiled, consolidate findings into the report structure
defined below. Return the full report in the chat.

## Deduplication Rules

Each fact or feature appears in exactly ONE place. Never describe the same item
in multiple sections:

1. **Executive Overview** names each complexity driver once with count and brief
   resolution. No full technical detail — that belongs in the Inventory.
2. **Inventory** is the single detailed listing. Each feature lives in exactly
   one sub-section:
   - Calculation groups, field parameters, RLS → Data Modeling only
   - Slicers → Filters only (not also Interactivity)
   - Bookmarks → Interactivity only
3. **Automation Classification** references Inventory rows by feature name and
   adds the auto/manual column — no re-description.
4. **Per-Workbook Detail** (multi-workbook only) contains ONLY workbook-specific
   risks and validation checks, referencing Inventory rows by name.
5. **Single-workbook shortcut**: When one workbook is analyzed, omit the
   per-workbook section entirely. Append "Specific Risks" and "Validation
   Checks" under the Readiness Summary.

## Empty Report Handling

When a `.pbit` has **0 visuals**, collapse Visualizations, Interactivity, and
Filters into one callout:

> **Model-only template** — this `.pbit` contains a semantic model with no
> report visuals, slicers, bookmarks, or filters. The dashboard must be
> designed from scratch after conversion. Visual/interaction inventory is N/A.

Do NOT print empty tables for each section.

## Report Structure

**You MUST use the EXACT headings and tables below.** This is not an example
— it is the mandatory output format. Copy the heading hierarchy verbatim.
Do NOT use numbered sections (## 1. Model Overview, ## 2. Table Classification,
etc.). Do NOT add sections like "Fact-Domain Grouping", "Source Views Needed",
or "Relationship Analysis" — those details belong INSIDE the tables below.

**Anti-patterns (DO NOT do these)**:
- ❌ Listing individual measure names (e.g. "`SUM of FTE`, `SUM of FTE paid`…")
- ❌ Listing individual relationship edges one by one
- ❌ Listing individual calculated columns with full DAX expressions
- ❌ Using ✅/⚠️/❌ — use ✅/⚠️/🔧 (Auto / Auto+workaround / Manual)
- ❌ Producing > 400 lines of output
- ❌ Omitting the Automation Classification or Automation Uplift sections

**Correct patterns**:
- ✅ "Simple aggregations (SUM, COUNT, etc.) | 18 | ✅ Auto"
- ✅ "Relationships (M:1, active) | 13 | ✅ Auto | Direct metric-view joins"
- ✅ "CF_ conditional formatting (calc group dependent) | 29 | 🔧 Manual"

Produce the report in this structure:

```markdown
# Migration Assessment Report

**Date scanned**: <date> | **Files**: <count>

| Metric | Count |
|---|---|
| Workbooks | ... |
| Pages | ... |
| Fact / Dimension tables | ... / ... |
| Physical data sources | ... |
| DAX measures | ... |
| Calculated columns / tables | ... / ... |
| Calculation groups | ... |

## Prerequisites

### M-Query Parameters

| Parameter | Status | Action |
|---|---|---|
| Databricks_Catalog | Unresolved | Resolve to concrete catalog |
| RangeStart / RangeEnd | Incremental refresh | Informational — not used in metric views |

### Source Tables

| UC Schema.Table | Used By | Accessible |
|---|---|---|
| catalog.schema.table | F_FactTable | To verify |

### Non-Databricks Sources

<list or "None — all sources are Databricks">

## Executive Overview

### Per-Workbook Summary (if multiple)

| Workbook | Complexity | Top Factors |
|---|---|---|
| ... | Low / Medium / High | ... |

**Overall Complexity**: <Low / Medium / High>

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
| Databricks.Catalogs (passthrough) | ... | Yes | No migration needed |
| Databricks.Catalogs (M-transforms) | ... | Yes | Source view needed |
| Calculated / DATATABLE | ... | Abstraction | Omit or materialize |
| Non-Databricks | ... | No | Requires migration / federation |

### Data Modeling

| Feature | Count | Classification | Note |
|---|---|---|---|
| Simple aggregations (SUM, COUNT, etc.) | ... | ✅ Auto | ... |
| CALCULATE + dimension filter | ... | ✅ Auto | ... |
| Calculation groups | ... | 🔧 Manual | ... |
| ... only list features with count > 0 ... |

### Visualizations

| Visual Type | Count | AI/BI Equivalent | Issues |
|---|---|---|---|
| ... only non-trivial or problematic visuals ... |

If model-only: use Empty Report Handling callout.

### Interactivity & Filters

| Feature | Count | Status |
|---|---|---|
| ... only features present in the model, excluding items in Data Modeling ... |

If model-only: use Empty Report Handling callout.

## Automation Classification

<!-- MANDATORY — do NOT omit this section -->
This is the key decision table. Classify every Inventory feature into one of
three buckets. **The baseline classification reflects `/importBI`'s current
capabilities as the migration execution path** — not theoretical possibility.
Only classify ✅ or ⚠️ if `/importBI` has a documented, tested pattern for it.

### Legend

- ✅ **Auto** — /importBI converts this with no user intervention.
  (Simple aggregations, DIVIDE, TOTALYTD, SAMEPERIODLASTYEAR, CALCULATE with
  dimension filters, passthrough M-queries, standard chart types.)
- ⚠️ **Auto + workaround** — /importBI converts this by applying a known
  workaround automatically (source SQL view, derived column, decomposition).
  User should verify but does not build anything manually.
  (M-query row/column filters, AVERAGEX over VALUES(dim), SUMX row products,
  LASTNONBLANK, simple REMOVEFILTERS, field parameters → dashboard variables.)
- 🔧 **Manual** — /importBI cannot convert this. Must be redesigned after
  automated conversion completes.
  (Calculation groups, RLS/USERPRINCIPALNAME, ISINSCOPE/ISFILTERED, general
  ALL/ALLSELECTED, bidirectional cross-filtering, composite models, custom
  visuals, USERNAME, dynamic FORMAT text.)

### Feature Classification

| Feature (from Inventory) | Count | Bucket | /importBI Behavior |
|---|---|---|---|
| ... | ... | ✅/⚠️/🔧 | One-line description of what happens |

### Automation Summary

| Bucket | Features | Measures | % of Measures |
|---|---|---|---|
| ✅ Auto | ... | ... | ... |
| ⚠️ Auto + workaround | ... | ... | ... |
| 🔧 Manual | ... | ... | ... |

## Automation Uplift with Reference Patterns

<!-- MANDATORY — do NOT omit this section -->
The baseline above reflects what **`/importBI` handles today**. Some 🔧 Manual
items can be reclassified as ⚠️ Auto + workaround when the migration
additionally applies documented UC semantics patterns from
[uc-semantics-patterns](https://github.com/databricks-solutions/uc-semantics-patterns).
This section estimates the **additional** automation achievable beyond
`/importBI`'s built-in capabilities.

| 🔧 Feature | Measures | Applicable Pattern | Reclassified To | Recipe |
|---|---|---|---|---|
| <e.g. Calculation groups (CY/PY/YTD)> | <n> | Period-over-period growth / Period-to-date totals | ⚠️ Auto + workaround | Decompose into explicit CY/PY/YTD metric-view measures using `window` + `offset` |
| <e.g. CF_ conditional formatting> | <n> | (dependent on calc group decomposition) | ⚠️ Omit | Presentation logic; dashboard-layer formatting replaces these after decomposition |
| <e.g. LASTNONBLANK> | <n> | Semi-additive calculations | ⚠️ Auto + workaround | `semiadditive: last` window measure |

**Revised Automation Summary (with patterns)**:

| Bucket | Measures (baseline) | Measures (with patterns) | % Baseline | % With Patterns |
|---|---|---|---|---|
| ✅ Auto | ... | ... | ...% | ...% |
| ⚠️ Auto + workaround | ... | ... | ...% | ...% |
| 🔧 Manual | ... | ... | ...% | ...% |

> **Automation uplift**: Applying
> [uc-semantics-patterns](https://github.com/databricks-solutions/uc-semantics-patterns)
> recipes during migration can raise the automatable share from **<baseline>%** to
> **<with-patterns>%** (a **+<delta>pp** improvement), potentially shifting the
> overall complexity from <baseline rating> to <new rating>.

## Readiness Summary

**Primary blockers** (🔧 only):
- <list>

**Data prerequisites**:
- <UC tables/sources that must exist before conversion>

**Pre-conversion remediation** (🔧 only):
- <what must be redesigned before /importBI can process the rest>

**Post-conversion manual work** (🔧 visuals/interaction):
- <unsupported visuals, custom visuals, complex interactivity>

**Recommended next steps**:
1. Resolve prerequisites (parameters, source access)
2. Complete 🔧 Manual items
3. Run /importBI for ✅ and ⚠️ items
4. Verify ⚠️ workaround results
5. Build net-new visuals if model-only template

### Specific Risks
- <list — for single-workbook runs, place here>

### Validation Checks
- <list of things to verify after conversion — for single-workbook runs, place here>

## Per-Workbook Detail (multi-workbook only)

Omit entirely for single-workbook runs.

For each workbook:

### <Workbook Name>
- **Complexity**: Low / Medium / High
- **Key drivers**: <reference Inventory feature names — do NOT re-inventory>

| Category | ✅ Auto | ⚠️ Workaround | 🔧 Manual |
|---|---|---|---|
| Data Sources | ... | ... | ... |
| Data Model | ... | ... | ... |
| Visuals | ... | ... | ... |

**Risks**: <workbook-specific only>
**Validation**: <workbook-specific only>
```

> **REMINDER**: The markdown above is the COMPLETE report. Do NOT add any
> sections beyond what is shown. The Automation Classification and Automation
> Uplift sections are MANDATORY parts of EVERY report. If you find yourself
> writing section numbers (## 1., ## 2., etc.) you are violating the format.

## Complexity Rating Criteria

### Low
- < 5 DAX measures, all simple aggregations
- Single Databricks source
- Standard visuals, < 3 pages
- No calc tables, RLS, composite models
- **Expected automation**: 90%+ ✅ Auto

### Medium
- 5–20 DAX measures with time intelligence or CALCULATE filters
- 2–3 sources, some non-Databricks
- Some formatting, drill-through, bookmarks
- **Expected automation**: 50–90% ✅ or ⚠️

### High
- 20+ DAX measures with iterators, context transition, or calc groups
- Multiple sources needing migration/federation
- Composite models, DirectQuery, custom visuals
- RLS/OLS, bidirectional filtering, M:M relationships
- **Expected automation**: < 50% ✅ or ⚠️

## Important Guardrails

- **MANDATORY FORMAT**: Use the exact report structure above. Do NOT invent
  your own sections. Do NOT use numbered headings (## 1., ## 2.).
- **MANDATORY SECTIONS**: Automation Classification and Automation Uplift
  with Reference Patterns MUST appear in every report.
- **CONCISE — NO INDIVIDUAL LISTINGS**: Never list individual measure names,
  individual relationship edges, or individual calculated column DAX
  expressions. Always group and count (e.g. "Simple aggregations | 18 |
  ✅ Auto"). Target < 300 lines of output.
- **USE ✅/⚠️/🔧 ONLY**: Do NOT use ❌. The three buckets are:
  ✅ Auto, ⚠️ Auto + workaround, 🔧 Manual.
- **Read-only**: Never convert, create datasets, or create widgets.
- **No duplication**: Each feature in exactly ONE section per Deduplication Rules.
- **Classification anchored on `/importBI`**: The ✅/⚠️/🔧 buckets reflect what
  the `/importBI` migration agent handles today. Only classify ✅ or ⚠️ if
  `/importBI` has a documented pattern for it. When uncertain, classify
  🔧 Manual. The Automation Uplift section then shows the delta from applying
  reference patterns on top of `/importBI`'s baseline.
- **Power BI terminology**: DAX, measures, slicers, Power Query / M — not
  Tableau terms.
- **Power BI only**: This skill is for `.pbit` files. Tableau files use a
  different assessment framework.

## Reference Patterns

When classifying 🔧 Manual items, check whether any can be reclassified as
⚠️ Auto + workaround by applying patterns from the
[UC Semantics Patterns](https://github.com/databricks-solutions/uc-semantics-patterns)
reference repository. This repo provides tested, production-ready YAML
templates for UC metric views.

### Pattern Catalog

| Pattern | Repo Folder | Unlocks Migration Of |
|---|---|---|
| **Period-over-period growth** (YoY, QoQ, MoM, WoW) | `Time Intelligence/Period-over-period growth/` | `SAMEPERIODLASTYEAR`, `DATEADD`, `PARALLELPERIOD`; **Calculation group CY/PY decomposition** |
| **Period-to-date totals** (YTD, QTD, MTD) | `Time Intelligence/Period-to-date totals/` | `TOTALYTD/QTD/MTD`, `DATESYTD`; **Calculation group YTD decomposition** |
| **Period-to-date growth** (YOYTD, QOQTD) | `Time Intelligence/Period-to-date growth/` | Combined period-to-date + prior-period comparison |
| **Moving calculations** (rolling 7d, 1m, 1q, 1y) | `Time Intelligence/Moving calculations/` | `DATESINPERIOD`, `DATESBETWEEN` rolling averages |
| **Semi-additive calculations** (first/last date, opening/closing balance) | `Semi-additive calculations/` | `LASTNONBLANK`, `FIRSTNONBLANK`, `CLOSINGBALANCEMONTH`; **inventory/balance snapshots** |
| **Ranking** (RANK, DENSE_RANK, NTILE, PERCENT_RANK) | `Ranking/` | `RANKX`, `TOPN` |
| **Static segmentation** (CASE bands, config-table bands) | `Static segmentation/` | Static SWITCH/IF dimension classifications |
| **Currency conversion** (FX rates, multi-currency) | `Currency conversion/` | Multi-currency CALCULATE patterns |

### Calculation Group Decomposition Recipe

Calculation groups are the most common high-impact 🔧 blocker. When a calc
group applies time-intelligence variants (CY, PY, YTD) across KPIs, it can
be decomposed using the Period-over-period and Period-to-date patterns:

1. **Identify calc group items** — read `CG_<Name>` columns (e.g. `Formula`:
   CY, PY, YTD) and their ordinals.
2. **For each base KPI measure**, generate explicit metric-view variants:
   - **CY** (current year): the base measure as-is (no window needed).
   - **PY** (previous year): apply `semiadditive: last` + `offset: -1 year`
     per the Period-over-period pattern.
   - **YTD** (year-to-date): apply `range: period_to_date year` per the
     Period-to-date pattern.
3. **Omit CF_ conditional-formatting measures** — these read
   `SELECTEDVALUE(CG_<Name>[Ordinal])` to conditionally show/hide KPIs per
   calc-group selection. After decomposition, CY/PY/YTD are separate
   measures; the dashboard controls visibility directly. These measures
   become dashboard-layer formatting rules, not metric-view measures.
4. **Wire the dashboard** — the CY/PY/YTD variants replace the calc-group
   slicer. A dashboard variable or separate visual columns display each
   variant.

This recipe typically reclassifies the calc group itself + all dependent
CF_ measures from 🔧 Manual to ⚠️ Auto + workaround.

### Semi-Additive Recipe (LASTNONBLANK)

Power BI `LASTNONBLANK` measures (e.g. "remaining vacation days as of last
available date") map directly to:

```yaml
- name: RemainingBalance
  expr: SUM(remaining_days)
  window:
    - order: Date
      range: current
      semiadditive: last
```

This is a direct ⚠️ workaround — no manual redesign needed.

### How to Use in the Report

After the baseline Automation Summary, always include an **Automation Uplift**
section that:
1. Lists each 🔧 item that has a matching pattern from the catalog above.
2. States the reclassified bucket and the recipe name.
3. Shows a revised Automation Summary table (baseline vs. with-patterns).
4. Calculates the percentage-point uplift and whether it changes the
   complexity rating.
5. Links to the repo: `https://github.com/databricks-solutions/uc-semantics-patterns`
