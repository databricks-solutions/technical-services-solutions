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

This skill runs a **read-only profiling pass** over one or more Tableau files
— workbooks (`.twb` / `.twbx`) and data sources (`.tds` / `.tdsx`) — and
produces a concise Migration Assessment Report. Every ✅/⚠️/🔧 classification is
anchored to what the `/importBI` migration agent reports it can handle; the
**Automation Uplift** shows how
[uc-semantics-patterns](https://github.com/databricks-solutions/uc-semantics-patterns)
recipes can raise the Auto with review share further. Bulk runs (2+ files) open
with a **Migration Summary Report** followed by one **Individual Report** per
file (compact for 6+ files). Nothing is converted.

## Rules

> **CRITICAL** — these rules apply to every run. Breaking them makes the report
> unusable.

1. **Exact format.** Use the exact headings and tables in
   [Report Structure](#report-structure). No numbered sections (`## Part 1`,
   `## 1.`), no extra sections, no omitted sections. Summary first, then the
   Individual Reports — never only the summary, and never individual detail
   folded into the summary.
2. **Mandatory sections.** Automation Classification, Automation Summary, and
   Automation Uplift (with the Revised Automation Summary when there is an
   uplift) appear in **every**
   Individual Report, full or compact — never only at portfolio level. In bulk
   runs the Migration Summary Report also has its Automation Uplift section.
3. **`/importBI` is the source of truth — no hallucination.** Every ✅/⚠️/🔧
   bucket and every handling / behavior / resolution cell comes from the
   `/importBI` profile. If it did not state how it handles an item, write
   `Not stated by /importBI — verify` and classify it 🔧. The only other source
   is uc-semantics-patterns, used only in Automation Uplift (see
   [Reference Patterns](#reference-patterns)). Facts read from the workbook /
   data-source XML (field lists, calc formulas and references) are allowed;
   classifications are not.
4. **Concise — group and count.** Never list individual calculated-field
   names, relationships / joins, or LOD formula text in the main report (write
   "Simple aggregations (SUM, AVG, etc.) | 18 | ✅ Auto"). 🔧 item names appear
   only in the 🔧 Manual Adjustment Report. Limits: ≤ 300 lines per full
   Individual Report, ≤ 25 per compact one, ≤ 150 for the Migration Summary
   Report. Never shorten a report beyond the compact form.
5. **✅/⚠️/🔧 only** — never ❌. See [Buckets](#buckets).
6. **One pass.** Profile every file in one turn (in parallel batches where
   supported — Step 3). Between the Step 1 file count and the final report,
   print only `Profiled <i>/<n> — <file name>` per file. Never print a profile
   or a per-file report while profiling, and never stop to ask the user to
   "continue" or confirm the next file.
7. **Read-only.** Never convert, create datasets, or create widgets — this
   applies to every `/importBI` handoff and parallel subagent.
8. **Counting Rules everywhere.** Calc populations, rates, root 🔧 calcs,
   calculation families, and shared data sources follow
   [Counting Rules](#counting-rules).
9. **Source dependencies.** Never mark a data source unused or omittable if
   anything references it — a worksheet, a data blend (primary or secondary), a
   dashboard action, a parameter, or another (published) data source built on
   it. Only a source referenced by nothing is omittable.
10. **Checks are mandatory.** Run Step 5 before printing every report, and the
    Manual Adjustment check before every Manual Adjustment Report.
11. **No unevidenced claims.** Do not claim AI/BI support or give an ETA for a
    feature unless `/importBI` stated it or it is supplied documentation. When
    unsure, mark it 🔧 Manual / Unknown and say so.
12. **Tableau only.** Use Tableau terms (calculated fields, LOD expressions,
    table calculations, marks, worksheets, dashboards, data blending, quick
    filters, context filters, dashboard actions). Power BI files use a separate
    skill.

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
  connection. Profile it; do not improvise a count.
- **Source dependencies**: Record which sources use which (see Rule 9).
- **Extracts (.hyper) — live connection vs. extract**: For every data source, state
  explicitly whether it is a **live connection** or a **`.hyper` extract**. Extracts
  are point-in-time snapshots; AI/BI dashboards query live UC data, so extracts are
  informational only and the underlying live source must be identified. Never assume
  an extract's embedded connection is the live source without confirming it.
- **Custom SQL target vs. connection catalog/schema**: When a source uses Custom SQL
  or Initial SQL, check the `FROM` target (catalog.schema.table) **against the
  connection's catalog/schema**. A mismatch (SQL reads from a different catalog/schema
  than the connection points at) is a prerequisite to resolve before conversion —
  flag it; do not silently trust the connection metadata.
- **Trailing-space / near-duplicate aliases**: Flag field or value aliases that differ
  only by trailing/leading whitespace or case (e.g. `"Region"` vs `"Region "`). They
  silently split groups and break joins after conversion — report them, do not
  normalize them away.
- **Embedded parameter sources**: Flag sources that are embedded or driven by a
  workbook parameter (parameter-selected tables, parameter-in-Custom-SQL). These must
  resolve to a concrete source before conversion.
- **Parameters datasource is NOT data blending**: Tableau's special *Parameters*
  pseudo-datasource is a container for parameter controls, not a data source. Never
  count it as a blend, a secondary source, or a relationship — exclude it from the
  Relationships and Data Source tables.
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

- begins with `/importBI` and includes the file name or path;
- states: **"Profile only — do NOT convert. Do not create any datasets or
  widgets."**;
- asks `/importBI` to state how it would handle **every field of the
  [Profile Digest](#profile-digest)** — grouped and counted, using the
  [Calculation Families](#calculation-families) names, one-line handling per
  row, no prose — and in particular:
  - data-source transformations (custom SQL / Initial SQL, unions, cross-DB
    joins, pivots, data-source filters) and dependent sources;
  - relationships by pattern: physical joins (M:1), logical relationships
    (noodle model), many-to-many, date table on the many side, fact-to-fact
    relationships / blends, data blends (primary / secondary links), joins on
    differently named / mismatched keys (join calculations), disconnected
    sources (blend helpers / parameter-driven), and cardinality /
    referential-integrity overrides;
  - row-level (non-aggregate) calculated fields, groups, bins, and sets;
  - cross-datasource / blend ratios, split fact ÷ dimension vs fact ÷ fact;
  - every calculated field / LOD / table calc it cannot convert, with its name
    and the blocking construct;
  - unused / disabled calcs, display & gating calcs, and calc dependencies
    (which calcs reference which).

If `/importBI` does not return calc dependencies, display & gating calcs, or a
data source's table list, read them from the workbook / data-source XML —
facts, not classifications (Rule 3).

**Parallelize when supported.** With **2+** files, and if Genie Code can run
concurrent `/importBI` handoffs, profile them in **parallel batches of up to 4
files**: one profiling task per file as concurrent subagents, then the next
batch. Otherwise profile sequentially, one handoff per file. A single file is
profiled directly. Every handoff carries the same read-only `continueMessage`,
and all of it runs in one turn (Rule 6):

1. Hand off the file (or batch).
2. Immediately reduce each answer to a **Profile Digest** and keep only the
   digest — not the raw analysis — for the rest of the run.
3. Print one progress line per file: `Profiled <i>/<n> — <file name>`.
4. Continue with the next file or batch without waiting for the user.

The digests are the only source for every report — including a full
Individual Report requested later in Step 6. Never re-profile a file that
already has a digest.

#### Profile Digest

A fixed-format, internal record per file (target 30–50 lines; never printed).
Every row is grouped and counted; handling text is copied as one line from the
`/importBI` answer, or `Not stated by /importBI — verify`. Apply the
[Counting Rules](#counting-rules) while filling it in.

```text
FILE: <name> | TYPE: .twb/.twbx/.tds/.tdsx | WORKSHEETS: <n> | DASHBOARDS: <n> | DASHBOARD OBJECTS: <n>
DATA SOURCES: <name — connection — live/extract — tables (<sorted names>) — calcs <n> (✅ <n> ⚠️ <n> 🔧 <n>)>; …
CALCS: total <n> | classified <n> | display & gating <n> | row-level <n> | unused/disabled <n> | unused exclusion: applied / not applied (<reason>)
FAMILIES: <family — population — count — bucket — handling>; …
GROUPS / BINS / SETS: <n> / <n> / <n> — <bucket — handling> | PARAMETERS: <n> | ALIASES: <n> | HIERARCHIES: <n>
CONNECTIONS / PARAMETERS: <name — resolved/unresolved>; … | NON-DATABRICKS: <type — count>; …
SOURCE TABLES: <n> (<schema.table>, …) | CUSTOM SQL MISMATCHES: <n> | ALIAS WHITESPACE ISSUES: <n>
SOURCE TRANSFORMS: direct <n> | db+custom SQL <n> | non-db <n> | dependent <n> (<source → source>; …) | handling: <…>
RELATIONSHIPS: <pattern — count — bucket — handling>; …
VISUALS: <mark type — count — bucket — issue>; …
FILTERS: distinct fields <n> | worksheet instances <n> | dashboard controls <n> | measure names/values <n>
INTERACTIVITY: <feature — count — bucket>; … | DYNAMIC ZONE VISIBILITY / SHEET SWAP: <n>
ENTITLEMENTS: user filters / USERNAME() / ISMEMBEROF calcs <n>
LAYERS: model ✅ <n> ⚠️ <n> 🔧 <n> | visual ✅ <n> ⚠️ <n> 🔧 <n>
CALC DEPTH: max <n> levels
🔧 CALCS: <calc — data source — family — root | dependent of <root> — reason>; …
DEPENDENTS: <root → <n>: calc, calc 🔧, …>; …
GATING CALCS: <calc — what it gates>; …
```

Calc names are kept only in the 🔧 CALCS, DEPENDENTS, and GATING CALCS lines;
they feed the Manual Adjustment Report and the Readiness Summary.

### Step 4 — Consolidate

1. **Read the reference patterns** — once per run, before building any
   report, as described in [Reference Patterns](#reference-patterns). Do not
   build reports until the pattern status is set.
2. **Pick the report mode** by file count:

   | Files | Report |
   |---|---|
   | 1 | Template B (full) only — no Migration Summary Report |
   | 2–5 | Template A, then Template B (full) for every file |
   | 6+ | Template A, then Template B-compact for every file |

3. **Per file first.** Build each Individual Report from that file's own
   digest: Counting Rules, [Complexity Rating](#complexity-rating) score, and
   an Automation Uplift that matches **that file's** 🔧 items against the
   pattern list. Compute every percentage from that file's own counts.
4. **Group shared data sources** (bulk only) — see
   [Shared and Duplicate Data Sources](#shared-and-duplicate-data-sources).
5. **Then the portfolio.** Build Template A only by aggregating per-file
   results — never re-classify at portfolio level. Portfolio calc counts,
   including calcs reclassified by patterns, are sums over **unique data
   sources**, so a data source shared by several files is counted once. The
   portfolio Uplift rolls up the per-file Uplift tables in the same way.
6. **Detect outliers** (3+ files) using the [Outlier Rules](#outlier-rules).

### Step 5 — Consistency Check (mandatory, before printing)

Silently verify the drafted report. Fix every mismatch before printing; do not
print the check itself.

**Per file**

1. Classified + display & gating + row-level + unused / disabled calcs = total
   calculated fields, and every calc is in exactly one population. ✅ + ⚠️ + 🔧
   = classified calcs; the same holds for display & gating calcs and for the
   row-level block.
2. **Calc-family completeness**: every calculated field is in exactly one
   [calculation family](#calculation-families), and the family counts sum to
   the total calculated-field count. Groups, bins, sets, and parameters are not
   calculated fields and are reconciled separately.
3. Every count is identical wherever it appears — header metrics, Inventory,
   Feature Classification, Automation Summary, Uplift baseline, and (bulk) the
   Per-Workbook rows for that file. The Unused / disabled row is never
   silently dropped.
4. No dimension or plain field is counted as a calc; no calc is counted as both
   a measure and a dimension; no parameter, alias, or hierarchy is in the calc
   %; the unused exclusion is applied only where
   [Calc Populations](#calc-populations) allows it.
5. Every family name comes from [Calculation Families](#calculation-families)
   (or `Other — <name>`). A calc in several 🔧 families is counted **once**,
   under its primary (most blocking) family, with the note
   "n calcs also involve <other family>".
6. Root 🔧 calcs + 🔧 dependents = 🔧 calcs, and every dependent names its root.
7. The grouped 🔧 counts in the Readiness Summary reconcile with the 🔧 rows in
   Feature Classification (same families, same counts).
8. The complexity score equals the sum of the rubric points shown.
9. Every bucket and handling / resolution cell traces to the `/importBI`
   output, or (Uplift only) to a cited uc-semantics-patterns folder. Anything
   else → `Not stated by /importBI — verify` and 🔧.
10. The pattern status is in every report header, every Uplift section is
    present, and no "with patterns" or "Uplift (pp)" cell is blank — it holds a
    value (`+0` when no pattern matches), or `n/a — pattern repo unavailable`.
    In every row, Uplift (pp) = with patterns − baseline of that same row
    (including the per-file median row).

**Bulk runs**

11. Every Individual Report has the Rule 2 sections, with percentages from its
    own counts.
12. Portfolio counts (✅ / ⚠️ / 🔧, baseline and with patterns, including
    reclassified calcs) equal the sum over unique data sources. Files that
    share a data source are listed together in Unique Data Sources and the
    source is counted once.
13. "All files" = "Excluding outliers" + each outlier, for every count column.

Then return the full report in the chat.

### Step 6 — Offer Follow-ups

After printing the main report, offer the follow-ups that apply.

**1–5 files** — ask:

> "Do you want a detailed 🔧 Manual Adjustment Report listing the calculated
> fields / LODs / table calcs that need manual work?"

**6+ files (compact mode)** — list the files (number, name, complexity,
Auto with review % baseline, outlier flag) and ask:

> "Individual reports are shown in compact form. Do you want:
> 1. a full Individual Report for a specific file — which one(s)?
> 2. a detailed 🔧 Manual Adjustment Report — for all files or for the
>    selected file(s)?"

Suggest starting with flagged outliers and the files with the most root 🔧
calcs. For each file the user picks, print the full Template B from its
Profile Digest — do not re-profile. Its numbers must match the compact report
and the Per-Workbook Automation table.

Produce the [Manual Adjustment Report](#manual-adjustment-report-structure)
only if the user agrees. If they requested it (or a detailed list of manual
items) in the first prompt, skip that question and print it directly after the
main report; in compact mode, still offer the full Individual Report.

## Deduplication Rules

Within each Individual Report, each feature appears in exactly ONE place:

- **Executive Overview** names each complexity driver once (count + brief
  resolution); detail lives in the Inventory.
- **Inventory** sub-sections: data-source transformations and dependencies →
  Prerequisites only; relationships / joins / blends → the grouped
  Relationships table only; LOD expressions, table calcs, aggregate calcs →
  Data Modeling only; row-level calculated fields, groups, bins, sets → the
  Row-level block only; quick filters / filter controls → filters only;
  dashboard actions → interactivity only.
- **Automation Classification** references Inventory rows by name — no
  re-description.
- **Migration Summary Report** only aggregates and lists cross-cutting
  findings once; it never re-inventories features or repeats an Individual
  Report's tables.

## Empty Report Handling

When a file has **0 worksheets/visuals** — a data-source-only or connection-only
workbook, or any `.tds` / `.tdsx` data source — collapse Visualizations,
Interactivity, and Filters into one callout in that file's report:

> **Model-only workbook** — this file contains data-source connections and
> calculated fields with no worksheets, dashboards, filters, or actions. The
> dashboard must be designed from scratch after conversion. Visual/interaction
> inventory is N/A.

Do NOT print empty tables for each section.

## Counting Rules

These rules apply to every report — full, compact, and summary — and to the
Manual Adjustment Report.

### Buckets

The baseline reflects what `/importBI` reported in Step 3 — not theoretical
possibility. Only classify ✅ or ⚠️ if `/importBI` stated it handles the item.

- ✅ **Auto** — /importBI stated it converts this with no user intervention.
- ⚠️ **Auto + workaround** — /importBI stated it converts this by applying a
  known workaround automatically (source SQL view, precomputed column, window
  function, decomposition). The user reviews it but builds nothing manually.
- 🔧 **Manual** — /importBI cannot convert this, or did not state how it would.
  Must be redesigned after automated conversion completes.

**Cross-datasource / blend ratios** are always split:
- **Fact ÷ dimension / lookup** — the secondary source is a lookup joinable to
  the fact on a shared key (rates, targets, attributes). Bucket as reported by
  `/importBI`.
- **Fact ÷ fact** — a direct join fans out the rows and gives the wrong ratio.
  Each side must be **aggregated separately to a shared grain** (a
  pre-aggregated source view, or two metric views at that grain), **then
  divided**. Bucket as reported by `/importBI`, **capped at ⚠️** (never ✅); 🔧 if
  there is no shared conformed dimension. Never advise "just join them in the
  metric view". Describe the approach only as `/importBI` suggested it;
  otherwise reference a uc-semantics-patterns recipe in the Uplift section.

### Calc Populations

Every calculated field belongs to exactly one population:

| Population | Definition | In headline rate |
|---|---|---|
| Unused / disabled | Not referenced by any worksheet, other calc, action, or dashboard object in the file — **only where the unused exclusion applies** (below) | No |
| Display & gating | Returns presentation or layout control, not a business value: color / shape / size / label calcs, dynamic-title text, KPI arrows / indicator text, and boolean flags that gate visibility, zones, sheet swapping, or filter actions | No — own buckets and rate |
| Row-level | Non-aggregate calculated fields (arithmetic, IF/CASE, string/date), reported with groups, bins, and sets | No — own block (Model layer) |
| Classified | Aggregate calcs, LOD expressions, table calculations, and cross-datasource ratio calcs | Yes |

When a calc fits several, the first match wins: Unused / disabled → Display &
gating → Row-level → Classified. Display & gating calcs are still assessed for
readiness, even when simple, and are never dismissed as unused.

**The unused exclusion applies only when** the file has worksheets **and** the
calc's data source is not shared with another file in the run. For model-only
files (`.tds` / `.tdsx`, or a workbook with 0 worksheets) and shared data
sources, a calc that nothing in this file references may still be used by
other workbooks: keep it in its population and show
`Not used in this file: <n> (info — not excluded)` instead of an unused count.

### Rates

- **Auto %** = ✅ ÷ classified calcs — converts with no intervention.
- **Auto with review %** = (✅ + ⚠️) ÷ classified calcs — the **headline
  rate**; ⚠️ items convert automatically but must be reviewed.
- **🔧 %** = 🔧 ÷ classified calcs.
- "With patterns" versions use the counts after the Automation Uplift
  reclassification (🔧 → ⚠️), so patterns raise Auto with review %, not Auto %.
- **Uplift (pp)** = Auto with review % (with patterns) − Auto with review %
  (baseline) **in the same row** — for a file, a portfolio view, or the median
  row. Never take a median or average of uplift values.
- **Per-file median row**: each % column is the median of that column's
  per-file values; its Uplift (pp) is the difference of the two medians shown
  in that row.
- **Layer rates** — Auto with review % per layer, each with its item count:
  - **Model layer** — relationships / joins / blends, data-source
    transformations, the row-level block (row-level calcs, groups, bins,
    sets), and model features (parameters, aliases, hierarchies), counted by
    Inventory rows.
  - **Calcs** — the headline rate above (classified calcs).
  - **Visual layer** — visuals / marks, filters, and dashboard actions; `N/A`
    for model-only files.
  - **Display & gating calcs** — reported separately; never part of the
    headline.
- Show every rate with its denominator in the same row or cell. Mark any rate
  computed on fewer than 10 items `(small n)`.

### Root and Dependent 🔧 Calcs

- A **root 🔧 calc** is a 🔧 calc whose own formula blocks conversion — not one
  that is 🔧 only because it references another 🔧 calc.
- A **dependent** is any calc (✅, ⚠️, or 🔧) that references a root directly or
  through other calcs. It can only be converted once the root is rebuilt. A
  dependent of several roots is listed under the root it references most
  directly.
- Buckets stay as `/importBI` stated them. Report the number of root 🔧 calcs
  (the manual effort units), the blocked dependents, and the maximum calc
  dependency depth.
- Dependencies come from field references (`[Calc]`) in calc formulas — from
  `/importBI` or the workbook XML.

### Calculation Families

Assign every calculated field to exactly one family, and use the same names in
Data Modeling, the Row-level block, Feature Classification, Automation Uplift,
the Manual Adjustment Report, and every cross-file roll-up. The primary family
is the most blocking construct. Use `Other — <short name>` only if no family
fits.

| # | Family | Population |
|---|---|---|
| 1 | Simple aggregations (SUM, AVG, etc.) | Classified |
| 2 | FIXED LODs | Classified |
| 3 | INCLUDE / EXCLUDE LODs | Classified |
| 4 | Table calc — constant LOOKUP (fixed offset) | Classified |
| 5 | Table calc — dynamic LOOKUP (parameter/field-driven offset) | Classified |
| 6 | Table calc — analytical windows (running / moving / rank / period) | Classified |
| 7 | Table calc — mark-positioning windows (INDEX/SIZE/FIRST/LAST for layout) | Classified |
| 8 | Cross-datasource calc — fact ÷ dimension/lookup | Classified |
| 9 | Cross-datasource calc — fact ÷ fact (blend) | Classified |
| 10 | Row-level calculated fields (arithmetic, IF/CASE, string/date) | Row-level |
| 11 | Display calcs (color / shape / label / title / KPI text) | Display & gating |
| 12 | Gating calcs (visibility / zone / sheet-swap / action flags) | Display & gating |

- **Constant LOOKUP ≠ dynamic LOOKUP**: a fixed-offset `LOOKUP(SUM([x]), -1)`
  and a parameter-/field-driven offset are different migration risks — never
  merge them.
- **Mark-positioning windows ≠ analytics**: `INDEX`, `SIZE`, `FIRST`, `LAST`
  used to place marks or drive layout are not analytical windows (which map to
  window measures); they usually need manual redesign.
- **Parameter-dependent ratios** are ratio calcs (family 8 or 9), **never
  simple aggregations**, and are distinct from the Parameters model-feature
  row.
- Groups, bins, sets, parameters, aliases, and hierarchies are not calculated
  fields: groups / bins / sets go in the Row-level block; parameters, aliases,
  and hierarchies are model features — classified for effort, not in the
  calc %.

### Shared and Duplicate Data Sources

Bulk runs only. Every calc belongs to one data source in the XML. Compare the
DATA SOURCES lines of the digests:

- **Identical** — same connection, same table list, same calc count.
- **Variant** — same connection and table list, calc counts within ±10%.

Matching data sources across files — including a `.tds` / `.tdsx` in the run
and the workbooks that embed or connect to it — form one shared data source.
Count it through the copy with the most calcs.

- Individual Reports stay per file, with each file's own rates.
- Portfolio totals, rates, Uplift, and outlier shares count each shared data
  source once.
- The unused exclusion does not apply to calcs of a shared data source (see
  [Calc Populations](#calc-populations)).
- List every group in the Unique Data Sources table of Template A.

## Report Structure

These templates are the mandatory output format — copy the heading hierarchy
verbatim. Details such as fact-domain grouping go INSIDE the tables, never in
new sections; relationship details go only in the grouped Relationships table
(no separate "Relationship Analysis" narrative). Only list rows with a
count > 0.

Formatting illustrations (not statements of what `/importBI` supports):
"Simple aggregations (SUM, AVG, etc.) | 18 | ✅ Auto" · "Relationships (physical
joins, M:1) | 13 | ✅ Auto | <resolution as stated by /importBI>" ·
"INCLUDE / EXCLUDE LODs | 6 | 🔧 Manual | <as stated by /importBI>".

- **Single file** — one Template B (full).
- **Bulk (2+ files)** — Template A, then one Template B (full, or compact for
  6+ files) per file, in the same order as the Per-Workbook Automation table.

Each report starts with its own `#` title, so section headings are identical
in single-file and bulk runs.

### Template A — Migration Summary Report (bulk only)

```markdown
# Migration Summary Report

**Date scanned**: <date> | **Files**: <count> | **File type(s)**: <.twb / .twbx / .tds / .tdsx> | **Report mode**: full / compact
**/importBI**: <version, or "version not reported"> | **Reference patterns**: <read live — n patterns checked / Pattern repo unavailable>

| Metric | Total |
|---|---|
| Files (.twb / .twbx / .tds / .tdsx) | ... / ... / ... / ... |
| Unique data sources | ... |
| Worksheets / dashboards | ... / ... |
| Classified calcs (aggregate / LOD / table calc / cross-datasource) | ... (... / ... / ... / ...) |
| Display & gating calcs (not in headline rate) | ... |
| Row-level calcs / groups / bins / sets | ... |
| Unused / disabled calcs (excluded) | ... |
| Root 🔧 calcs (manual effort units) / blocked dependents | ... / ... |

## Unique Data Sources

<"Each file has its own data sources." or:>

| Data Source | Files | Match | Calcs | Counted Through |
|---|---|---|---|---|
| <data source> | <file, file> | Identical / Variant (±n calcs) | ... | <file> |

## Complexity Distribution

| Complexity | Workbooks | % of Total |
|---|---|---|
| Low | ... | ...% |
| Medium | ... | ...% |
| High | ... | ...% |

**Overall portfolio complexity**: <Low / Medium / High> — <1–2 sentence rationale>

## Per-Workbook Automation

| # | Workbook | File Type | Complexity (score) | Classified Calcs | Auto % | Auto with review % | 🔧 % | Root 🔧 | Auto with review % (with patterns) | Uplift (pp) | Outlier |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | ... | .twb / .twbx / .tds / .tdsx | High (9) | ... | ...% | ...% | ...% | ... | ...% | +... | — / ⚑ <reason> |

**Distribution (Auto with review %, baseline)**: <n> files ≥ 80% · <n> files 50–80% · <n> files < 50%

## Portfolio Automation Summary

| View | Files / Data Sources | Classified Calcs | ✅ | ⚠️ | 🔧 | Root 🔧 | Auto % | Auto with review % (baseline) | Auto with review % (with patterns) | Uplift (pp) |
|---|---|---|---|---|---|---|---|---|---|---|
| All files (unique data sources, calc-weighted) | ... / ... | ... | ... | ... | ... | ... | ...% | ...% | ...% | +... |
| Excluding outliers (calc-weighted) | ... / ... | ... | ... | ... | ... | ... | ...% | ...% | ...% | +... |
| Per-file median | ... / — | — | — | — | — | — | ...% | ...% | ...% | +... |

## Automation Uplift with Reference Patterns

Roll-up of the per-file Uplift tables (each shared data source once).

| 🔧 Family | Applicable Pattern | Recipe | Files | Calcs Reclassified to ⚠️ |
|---|---|---|---|---|
| <family> | <pattern name from repo> | <repo folder / recipe> | <file, file> | <n> |

> **Portfolio automation uplift**: applying
> [uc-semantics-patterns](https://github.com/databricks-solutions/uc-semantics-patterns)
> recipes raises Auto with review % from **<baseline>%** to
> **<with-patterns>%** (**+<delta>pp**) across all files, and from <x>% to <y>%
> excluding outliers. Largest gains: <file (+pp)>, <file (+pp)>.

<or the no-match / repo-unavailable line from Reference Patterns>

## Outliers

<"None — no file meets the outlier rules" or, per flagged file:>

| Workbook | Reason | Share of Portfolio Classified Calcs | Classified Calcs | ✅ | ⚠️ | 🔧 | Auto with review % (baseline) | Auto with review % (with patterns) | Effect on Portfolio |
|---|---|---|---|---|---|---|---|---|---|
| ... | Size: ...% of calcs / Rate: ±..pp vs. portfolio | ...% | ... | ... | ... | ... | ...% | ...% | Lowers / raises the all-files rate by ...pp |

> **Reading the portfolio rate**: <1–2 sentences — e.g. "The all-files rate of
> 48% is driven by <outlier>; the remaining <n> files average 79%.">

## Cross-cutting Findings

- **Recurring 🔧 families**: <family — n files, n root 🔧, n 🔧 calcs>
- **Aggregate data prerequisites** (Unity Catalog): <UC tables/sources required across the portfolio; extracts to re-point>
- **Non-Databricks sources across portfolio**: <source type + count per type, or "None">
- **Unresolved connections / parameters across files**: <list or "None">

## Recommended Migration Sequence

| Wave | Workbooks | Why |
|---|---|---|
| 1 — Quick wins | ... | High Auto with review %, Low complexity, all-Databricks |
| 2 | ... | Shared prerequisites resolved, ⚠️ workarounds validated |
| 3 — Redesign | ... | Outliers / many root 🔧 / High complexity |
```

### Outlier Rules

Apply only when the run has **3+ files**. Flag a file (⚑) when either is true:

1. **Size outlier** — the file holds **> 40%** of the portfolio's classified
   calcs **and** more than **2×** the average share (100% ÷ number of files).
2. **Rate outlier** — the file has **≥ 10 classified calcs** and its baseline
   Auto with review % differs by **more than 20 percentage points** from the
   calc-weighted rate of all files that are not size outliers. (Find size
   outliers first, compute that reference rate once, then test each file.)

Files with fewer than 10 classified calcs are never rate outliers; mark their
rates `(small n)`. Show every flagged file in the **Outliers** table and keep
it out of the "Excluding outliers" row. Never let an outlier's rate stand in
for the portfolio: the Reading-the-portfolio-rate line must name it.

### Template B — Individual Report (full)

Used for a single-file run, for every file in a 2–5 file run, and for any file
the user picks in Step 6.

```markdown
# Individual Report — <Workbook Name>

**Date scanned**: <date> | **Source path**: <path> | **File type**: <.twb / .twbx / .tds / .tdsx>
**/importBI**: <version, or "version not reported"> | **Reference patterns**: <read live — n patterns checked / Pattern repo unavailable>

| Metric | Count |
|---|---|
| Worksheets / dashboards | ... / ... |
| Data sources (live / extract) | ... / ... |
| Physical data connections | ... |
| Classified calcs (aggregate / LOD / table calc / cross-datasource) | ... (... / ... / ... / ...) |
| Display & gating calcs | ... |
| Row-level calcs / groups / bins / sets | ... |
| Unused / disabled calcs (excluded) — or "Not used in this file (info)" | ... |
| Root 🔧 calcs / blocked dependents / max calc depth | ... / ... / ... |
| Parameters | ... |
| User filters / entitlement calcs (USERNAME / ISMEMBEROF) | ... |

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

### Data Source Transformations

| Source type | Count | Depends on / Used by | /importBI Handling |
|---|---|---|---|
| Direct connection (no transforms) | ... | ... | <as stated by /importBI> |
| Databricks + custom SQL / Initial SQL / transforms | ... | ... | <as stated by /importBI> |
| Non-Databricks source | ... | ... | <as stated by /importBI> |
| Dependent source (published source built on another, union, cross-DB join, blend secondary, or referenced by a parameter / action) | ... | <source → source> | <as stated by /importBI> |

### Non-Databricks Sources

<source type + count per type, or "None — all sources are Databricks">

## Executive Overview

**Complexity**: <Low / Medium / High> (score <n>) — <score breakdown, e.g. "root 🔧 2 · calcs 1 · sources 1 · blends 1">

**Rationale**: <2–3 sentences>

### Complexity Drivers (ranked by impact)

| # | Driver | Count | Impact | Resolution |
|---|---|---|---|---|
| 1 | ... | ... | 🔴/🟠/🟡 | ... |

## Feature Inventory

### Data Sources

| Connection Type | Count | Databricks? | Migration Impact |
|---|---|---|---|
| Databricks (live, passthrough) | ... | Yes | <as stated by /importBI> |
| Databricks (with custom SQL / transforms) | ... | Yes | <as stated by /importBI> |
| Extract (.hyper) | ... | Depends | <as stated by /importBI> |
| Non-Databricks (SQL Server, Excel, etc.) | ... | No | <as stated by /importBI> |

> Clearly distinguish **physical connections** from Tableau **logical/federated
> groupings** (relationships/noodle model): count physical joins separately from
> logical relationships.

### Relationships

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

### Data Modeling

Classified and display & gating calcs by
[family](#calculation-families), plus model features (classified for effort,
not in the calc %). Row-level calcs, groups, bins, and sets go in the next
block.

| Feature | Population | Count | Classification | Note |
|---|---|---|---|---|
| Simple aggregations (SUM, AVG, etc.) | Classified | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| FIXED LODs | Classified | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| INCLUDE / EXCLUDE LODs | Classified | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| Table calc — constant LOOKUP (fixed offset) | Classified | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| Table calc — dynamic LOOKUP (parameter/field-driven offset) | Classified | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| Table calc — analytical windows (running / moving / rank / period) | Classified | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| Table calc — mark-positioning windows (INDEX/SIZE/FIRST/LAST for layout) | Classified | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| Cross-datasource calc — fact ÷ dimension/lookup | Classified | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| Cross-datasource calc — fact ÷ fact (blend) | Classified | ... | ⚠️/🔧 (never ✅) | <as stated by /importBI> |
| Display calcs (color / shape / label / title / KPI text) | Display & gating | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| Gating calcs (visibility / zone / sheet-swap / action flags) | Display & gating | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| Parameters | Model feature | ... | ✅/⚠️/🔧 | not in calc %; <as stated by /importBI> |
| Field / value-level aliases | Model feature | ... | ✅/⚠️/🔧 | not in calc %; <as stated by /importBI> |
| Hierarchies | Model feature | ... | ✅/⚠️/🔧 | not in calc %; <as stated by /importBI> |

### Row-level Calculations, Groups, Bins & Sets

Not in the calc % — reported on their own line in the Automation Summary and
in the Model layer.

| Pattern | Count | Bucket | /importBI Handling |
|---|---|---|---|
| Row-level calculated fields (arithmetic, IF/CASE, string/date) | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| Groups | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| Bins | ... | ✅/⚠️/🔧 | <as stated by /importBI> |
| Sets | ... | ✅/⚠️/🔧 | <as stated by /importBI> |

### Visualizations

| Visual / Mark Type | Count | AI/BI Equivalent | Issues |
|---|---|---|---|
| ... only non-trivial or problematic visuals ... |
| Dual-axis / combined multi-mark | ... | <as stated by /importBI> | <as stated by /importBI> |
| Maps (filled / symbol / custom geocoding) | ... | <as stated by /importBI> | <as stated by /importBI> |
| KPI / counter (BAN) | ... | <as stated by /importBI> | <as stated by /importBI> |
| Reference lines / bands / annotations | ... | <as stated by /importBI> | <as stated by /importBI> |
| Custom / rare marks | ... | <as stated by /importBI> | <as stated by /importBI> |

If model-only: use Empty Report Handling callout.

### Interactivity & Filters

Report filter volume as **three distinct counts** — do not conflate them: the number
of **distinct filter fields** (unique fields filtered on), the number of **worksheet
filter instances** (the same field filtered on N worksheets counts N times), and the
number of **dashboard controls** (filter cards/controls shown on dashboards). Keep
**Measure Names / Measure Values** separate — that is a display/measure-selection
mechanism, **not a data filter** — and never count it toward the filter totals.

| Filter metric | Count |
|---|---|
| Distinct filter fields | ... |
| Worksheet filter instances | ... |
| Dashboard controls (filter cards) | ... |
| Measure Names / Measure Values (display selection — not a data filter) | ... |

| Feature | Count | Status |
|---|---|---|
| Filter controls (quick filters) | ... | ✅/⚠️/🔧 |
| Context filters | ... | ✅/⚠️/🔧 |
| Cascading / dependent filters | ... | ✅/⚠️/🔧 |
| Dashboard filter actions | ... | ✅/⚠️/🔧 |
| Highlight actions | ... | ✅/⚠️/🔧 |
| URL / navigation / drill actions | ... | ✅/⚠️/🔧 |
| Parameter actions | ... | ✅/⚠️/🔧 |
| Dynamic zone visibility / sheet swapping | ... | ✅/⚠️/🔧 |

> A filter set to "(All)" is **not** necessarily a no-op — check the consumer formula
> before treating it as "no filter"; it may be read by a calc (e.g. `ISFILTERED` /
> context-dependent LODs) or gate a view.

If model-only: use Empty Report Handling callout.

## Automation Classification

Classify every Inventory feature using the [Buckets](#buckets).

### Feature Classification

| Feature (from Inventory) | Population | Count | Bucket | /importBI Behavior |
|---|---|---|---|---|
| ... | Classified / Display & gating / Row-level / Model / Visual | ... | ✅/⚠️/🔧 | One line, as stated by /importBI (or "Not stated by /importBI — verify") |

### Automation Summary

| Bucket | Features | Classified Calcs | % of Classified Calcs |
|---|---|---|---|
| ✅ Auto | ... | ... | ...% |
| ⚠️ Auto + workaround | ... | ... | ...% |
| 🔧 Manual | ... | ... | ...% |

**Auto %**: <n>% · **Auto with review %**: <n>% (of <n> classified calcs)
**Root 🔧 calcs**: <n> roots block <n> dependents (<n> of them 🔧); max calc depth <n>

| Layer | Items | ✅ | ⚠️ | 🔧 | Auto with review % |
|---|---|---|---|---|---|
| Model layer | ... | ... | ... | ... | ...% |
| Calcs (classified) | ... | ... | ... | ... | ...% |
| Visual layer | ... | ... | ... | ... | ...% / N/A |
| Display & gating calcs | ... | ... | ... | ... | ...% |

**Unused / disabled calcs (excluded)**: <n> — or `Not used in this file: <n> (info — not excluded)`
**Row-level calcs, groups, bins & sets (Model layer, not in calc %)**: ✅ <n> / ⚠️ <n> / 🔧 <n>

## Automation Uplift with Reference Patterns

| 🔧 Family | Calcs | Applicable Pattern | Reclassified To | Recipe |
|---|---|---|---|---|
| <family from Classification> | <n> | <pattern name from repo> | ⚠️ Auto + workaround | <repo folder / recipe, short description> |

<or only the no-match / repo-unavailable line from Reference Patterns — then
omit the Revised Automation Summary and the callout below>

**Revised Automation Summary (with patterns)**:

| Bucket | Classified Calcs (baseline) | Classified Calcs (with patterns) | % Baseline | % With Patterns |
|---|---|---|---|---|
| ✅ Auto | ... | ... | ...% | ...% |
| ⚠️ Auto + workaround | ... | ... | ...% | ...% |
| 🔧 Manual | ... | ... | ...% | ...% |

> **Automation uplift**: Applying
> [uc-semantics-patterns](https://github.com/databricks-solutions/uc-semantics-patterns)
> recipes during migration can raise Auto with review % from **<baseline>%** to
> **<with-patterns>%** (a **+<delta>pp** improvement), potentially shifting the
> complexity from <baseline rating> to <new rating>.

## Readiness Summary

**Primary blockers** (root 🔧 calcs, by family):
- <list>

**Data prerequisites** (Unity Catalog):
- <UC tables/sources that must exist before conversion; extracts to re-point at live sources>

**Semantic-model remediation** (🔧 only, before conversion):
- <grouped 🔧 blockers by family with counts — e.g. "INCLUDE / EXCLUDE LODs — 4 roots", "fact ÷ fact blends — 2">
- Names of each 🔧 item are available in the optional 🔧 Manual Adjustment Report (Step 6).

**Dashboard-gating calculations**:
- <gating calcs and what they gate — field/zone visibility, filter actions, dynamic
  zone visibility (e.g. `RM`, `fSite`, `fPlatform`)>. They control the layout, so
  they must be assessed for readiness even when simple, and never dismissed as unused.

**Visualization / interaction redesign** (🔧 visuals/interaction):
- <unsupported visuals, custom geocoding, parameter/highlight/URL actions, analytics objects>

**Recommended next steps**:
1. Resolve prerequisites (connections, parameters, source access, extract → live source)
2. Rebuild root 🔧 calcs (this unblocks their dependents)
3. Run /importBI for ✅ and ⚠️ items
4. Review ⚠️ workaround results
5. Build net-new visuals if model-only workbook

### Specific Risks
- <workbook-specific list>

### Validation Checks
- <list of things to verify after conversion>
```

### Template B-compact — Individual Report (6+ files)

At most **25 lines** per file. Same numbers as the full Template B; inventory
and prerequisite detail roll up into the Migration Summary Report's
Cross-cutting Findings. The full report for any file is available in Step 6.

```markdown
# Individual Report — <Workbook Name>

**Type**: .twb / .twbx / .tds / .tdsx | **Complexity**: <Low / Medium / High> (<score>) | **Outlier**: — / ⚑ <reason>
**Reference patterns**: <read live — n patterns checked / Pattern repo unavailable>

**Metrics**: <w> worksheets · <d> dashboards · <c> classified + <g> display & gating calcs (+<u> unused) · <r> row-level / groups / bins / sets · <k> root 🔧 blocking <b> · <s> non-Databricks sources · <x> extracts

## Automation Classification

**⚠️ families**: <family (n)>, … | **🔧 families**: <family (n roots / n calcs)>, …

## Automation Summary & Uplift

| Bucket | Classified Calcs (baseline) | % | Classified Calcs (with patterns) | % |
|---|---|---|---|---|
| ✅ Auto | ... | ...% | ... | ...% |
| ⚠️ Auto + workaround | ... | ...% | ... | ...% |
| 🔧 Manual | ... | ...% | ... | ...% |

**Auto %**: <n>% · **Auto with review %**: <baseline>% → <with patterns>% (+<delta>pp) via <recipe (n calcs)>, … / "No matching pattern — no uplift" / "Pattern repo unavailable"

**Layers** (Auto with review %): Model <x>% (n) · Visual <y>% (n) / N/A · Display & gating <z>% (n)

**Primary blockers** (root 🔧, top 3): <family — n roots>, …
```

> **REMINDER**: The templates above are the COMPLETE report — see Rules 1–2.

## Manual Adjustment Report Structure

Produced after the main report, when requested in the first prompt or
accepted in Step 6 — with the same structure and check either way, so the user
never needs to describe the format. In a bulk run it covers all files, or only
the file(s) the user selected. This is the only place where individual 🔧 item
names are listed, and it lists **all** of them — no top-N cap.

- Organised by **root 🔧 calcs**; each root lists the calcs it blocks, so the
  manual effort is the number of roots.
- One `##` group per [family](#calculation-families), in the same names and
  order as Feature Classification.
- A 🔧 calc that is 🔧 only because it references a root is listed under that
  root (marked 🔧 in the Blocks column), not as its own row.
- Reasons come from the `/importBI` output — the blocking construct it
  reported.

```markdown
# 🔧 Manual Adjustment Report

**Root 🔧 calcs**: <n> (manual effort units) | **Blocked dependents**: <n> (of which 🔧: <n>)

## <Family> — <n> roots, <n> 🔧 calcs

| Root Calc | Data Source | Workbook (bulk only) | Reason | Blocks |
|---|---|---|---|---|
| `Profit Ratio` | Orders | Sales.twbx | Cross-datasource blend (fact ÷ fact) — aggregate each side then divide | 2: [Profit Ratio LY] 🔧, [Profit Ratio Δ] |

## <next family> — <n> roots, <n> 🔧 calcs
...

**Per-workbook subtotals** (bulk only): <workbook — n roots, n 🔧 calcs>; …

**Consistency**: <n> roots + <n> 🔧 dependents = <total> 🔧 calcs = 🔧 in the
Automation Summary and the Row-level / Display & gating lines; family counts
match the Feature Classification table.
```

**Manual Adjustment consistency check (mandatory, before printing):**

1. Roots + 🔧 dependents listed = all 🔧 calcs of the file(s) covered
   (classified, display & gating, and row-level).
2. Every 🔧 calc appears exactly once — as a root row or as a 🔧 entry in one
   root's Blocks column — and also appears in Feature Classification.
3. For every family, the 🔧 count in Feature Classification equals the number
   of 🔧 calcs of that family in this report, whether listed as a root or as a
   dependent.
4. Every root has a data source and a non-empty reason.
5. Bulk only: each workbook subtotal equals the root and 🔧 counts in that
   workbook's Individual Report, and the subtotals add up to the total.

If anything differs, fix it before printing and say which report was
corrected. The final **Consistency** line states the result.

## Complexity Rating

Score every file with the points below, then show the rating with the score
(e.g. "High (9)") and a one-line breakdown in the Executive Overview. All
inputs are counts from the Profile Digest. The rating describes migration
effort; it does not describe `/importBI` behavior.

| Factor | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| Root 🔧 calcs | 0 | 1–5 | 6–15 | 16+ |
| Classified calcs | < 20 | 20–99 | 100+ | — |
| Calc dependency depth | < 3 levels | 3+ levels | — | — |
| Non-Databricks source types or `.hyper` extracts | 0 | 1 | 2+ | — |
| Data blends / fact-to-fact relationships | None | Present | — | — |
| INCLUDE / EXCLUDE or nested LODs | None | Present | — | — |
| Dynamic LOOKUP or mark-positioning windows | None | Present | — | — |
| Parameter / URL / navigation actions; dynamic zone visibility / sheet swapping | None | One kind | Both | — |
| User filters / entitlement calcs (USERNAME / ISMEMBEROF) | None | Present | — | — |
| Worksheets + dashboard objects | < 10 | 10–29 | 30+ | — |
| Custom geocoding, analytics objects (forecast, cluster, trend), > 3 dual-axis, composite scorecards | None | One kind | 2+ kinds | — |
| Model or Visual layer Auto with review % below 50% | Neither | One | Both | — |

**Rating**: 0–3 **Low** · 4–7 **Medium** · 8+ **High**.

## Reference Patterns

Read `https://github.com/databricks-solutions/uc-semantics-patterns` live,
**once per run**, before building any report (Step 4), and reuse that pattern
list for every file. Never rely on a remembered or cached list — the repo
changes — and never skip the read because the run is long.

1. Read the repo's root `README.md`.
2. Follow its links to the pattern folders and read the recipe for any pattern
   that may match a 🔧 item (e.g. period-over-period growth, period-to-date
   totals, moving calculations, semi-additive calculations, ranking, static
   segmentation, currency conversion, fact ÷ fact ratios). These are
   source-agnostic UC metric-view recipes, so Tableau LODs, table
   calculations, and blends map onto them directly.
3. Keep a pattern list: pattern name → repo folder / recipe → what it handles,
   and set the **pattern status** shown in every report header:
   `read live — <n> patterns checked` or `Pattern repo unavailable`.

Each Automation Uplift section (per file, and the portfolio roll-up):

- lists each 🔧 item matched to a pattern **only by what the current repo
  content documents**, with the reclassified bucket (⚠️) and the cited
  folder / recipe;
- when there is an uplift, shows the Revised Automation Summary, the
  percentage-point uplift, and whether it changes the complexity rating;
- links to the repo.

Fallbacks — the section is never omitted:

- **No match (no uplift)**: the section holds only the line
  "No matching pattern — no uplift; baseline applies." — no tables and no
  uplift callout. Portfolio, when no file has a match: "No matching pattern in
  any file — no uplift; baseline applies." In the Per-Workbook and Portfolio
  tables, "with patterns" equals baseline and Uplift (pp) is `+0`.
- **Repo unavailable**: write "Pattern repo unavailable — uplift not computed;
  baseline applies." in every Uplift section instead of the table and revised
  summary, and `n/a — pattern repo unavailable` in every "with patterns" cell.
