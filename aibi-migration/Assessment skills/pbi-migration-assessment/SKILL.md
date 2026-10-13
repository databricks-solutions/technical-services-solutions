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
what `/importBI` reports it can handle. The **Automation Uplift** section then shows how
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
> The only exception is the optional **🔧 Manual Adjustment Report** (Step 6),
> produced on user request after the main report.
>
> **SOURCE-OF-TRUTH RULE — NO HALLUCINATION**: Every ✅/⚠️/🔧 bucket and every
> "/importBI Behavior", "handling", or "resolution" cell MUST come from what
> `/importBI` actually returned in the Step 3 profile. Never infer, assume, or
> invent a `/importBI` capability. If `/importBI` did not state how it handles
> an item, write `Not stated by /importBI — verify` and classify it 🔧 Manual.
> The ONLY other allowed source is the
> [uc-semantics-patterns](https://github.com/databricks-solutions/uc-semantics-patterns)
> repo, used ONLY in the Automation Uplift section and read live (see
> Reference Patterns).

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
- **Non-Databricks sources**: Flag every M-query source other than
  `Databricks.Catalogs` / `Databricks.Query` (e.g. `Sql.Database`,
  `PowerPlatform.Dataflows`, `Excel.Workbook`, `Web.Contents`, `SharePoint.*`).
  Name each source type; these require data migration or federation.
- **M-query transformations**: Classify each M query into one of:
  - **Direct navigation** — source + table navigation only, no transforms
  - **Databricks + transforms** — any step beyond navigation (filters, added /
    removed / renamed columns, type changes, merges, pivots, grouping, etc.)
  - **Non-Databricks source** — as above
  - **Dependent query** — references another query (`Table.NestedJoin`,
    `Table.Join`, `Table.Combine`, `Table.Append`, or a direct reference to
    another query name)
- **Query dependencies**: Record which queries use which. **Never mark a query
  as omittable (e.g. "Omit or materialize") if another query references it.**
- **Source table inventory**: List UC schema.table references so the user can
  verify accessibility.

### Step 3 — Profile Each Report

For each Power BI file, hand off to the `/importBI` migration specialist on a
**temporary or existing dashboard** with a `continueMessage` that:
- Begins with `/importBI`
- Explicitly states: **"Profile only — do NOT convert. Return the full analysis
  of data sources, data model, DAX measures, visualizations, filters, and
  interactivity. Do not create any datasets or widgets."**
- Asks `/importBI` to state **how it would handle each item** for:
  - M queries with transformations and dependent queries
  - Relationships, grouped by pattern: standard M:1 active, inactive
    (USERELATIONSHIP), bidirectional, M:M, date table on the many side,
    fact-to-fact links, joins on differently named columns, disconnected
    tables (slicer helpers / TREATAS targets)
  - Calculated columns and calculated tables
  - Cross-table measures — distinguishing fact ÷ dimension from fact ÷ fact
  - Measures it cannot convert, with the measure name and the blocking DAX
    construct (needed for the optional Manual Adjustment Report)
  - Unused measures (not referenced by any visual or other measure)
- Includes the file name or path

Process files sequentially (one `/importBI` handoff per file). Collect the
analysis output from each before proceeding to the next. Keep it — it is the
only source for classifications and handling text.

> **Hard constraint**: Do NOT allow the specialist to create datasets, widgets,
> or perform any conversion. This is a read-only assessment.

### Step 4 — Consolidate

After all files are profiled, consolidate findings into the report structure
defined below. Before Step 5, read the uc-semantics-patterns repo live to build
the Automation Uplift section (see Reference Patterns).

### Step 5 — Consistency Check (mandatory, before printing)

Silently verify the drafted report. Fix every mismatch before printing; do not
print the check itself.

1. ✅ + ⚠️ + 🔧 measure counts = total DAX measures − unused measures.
2. Each count is identical everywhere it appears (header metrics, Inventory,
   Feature Classification, Automation Summary, Uplift baseline, Per-Workbook).
3. No calculated column or calculated table is counted in any measure count.
4. Every 🔧 item named in the Readiness Summary appears in the Feature
   Classification table.
5. The Uplift "Measures (baseline)" column equals the Automation Summary.
6. A measure that falls into several 🔧 categories is counted **once**, under
   its primary (most blocking) category. Add a note to that row in the Feature
   Classification table: "n measures also involve <other category>".
7. Every bucket and every handling / resolution cell traces to the `/importBI`
   output, or (Uplift only) to a cited uc-semantics-patterns folder. Anything
   else → replace with `Not stated by /importBI — verify` and 🔧.

Then return the full report in the chat.

### Step 6 — Offer Manual Adjustment Report

After printing the main report, ask the user:

> "Do you want a detailed 🔧 Manual Adjustment Report listing the measures
> that need manual work?"

Only if the user agrees, produce the report using the
[Manual Adjustment Report Structure](#manual-adjustment-report-structure).

If the user already requested the Manual Adjustment Report (or a detailed list
of manual measures) in the initial prompt, skip the question and print it
directly after the main report.

## Deduplication Rules

Each fact or feature appears in exactly ONE place. Never describe the same item
in multiple sections:

1. **Executive Overview** names each complexity driver once with count and brief
   resolution. No full technical detail — that belongs in the Inventory.
2. **Inventory** is the single detailed listing. Each feature lives in exactly
   one sub-section:
   - M-query transformations and dependencies → Prerequisites / M-Query
     Transformations only
   - Relationships → Relationships only
   - Calculated columns / tables → Calculated Columns & Tables only (never in
     Data Modeling or measure counts)
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
etc.). Do NOT add sections like "Fact-Domain Grouping" or "Source Views Needed"
— those details belong INSIDE the tables below. Relationship details go ONLY in
the grouped Relationships table.

**Anti-patterns (DO NOT do these)**:
- ❌ Listing individual measure names (e.g. "`SUM of FTE`, `SUM of FTE paid`…")
  in the main report
- ❌ Listing individual relationship edges one by one
- ❌ Listing individual calculated columns with full DAX expressions
- ❌ Using ✅/⚠️/❌ — use ✅/⚠️/🔧 (Auto / Auto+workaround / Manual)
- ❌ Writing handling / resolution text that `/importBI` did not state
- ❌ Producing > 400 lines of output
- ❌ Omitting the Automation Classification or Automation Uplift sections

**Correct patterns** (formatting illustrations only — not statements of what
`/importBI` supports):
- ✅ "Simple aggregations (SUM, COUNT, etc.) | 18 | ✅ Auto"
- ✅ "Relationships (M:1, active) | 13 | ✅ Auto | <handling as stated by /importBI>"
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
| Unused measures | ... |
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

### M-Query Transformations

| Query Type | Count | Depends on / Used by | /importBI Handling |
|---|---|---|---|
| Direct navigation | ... | ... | <as stated by /importBI> |
| Databricks + transforms | ... | ... | <as stated by /importBI> |
| Dependent query (NestedJoin / Combine / reference) | ... | <query → query> | <as stated by /importBI> |

Queries referenced by another query are never omittable.

### Non-Databricks Sources

<source type + count per type, or "None — all sources are Databricks">

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
| Databricks.Catalogs (passthrough) | ... | Yes | ... |
| Databricks.Catalogs (M-transforms) | ... | Yes | ... |
| Calculated / DATATABLE | ... | Abstraction | ... (never omit if referenced) |
| Non-Databricks | ... | No | Requires migration / federation |

### Relationships

| Pattern | Count | Bucket | /importBI Resolution |
|---|---|---|---|
| Standard M:1, active | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| Inactive (USERELATIONSHIP) | ... | ... | ... |
| Bidirectional | ... | ... | ... |
| M:M | ... | ... | ... |
| Date table on the many side | ... | ... | ... |
| Fact-to-fact links | ... | ... | ... |
| Joins on differently named columns | ... | ... | ... |
| Disconnected tables (slicer helpers / TREATAS) | ... | ... | ... |

Only list patterns with count > 0.

### Data Modeling

DAX measures only — calculated columns go in the next table.

| Feature | Count | Classification | Note |
|---|---|---|---|
| Simple aggregations (SUM, COUNT, etc.) | ... | ✅/⚠️/🔧 | ... |
| Cross-table: fact ÷ dimension | ... | ✅/⚠️/🔧 | ... |
| Cross-table: fact ÷ fact | ... | ⚠️/🔧 (never ✅) | ... |
| Calculation groups | ... | ✅/⚠️/🔧 | ... |
| ... only list features with count > 0 ... |

### Calculated Columns & Tables

| Pattern | Count | Bucket | /importBI Handling |
|---|---|---|---|
| ... | ... | ✅/⚠️/🔧 | <as stated by /importBI> |

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
three buckets. **The baseline classification reflects what `/importBI`
reported in the Step 3 profile** — not theoretical possibility and not
assumptions. Only classify ✅ or ⚠️ if `/importBI` stated it handles the item.

### Legend

- ✅ **Auto** — /importBI stated it converts this with no user intervention.
- ⚠️ **Auto + workaround** — /importBI stated it converts this by applying a
  workaround automatically (e.g. a source view, derived column, or
  decomposition). User should verify but does not build anything manually.
- 🔧 **Manual** — /importBI cannot convert this, or did not state how it
  would. Must be redesigned after automated conversion completes.

**Cross-table measures** — always split into two cases:
- **Fact ÷ dimension** — the dimension is joinable to the fact in one metric
  view. Bucket as reported by /importBI.
- **Fact ÷ fact** — each side must be aggregated separately to a shared grain
  (e.g. a pre-aggregated view or two metric views), then divided. Bucket as
  reported by /importBI, **capped at ⚠️** (never ✅). 🔧 if there is no shared
  conformed dimension. Describe the approach only as /importBI suggested it;
  otherwise reference a uc-semantics-patterns recipe in the Uplift section.

### Feature Classification

| Feature (from Inventory) | Count | Bucket | /importBI Behavior |
|---|---|---|---|
| ... | ... | ✅/⚠️/🔧 | One line, as stated by /importBI (or "Not stated by /importBI — verify") |

If a 🔧 measure belongs to several 🔧 categories, it is counted once under its
primary category, with a note: "n measures also involve <other category>".

### Automation Summary

| Bucket | Features | Measures | % of Measures |
|---|---|---|---|
| ✅ Auto | ... | ... | ... |
| ⚠️ Auto + workaround | ... | ... | ... |
| 🔧 Manual | ... | ... | ... |

**Unused measures (excluded)**: <n>
**Calculated columns / tables (not in measure %)**: ✅ <n> / ⚠️ <n> / 🔧 <n>

## Automation Uplift with Reference Patterns

<!-- MANDATORY — do NOT omit this section -->
The baseline above reflects what **`/importBI` reported**. Some 🔧 Manual
items can be reclassified as ⚠️ Auto + workaround when the migration
additionally applies documented UC semantics patterns from
[uc-semantics-patterns](https://github.com/databricks-solutions/uc-semantics-patterns),
read live at each run.

| 🔧 Feature | Measures | Applicable Pattern | Reclassified To | Recipe |
|---|---|---|---|---|
| <🔧 feature from Classification> | <n> | <pattern name from repo> | ⚠️ Auto + workaround | <repo folder / recipe, short description> |

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
| Calculated Columns | ... | ... | ... |
| Visuals | ... | ... | ... |

**Risks**: <workbook-specific only>
**Validation**: <workbook-specific only>
```

> **REMINDER**: The markdown above is the COMPLETE report. Do NOT add any
> sections beyond what is shown. The Automation Classification and Automation
> Uplift sections are MANDATORY parts of EVERY report. If you find yourself
> writing section numbers (## 1., ## 2., etc.) you are violating the format.

## Manual Adjustment Report Structure

Produced ONLY after the user accepts the Step 6 offer. This is the only place
where individual measure names are listed.

- One `###` group per 🔧 feature, using the **same group names and order** as
  the Feature Classification table and Readiness Summary.
- Each measure appears once, under its primary category (same rule as
  Step 5 check 6); mention other involved categories in the Reason.
- Reasons come from the `/importBI` output — the blocking DAX constructs it
  reported.

```markdown
# 🔧 Manual Adjustment Report

## <🔧 Feature group name> — <n> measures

| Measure | Table | Workbook (multi only) | Reason |
|---|---|---|---|
| Matrix Display | <table> | <workbook> | TREATAS on literals + ISINSCOPE + FORMAT text |

## <next 🔧 group> — <n> measures
...

**Consistency**: <total> measures listed = 🔧 Manual measures in the Automation
Summary (<n>); group counts match the Feature Classification table.
```

Before printing, verify that every group count equals the 🔧 count for that
feature in the main report and that the total equals the 🔧 Manual measure
count. If they differ, fix the discrepancy (and say which report was
corrected) before printing.

## Complexity Rating Criteria

The "Expected automation" values are rough guidance for rating complexity —
they do not describe actual `/importBI` behavior.

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
- RLS/OLS, bidirectional filtering, M:M relationships, fact-to-fact links
- **Expected automation**: < 50% ✅ or ⚠️

## Important Guardrails

- **MANDATORY FORMAT**: Use the exact report structure above. Do NOT invent
  your own sections. Do NOT use numbered headings (## 1., ## 2.).
- **MANDATORY SECTIONS**: Automation Classification and Automation Uplift
  with Reference Patterns MUST appear in every report.
- **CONCISE — NO INDIVIDUAL LISTINGS**: Never list individual measure names,
  individual relationship edges, or individual calculated column DAX
  expressions in the main report. Always group and count (e.g. "Simple
  aggregations | 18 | ✅ Auto"). Target < 300 lines of output. Measure names
  appear only in the opt-in Manual Adjustment Report (Step 6).
- **USE ✅/⚠️/🔧 ONLY**: Do NOT use ❌. The three buckets are:
  ✅ Auto, ⚠️ Auto + workaround, 🔧 Manual.
- **Read-only**: Never convert, create datasets, or create widgets.
- **No duplication**: Each feature in exactly ONE section per Deduplication Rules.
- **No hallucination — `/importBI` is the source of truth**: Buckets and
  handling text come only from the `/importBI` profile output. When
  `/importBI` did not state handling, write `Not stated by /importBI — verify`
  and classify 🔧 Manual. The only exception is uc-semantics-patterns, used in
  the Automation Uplift section.
- **Never omit referenced queries**: A query used by another query (merge,
  append, reference) is never marked omittable.
- **Calculated columns are not measures**: Keep them in their own block and
  out of every measure count.
- **Consistency check is mandatory**: Run Step 5 before printing every report.
- **Power BI terminology**: DAX, measures, slicers, Power Query / M — not
  Tableau terms.
- **Power BI only**: This skill is for `.pbit` files. Tableau files use a
  different assessment framework.

## Reference Patterns

Do NOT rely on a remembered or cached pattern list — the repo is updated over
time. At **each run**:

1. Read the root `README.md` of
   `https://github.com/databricks-solutions/uc-semantics-patterns`.
2. Follow its links to the pattern folders and read the recipe for any pattern
   that may match a 🔧 item (e.g. calculation groups, semi-additive measures,
   fact ÷ fact ratios, ranking, segmentation).
3. Match 🔧 items to patterns only by what the current repo content documents.
   Cite the folder / recipe name in the Recipe column.

If the repo cannot be read, keep the Automation Uplift section with this line
instead of the table and revised summary:
"Pattern repo unavailable — uplift not computed; baseline applies."

### How to Use in the Report

After the baseline Automation Summary, always include an **Automation Uplift**
section that:
1. Lists each 🔧 item that has a matching pattern from the repo.
2. States the reclassified bucket and the recipe name.
3. Shows a revised Automation Summary table (baseline vs. with-patterns).
4. Calculates the percentage-point uplift and whether it changes the
   complexity rating.
5. Links to the repo: `https://github.com/databricks-solutions/uc-semantics-patterns`
