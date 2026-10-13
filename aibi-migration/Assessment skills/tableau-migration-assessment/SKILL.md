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
It produces, for a batch of files, **one single Migration Report**. That one report
**opens with a Migration Summary Report** (a high-level cross-file roll-up —
**Template A**) and is **followed by the individual per-file report details**
(one Individual Workbook Report section per file — **Template B**). The **automation
estimate is anchored to the `/importBI` migration agent** — the intended execution
path for Tableau → Databricks AI/BI conversions. Every ✅/⚠️/🔧 classification reflects
what `/importBI` reports it can handle. The **Automation Uplift** section in each individual
report section then shows how applying
[uc-semantics-patterns](https://github.com/databricks-solutions/uc-semantics-patterns)
recipes during migration can raise the automatable share further.

The reports focus on blockers, frictions, and the auto vs. manual split — without
performing any conversion.

> **CRITICAL — MANDATORY REPORT FORMAT**: You MUST produce the report using the
> EXACT section headings and table structures defined in the "Report Structure"
> section below. Do NOT invent your own numbered sections (Part 1, Part 2, 1, 2, 3…),
> do NOT add sections not in the template, and do NOT omit required sections.
> The Automation Classification and Automation Uplift sections are MANDATORY in
> every individual report section. Violation of this format makes the report unusable.
>
> **ONE REPORT, SUMMARY FIRST**: Produce a SINGLE Migration Report. It MUST begin
> with ONE **Migration Summary Report** (Template A — the high-level cross-file
> roll-up), and that is **followed by** one **Individual Workbook Report** section
> per file (Template B — the detailed per-file analysis). Summary first, then the
> individual details. Never fold individual detail into the summary, and never make
> the summary the only output.
>
> **CONCISENESS RULE**: Reports must be SHORT. Summarize counts by category
> (e.g. "Simple aggregations (SUM, AVG, etc.) | 18 | ✅ Auto"). NEVER list
> individual calculated-field names, and NEVER list individual relationships or
> joins one by one — group and count. The only exception is the optional
> **🔧 Manual Adjustment Report** (Step 6), produced on user request after the
> main report.
>
> **SOURCE-OF-TRUTH RULE — NO HALLUCINATION**: Every ✅/⚠️/🔧 bucket and every
> "/importBI Behavior", "handling", or "resolution" cell MUST come from what
> `/importBI` actually returned in the Step 3 profile. Never infer, assume, or
> invent a `/importBI` capability. If `/importBI` did not state how it handles an
> item, write `Not stated by /importBI — verify` and classify it 🔧 Manual.
> The ONLY other allowed source is the
> [uc-semantics-patterns](https://github.com/databricks-solutions/uc-semantics-patterns)
> repo, used ONLY in the Automation Uplift section and read live (see
> Reference Patterns).

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
  connections requiring data migration, federation, or upload. For each
  non-Databricks source, also capture its **in-source transformation logic** —
  custom SQL / Initial SQL, unions, cross-database joins, pivots, and data-source
  filters — because that logic must be rebuilt as a UC source view, not just the
  connection. (This is Tableau's equivalent of a Power Query / M dataflow; profile
  it, do not improvise a count.)
- **Source dependency rule**: NEVER mark a data source as unused or omittable if
  anything references it — a worksheet, a data blend (as primary or secondary), a
  dashboard action, a parameter, or another (published) data source that is built
  on it. Only a source referenced by nothing is omittable.
- **Extracts (.hyper)**: Flag `.hyper` extracts — they are point-in-time snapshots;
  AI/BI dashboards query live UC data, so extracts are informational only and the
  underlying live source must be identified.
- **Source table inventory**: List UC schema.table references (and non-UC tables)
  so the user can verify accessibility.
- **Relationship / join quality flags**: Do not just count relationships — flag the
  ones that need attention: data sources / tables with **no relationship at all**
  (disconnected — usually blend helpers or parameter-driven), **fact-to-fact**
  relationships or blends, relationships/joins on **differently named or mismatched
  key fields** (join calculations), **many-to-many** relationships, and any
  non-default **cardinality / referential-integrity** overrides. Report each as a
  flagged count, not a silent zero.

### Step 3 — Profile Each File

For each Tableau file, hand off to the `/importBI` migration specialist on a
**temporary or existing dashboard** with a `continueMessage` that:
- Begins with `/importBI`
- Explicitly states: **"Profile only — do NOT convert. Return the full analysis
  of data sources, data model, calculated fields, LOD expressions, table
  calculations, visualizations, filters, and interactivity. Do not create any
  datasets or widgets."**
- Asks `/importBI` to state **how it would handle each item** for:
  - data-source transformations (custom SQL / Initial SQL, unions, cross-DB
    joins, pivots, data-source filters) and dependent sources
  - relationships, grouped by pattern: physical joins (M:1), logical
    relationships (noodle model), many-to-many, date table on the many side,
    fact-to-fact relationships / blends, data blends (primary / secondary links),
    joins on differently named / mismatched keys (join calculations), disconnected
    sources (blend helpers / parameter-driven), and cardinality /
    referential-integrity overrides
  - row-level (non-aggregate) calculated fields, groups, bins, and sets
  - cross-datasource / blend ratios — distinguishing fact ÷ dimension from
    fact ÷ fact
  - calculated fields / LODs / table calcs it cannot convert, with the name and
    the blocking construct (needed for the optional Manual Adjustment Report)
  - unused / disabled calcs (not referenced by any worksheet or other calc)
- Includes the file name or path

**Parallelize when more than one file is present — if the environment supports
it.** If the volume (or attachment set) contains **2 or more** files **and Genie
Code can run concurrent `/importBI` handoffs**, profile them in **parallel batches
of up to 4 files at a time**: dispatch one profiling task per file (each an
independent `/importBI` handoff) as concurrent subagents, up to 4 running at once.
When a batch finishes, start the next batch until all files are profiled. If
concurrent handoffs are **not** supported in the current environment, **fall back
to sequential profiling** — one `/importBI` handoff per file, collecting each
file's analysis before the next (as the Power BI skill does). Either way, every
file's handoff must carry the same read-only, profile-only `continueMessage` above
(including the "state how you handle each item" asks), and all results must be
collected before producing the reports. The profile output is the only source for
classifications and handling text — keep it.

If **only one** file is present, profile it directly with a single `/importBI`
handoff (no batching needed).

> **Hard constraint**: Do NOT allow any specialist or subagent to create datasets,
> widgets, or perform any conversion. This is a read-only assessment, whether run
> sequentially or in parallel.

### Step 4 — Consolidate

After all files are profiled, consolidate findings into the report structure
defined below. Before Step 5, read the uc-semantics-patterns repo live to build
the Automation Uplift section (see Reference Patterns).

Produce ONE single Migration Report, in this order:

1. **First**, ONE **Migration Summary Report** (Template A) that summarizes every
   file at a high level (no re-inventory of features).
2. **Then**, for EACH file, a self-contained **Individual Workbook Report** section
   (Template B) appended after the summary.

### Step 5 — Consistency Check (mandatory, before printing)

Silently verify the drafted report. Fix every mismatch before printing; do not
print the check itself.

1. The three bucket counts (✅ + ⚠️ + 🔧) **equal the file's classified calc total**
   — aggregate calculated fields + LOD expressions + table calculations +
   cross-datasource ratio calcs — **minus** the unused / disabled calcs. Row-level
   calcs, groups, bins, and sets are NOT part of this total (they are counted in
   their own block, per check #3).
2. Every count is **identical everywhere it appears** (the file's header metrics
   table, Feature Inventory, Feature Classification, Automation Summary, Uplift
   baseline, and the summary's Per-File roll-up).
3. **No dimension or plain (non-calculated) field is counted as a calc**, a calc is
   never double-counted as both a measure and a dimension, and **no row-level calc,
   group, bin, set, parameter, alias, or hierarchy is counted in the calc %** (they
   live in their own block or are flagged as model features).
4. On every run, the **grouped 🔧 counts in the Readiness Summary reconcile with the
   🔧 rows in the Feature Classification table** (same categories, same counts).
   **When** the 🔧 Manual Adjustment Report is produced (Step 6), every 🔧 item it
   names also appears in the Feature Classification table (and vice versa) and its
   per-group counts match. Do NOT require named items on runs where the Manual
   Adjustment Report was not produced.
5. The Uplift **"Calcs (baseline)"** column equals the Automation Summary.
6. **Portfolio Totals in the summary equal the sum of the per-file counts**, and
   each Per-File Summary **"Automation %"** equals that file's Template B
   Automation Summary.
7. A calc that falls into **several 🔧 categories** is counted **once**, under its
   primary (most blocking) category, with a note in the Feature Classification
   row: "n calcs also involve <other category>".
8. The **Unused / disabled calcs** row appears in the Template B header metrics
   and in Template A Portfolio Totals — never silently dropped.
9. Every bucket and every handling / resolution cell **traces to the `/importBI`
   output**, or (Uplift only) to a cited uc-semantics-patterns folder. Anything
   else → replace with `Not stated by /importBI — verify` and 🔧.

Then return the full report in the chat: the summary first, then the individual
per-file detail sections.

### Step 6 — Offer Manual Adjustment Report

After printing the main report, ask the user:

> "Do you want a detailed 🔧 Manual Adjustment Report listing the calculated
> fields / LODs / table calcs that need manual work?"

Only if the user agrees, produce the report using the
[Manual Adjustment Report Structure](#manual-adjustment-report-structure).

If the user already requested the Manual Adjustment Report (or a detailed list of
manual items) in the initial prompt, skip the question and print it directly after
the main report.

## Deduplication Rules

Each fact or feature appears in exactly ONE place.

**Within an individual report:**
1. **Executive Overview** names each complexity driver once with count and brief
   resolution. No full technical detail — that belongs in the Inventory.
2. **Feature Inventory** is the single detailed listing. Each feature lives in
   exactly one sub-section:
   - Data-source transformations and dependencies → Prerequisites / Data Source
     Transformations only
   - Relationships / joins / blends → the grouped Relationships table only
   - LOD expressions, table calcs, aggregate calcs → Data Modeling only
   - Row-level calculated fields, groups, bins, sets → Row-level Calculations
     block only (never in Data Modeling or the calc counts)
   - Quick filters / filter controls → Filters only (not also Interactivity)
   - Dashboard actions (filter/highlight/URL/navigation/parameter) → Interactivity only
3. **Automation Classification** references Inventory rows by feature name and
   adds the auto/manual column — no re-description.

**Across the report's sections:**
4. The **Migration Summary Report** (the opening section) contains ONLY high-level
   cross-file roll-ups and one-line-per-file summaries. It NEVER re-inventories
   features or repeats an individual report section's tables — it references each
   file by name.

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
add sections like "Fact-Domain Grouping" — those details belong INSIDE the tables
below. Relationship details go ONLY in the grouped **Relationships** table; do not
add a separate "Relationship Analysis" narrative section.

**Anti-patterns (DO NOT do these)**:
- ❌ Listing individual ✅ Auto / ⚠️ workaround calculated-field names (group and count those)
- ❌ Listing individual relationships/joins one by one
- ❌ Listing individual LOD expressions with full formula text
- ❌ Using ✅/⚠️/❌ — use ✅/⚠️/🔧 (Auto / Auto+workaround / Manual)
- ❌ Writing handling / resolution text that `/importBI` did not state
- ❌ Producing > 400 lines per individual report
- ❌ Omitting the Automation Classification or Automation Uplift sections from an individual report section
- ❌ Skipping the per-file individual detail sections and returning only the summary
- ❌ Putting the individual detail sections before the Migration Summary Report (summary MUST come first)

**Correct patterns** (formatting illustrations only — not statements of what
`/importBI` supports):
- ✅ "Simple aggregations (SUM, AVG, etc.) | 18 | ✅ Auto"
- ✅ "Relationships (physical joins, M:1) | 13 | ✅ Auto | <resolution as stated by /importBI>"
- ✅ "INCLUDE/EXCLUDE LODs | 6 | 🔧 Manual | <as stated by /importBI>"

### Template A — Migration Summary Report (produce one, FIRST)

This is the opening section of the single report. High-level roll-up ONLY.
Reference each file by name; never re-inventory features or repeat an individual
report section's detailed tables.

```markdown
# Migration Report

## Migration Summary Report

**Date scanned**: <date> | **Files**: <count> | **File type(s)**: <.twb / .twbx / .tds / .tdsx>

### Portfolio Totals

| Metric | Count |
|---|---|
| Workbooks | ... |
| Worksheets | ... |
| Dashboards | ... |
| Data sources | ... |
| Aggregate calcs | ... |
| Row-level calcs / groups / bins / sets | ... |
| LOD expressions | ... |
| Table calculations | ... |
| Unused / disabled calcs | ... |

### Complexity Distribution

| Complexity | Workbooks | % of Total |
|---|---|---|
| Low | ... | ...% |
| Medium | ... | ...% |
| High | ... | ...% |

**Overall portfolio complexity**: <Low / Medium / High> — <1–2 sentence rationale>

### Per-File Summary

One row per file. Automation % is the ✅ + ⚠️ share of that file's **classified
calc total** (aggregate calcs + LOD expressions + table calculations +
cross-datasource ratio calcs; excludes unused/disabled calcs and the row-level
calcs / groups / bins / sets block) — the same denominator as that file's
Template B Automation Summary **% of Calcs**.

| Workbook | File Type | Complexity | Automation % | Top Drivers | Key Blockers |
|---|---|---|---|---|---|
| ... | .twb / .twbx / .tds / .tdsx | Low/Med/High | ...% | ... | ... |

### Cross-Cutting Findings

**Common blockers** (🔧 appearing across multiple files):
- <blocker> — affects <N> workbooks

**Aggregate data prerequisites** (Unity Catalog):
- <UC tables/sources required across the portfolio; extracts to re-point>

**Non-Databricks sources across portfolio**:
- <source type + count per type, or "None">

### Recommended Migration Sequence

1. <e.g. Start with Low-complexity, all-Databricks workbooks (quick wins)>
2. <e.g. Resolve shared prerequisites / source access>
3. <e.g. Tackle Medium workbooks after ⚠️ workarounds validated>
4. <e.g. Plan manual redesign effort for High-complexity workbooks>
```

### Template B — Individual Workbook Report (produce one section per file, AFTER the summary)

One per file, appended after the Migration Summary Report above.

```markdown
## Migration Assessment Report — <Workbook Name>

**Date scanned**: <date> | **Source path**: <path> | **File type**: <.twb / .twbx / .tds / .tdsx>

| Metric | Count |
|---|---|
| Worksheets | ... |
| Dashboards | ... |
| Data sources | ... |
| Physical data connections | ... |
| Aggregate calcs | ... |
| Row-level calcs / groups / bins / sets | ... |
| LOD expressions | ... |
| Table calculations | ... |
| Unused / disabled calcs | ... |

### Prerequisites

#### Connections & Parameters

| Connection / Parameter | Status | Action |
|---|---|---|
| catalog (workbook parameter) | Unresolved | Resolve to concrete catalog |
| .hyper extract | Point-in-time | Informational — identify live source |

#### Source Tables

| Schema.Table | Used By | Accessible |
|---|---|---|
| catalog.schema.table | Orders (data source) | To verify |

#### Data Source Transformations

| Source type | Count | Depends on / Used by | /importBI Handling |
|---|---|---|---|
| Direct connection (no transforms) | ... | ... | <as stated by /importBI> |
| Databricks + custom SQL / Initial SQL / transforms | ... | ... | <as stated by /importBI> |
| Non-Databricks source | ... | ... | <as stated by /importBI> |
| Dependent source (published source built on another, union, cross-DB join, blend secondary, or referenced by a parameter / action) | ... | <source → source> | <as stated by /importBI> |

A source referenced by anything (worksheet, blend, action, parameter, or dependent
published source) is never omittable.

#### Non-Databricks Sources

<source type + count per type, or "None — all sources are Databricks">

### Executive Overview

**Complexity**: <Low / Medium / High>

**Rationale**: <2–3 sentences>

#### Complexity Drivers (ranked by impact)

| # | Driver | Count | Impact | Resolution |
|---|---|---|---|---|
| 1 | ... | ... | 🔴/🟠/🟡 | ... |

### Feature Inventory

Each feature appears ONCE. Only list features that have non-zero occurrences.

#### Data Sources

| Connection Type | Count | Databricks? | Migration Impact |
|---|---|---|---|
| Databricks (live, passthrough) | ... | Yes | <as stated by /importBI> |
| Databricks (with custom SQL / transforms) | ... | Yes | <as stated by /importBI> |
| Extract (.hyper) | ... | Depends | <as stated by /importBI> |
| Non-Databricks (SQL Server, Excel, etc.) | ... | No | <as stated by /importBI> |

> Clearly distinguish **physical connections** from Tableau **logical/federated
> groupings** (relationships/noodle model): count physical joins separately from
> logical relationships.

#### Relationships

Counts only — never list individual joins. Only list patterns with count > 0.

| Pattern | Count | Bucket | /importBI Resolution |
|---|---|---|---|
| Physical joins (M:1) | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| Logical relationships (noodle model) | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| Many-to-many | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| Date table on the many side | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| Fact-to-fact relationships / blends | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| Data blends (primary / secondary links) | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| Joins on differently named / mismatched keys (join calculations) | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| Disconnected sources (blend helpers / parameter-driven) | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| Cardinality / referential-integrity overrides | ... | ✅/⚠️/🔧 | <as stated by /importBI> |

#### Data Modeling

The **calc rows** here — simple aggregations, LOD expressions, table calculations,
and cross-datasource ratio calcs — are the ones counted in the ✅/⚠️/🔧 **calc
total** that Step 5 reconciles. The **model-feature rows** (parameters, field/value
aliases, hierarchies) are classified for migration effort but are **NOT** in the
calc % — mark each `model feature — not in calc %` in the Note. Row-level calcs,
groups, bins, and sets go in the next block, also outside the calc %.

| Feature | Count | Classification | Note |
|---|---|---|---|
| Simple aggregations (SUM, AVG, etc.) | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| FIXED LODs | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| INCLUDE / EXCLUDE LODs | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| Table calculations | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| Cross-datasource calc — fact ÷ dimension/lookup | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| Cross-datasource calc — fact ÷ fact (blend) | ... | ⚠️/🔧 (never ✅) | <as stated by /importBI> |
| Parameters | ... | ✅/⚠️/🔧 | model feature — not in calc %; <as stated by /importBI> |
| Field / value-level aliases | ... | ✅/⚠️/🔧 | model feature — not in calc %; <as stated by /importBI> |
| Hierarchies | ... | ✅/⚠️/🔧 | model feature — not in calc %; <as stated by /importBI> |
| ... only list features with count > 0 ... |

#### Row-level Calculations, Groups, Bins & Sets

Row-level (non-aggregate) calculated fields, groups, bins, and sets. These are NOT
counted in the calc % — they are reported on their own line in the Automation
Summary.

| Pattern | Count | Bucket | /importBI Handling |
|---|---|---|---|
| Row-level calculated fields (arithmetic, IF/CASE, string/date) | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| Groups | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| Bins | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| Sets | ... | ✅/⚠️/🔧 | <as stated by /importBI> |

#### Visualizations

| Visual / Mark Type | Count | AI/BI Equivalent | Issues |
|---|---|---|---|
| ... only non-trivial or problematic visuals ... |
| Dual-axis / combined multi-mark | ... | <as stated by /importBI> | <as stated by /importBI> |
| Maps (filled / symbol / custom geocoding) | ... | <as stated by /importBI> | <as stated by /importBI> |
| KPI / counter (BAN) | ... | <as stated by /importBI> | <as stated by /importBI> |
| Reference lines / bands / annotations | ... | <as stated by /importBI> | <as stated by /importBI> |
| Custom / rare marks | ... | <as stated by /importBI> | <as stated by /importBI> |

If model-only: use Empty Report Handling callout.

#### Interactivity & Filters

| Feature | Count | Status |
|---|---|---|
| Filter controls (quick filters) | ... | ✅/⚠️/🔧 |
| Context filters | ... | ✅/⚠️/🔧 |
| Cascading / dependent filters | ... | ✅/⚠️/🔧 |
| Dashboard filter actions | ... | ✅/⚠️/🔧 |
| Highlight actions | ... | ✅/⚠️/🔧 |
| URL / navigation / drill actions | ... | ✅/⚠️/🔧 |
| Parameter actions | ... | ✅/⚠️/🔧 |
| ... only features present, excluding items in Data Modeling ... |

If model-only: use Empty Report Handling callout.

### Automation Classification

<!-- MANDATORY — do NOT omit this section -->
Classify every Inventory feature into one of three buckets (see the Automation
Classification Legend in the skill). **The baseline classification reflects what
`/importBI` reported in the Step 3 profile** — not theoretical possibility and not
assumptions. Only classify ✅ or ⚠️ if `/importBI` stated it handles the item;
otherwise 🔧 Manual with `Not stated by /importBI — verify`.

#### Feature Classification

| Feature (from Inventory) | Count | Bucket | /importBI Behavior |
|---|---|---|---|
| ... | ... | ✅/⚠️/🔧 | One line, as stated by /importBI (or "Not stated by /importBI — verify") |

If a 🔧 calc belongs to several 🔧 categories, it is counted once under its
primary category, with a note: "n calcs also involve <other category>".

#### Automation Summary

| Bucket | Features | Calculated fields / LODs / table calcs | % of Calcs |
|---|---|---|---|
| ✅ Auto | ... | ... | ... |
| ⚠️ Auto + workaround | ... | ... | ... |
| 🔧 Manual | ... | ... | ... |

**% of Calcs** = bucket calcs ÷ the classified calc total (aggregate calcs + LOD
expressions + table calculations + cross-datasource ratio calcs; excludes the two
lines below). This denominator is the same one the Per-File Summary uses.

**Unused / disabled calcs (excluded)**: <n>
**Row-level calcs, groups, bins & sets (not in calc %)**: ✅ <n> / ⚠️ <n> / 🔧 <n>

### Automation Uplift with Reference Patterns

<!-- MANDATORY — do NOT omit this section -->
The baseline above reflects what **`/importBI` reported**. Some 🔧 Manual items
can be reclassified as ⚠️ Auto + workaround when the migration additionally applies
documented UC semantics patterns from
[uc-semantics-patterns](https://github.com/databricks-solutions/uc-semantics-patterns),
read live at each run. These patterns are UC metric-view recipes (source-agnostic),
so Tableau LODs, table calculations, and blends map onto them directly. This
estimates the **additional** automation achievable beyond `/importBI`'s baseline.

| 🔧 Feature | Calcs | Applicable Pattern | Reclassified To | Recipe |
|---|---|---|---|---|
| <🔧 feature from Classification> | <n> | <pattern name from repo> | ⚠️ Auto + workaround | <repo folder / recipe, short description> |

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

If the pattern repo cannot be read, keep this section with the single line
"Pattern repo unavailable — uplift not computed; baseline applies." instead of the
tables above.

### Readiness Summary

**Primary blockers** (🔧 only):
- <list>

**Data prerequisites** (Unity Catalog):
- <UC tables/sources that must exist before conversion; extracts to re-point at live sources>

**Semantic-model remediation** (🔧 only, before conversion):
- <grouped 🔧 blockers by category with counts — e.g. "EXCLUDE LODs with nested context — 4", "fact ÷ fact blends — 2">
- Names of each 🔧 item are available in the optional 🔧 Manual Adjustment Report (Step 6).

**Visualization / interaction redesign** (🔧 visuals/interaction):
- <unsupported visuals, custom geocoding, parameter/highlight/URL actions, analytics objects>

**Recommended next steps**:
1. Resolve prerequisites (connections, parameters, source access, extract → live source)
2. Complete 🔧 Manual items (semantic redesign)
3. Run /importBI for ✅ and ⚠️ items
4. Verify ⚠️ workaround results
5. Build net-new visuals if model-only workbook

#### Specific Risks
- <workbook-specific list>

#### Validation Checks
- <list of things to verify after conversion>
```

> **REMINDER**: The markdown above defines the COMPLETE reports. Do NOT add any
> sections beyond what is shown. The Automation Classification section is a
> MANDATORY part of EVERY individual report. If you find yourself writing section
> numbers (## Part 1, ## 1., ## 2.) you are violating the format.

## Manual Adjustment Report Structure

Produced ONLY after the user accepts the Step 6 offer (or asked for it up front).
This is the only place where individual 🔧 item names are listed.

- One `###` group per 🔧 feature, using the **same group names and order** as the
  Feature Classification table and Readiness Summary.
- Each item appears once, under its primary category (same rule as Step 5 check 7);
  mention other involved categories in the Reason.
- Reasons come from the `/importBI` output — the blocking construct it reported.
- List **all** 🔧 items — there is no top-N cap in this report.

```markdown
# 🔧 Manual Adjustment Report

## <🔧 Feature group name> — <n> items

| Calculated field / LOD / table calc | Data source | Workbook (multi only) | Reason |
|---|---|---|---|
| `Profit Ratio` | Orders | Sales.twbx | Cross-datasource blend (fact ÷ fact) — aggregate each side then divide |

## <next 🔧 group> — <n> items
...

**Consistency**: <total> items listed = 🔧 Manual calcs in the Automation Summary
(<n>); group counts match the Feature Classification table (per file, and in the
portfolio total for multi-file runs).
```

Before printing, verify that every group count equals the 🔧 count for that feature
in the main report and that the total equals the 🔧 Manual calc count. If they
differ, fix the discrepancy (and say which report was corrected) before printing.

## Automation Classification Legend

Used by the Automation Classification section of every individual report. These are
bucket **definitions** only — the actual bucket for any feature comes from the
`/importBI` profile, never from this list.

- ✅ **Auto** — /importBI stated it converts this with no user intervention.
- ⚠️ **Auto + workaround** — /importBI stated it converts this by applying a known
  workaround automatically (source SQL view, precomputed column, window function,
  decomposition). User should verify but does not build anything manually.
- 🔧 **Manual** — /importBI cannot convert this, or did not state how it would.
  Must be redesigned after automated conversion completes.

**Cross-datasource / blend ratios** — always split into two cases:
- **Fact ÷ dimension / lookup** — the secondary source is a lookup joinable to the
  fact on a shared key (rates, targets, attributes). Bucket as reported by
  `/importBI`.
- **Fact ÷ fact** — a direct join fans out the rows and gives the wrong ratio. Each
  side must be **aggregated separately to a shared grain** (a pre-aggregated source
  view, or two metric views at that grain), **then divided**. Bucket as reported by
  `/importBI`, **capped at ⚠️** (never ✅); 🔧 if there is no shared conformed
  dimension. Never advise "just join them in the metric view". Describe the approach
  only as `/importBI` suggested it; otherwise reference a uc-semantics-patterns
  recipe in the Uplift section.

## Complexity Rating Criteria

The "Expected automation" values below are rough guidance for rating complexity —
they do **not** describe actual `/importBI` behavior.

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
- **ONE REPORT, SUMMARY FIRST**: Always produce a SINGLE Migration Report that
  OPENS with the Migration Summary Report (Template A) and is FOLLOWED by one
  Individual Workbook Report section per file (Template B). The Automation
  Classification and Automation Uplift sections MUST appear in every individual
  report section.
- **CONCISE — GROUP, DON'T NAME, IN THE MAIN REPORT**: Never list individual
  calculated-field names or relationship/join formulas — group and count
  (e.g. "Simple aggregations | 18 | ✅ Auto"). Individual 🔧 item names appear
  only in the opt-in **🔧 Manual Adjustment Report** (Step 6). Target < 300 lines
  per individual report.
- **SOURCE OF TRUTH — `/importBI`**: Every bucket and every handling / resolution
  cell comes only from the `/importBI` profile output. When `/importBI` did not
  state handling, write `Not stated by /importBI — verify` and classify 🔧 Manual.
  The only exception is uc-semantics-patterns, used in the Automation Uplift
  section and read live.
- **CONSISTENCY CHECK IS MANDATORY**: Run the Step 5 consistency check (silently)
  before printing every report.
- **ROW-LEVEL CALCS / GROUPS / BINS / SETS AND UNUSED CALCS ARE NOT IN THE CALC %**:
  keep them in their own block / lines and out of the ✅/⚠️/🔧 calc counts.
- **CROSS-DATASOURCE RATIOS SPLIT**: Always split fact ÷ dimension from fact ÷ fact;
  cap fact ÷ fact at ⚠️ (never ✅), 🔧 when there is no shared conformed dimension.
- **SOURCE DEPENDENCIES**: Capture each non-Databricks source's transformation logic
  (custom SQL, unions, cross-DB joins, data-source filters) as a source view to
  rebuild, and never mark a data source omittable if a worksheet, blend, action,
  parameter, or dependent published source references it.
- **USE ✅/⚠️/🔧 ONLY**: Do NOT use ❌. The three buckets are:
  ✅ Auto, ⚠️ Auto + workaround, 🔧 Manual.
- **Read-only**: Never convert, create datasets, or create widgets — this applies
  to parallel subagents too.
- **No duplication**: Each feature in exactly ONE section per Deduplication Rules;
  the summary never re-inventories features.
- **No unevidenced claims**: Do not claim AI/BI support or provide an ETA for a
  feature unless `/importBI` stated it or it is supplied documentation. When
  unsure, mark it 🔧 Manual / Unknown and say so.
- **Tableau terminology**: calculated fields, LOD expressions (FIXED/INCLUDE/
  EXCLUDE), table calculations, marks, worksheets, dashboards, data blending,
  quick filters, context filters, dashboard actions — not Power BI/DAX terms.
- **Tableau only**: This skill is for `.twb` / `.twbx` workbooks and
  `.tds` / `.tdsx` data sources. Power BI files use a different assessment
  framework (`pbi-migration-assessment`).

## Reference Patterns

Do NOT rely on a remembered or cached pattern list — the repo is updated over time.
At **each run**, read the
[uc-semantics-patterns](https://github.com/databricks-solutions/uc-semantics-patterns)
repository live and match 🔧 items to it by its current content only:

1. Read the root `README.md` of
   `https://github.com/databricks-solutions/uc-semantics-patterns`.
2. Follow its links to the pattern folders and read the recipe for any pattern
   that may match a 🔧 item (e.g. period-over-period growth, period-to-date totals,
   moving calculations, semi-additive calculations, ranking, static segmentation,
   currency conversion, fact ÷ fact ratios). These are source-agnostic UC
   metric-view recipes, so Tableau LODs, table calculations, and blends map onto
   them directly.
3. Match 🔧 items to patterns only by what the current repo content documents.
   Cite the folder / recipe name in the Recipe column.

If the repo cannot be read, keep the Automation Uplift section with this line
instead of the table and revised summary:
"Pattern repo unavailable — uplift not computed; baseline applies."

### How to Use in the Report

In each individual report, after the baseline Automation Summary, always include
an **Automation Uplift** section that:
1. Lists each 🔧 item that has a matching pattern from the repo.
2. States the reclassified bucket and the recipe name.
3. Shows a revised Automation Summary table (baseline vs. with-patterns).
4. Calculates the percentage-point uplift and whether it changes the
   complexity rating.
5. Links to the repo: `https://github.com/databricks-solutions/uc-semantics-patterns`
