---
name: pbi-migration-assessment
description: >
  Bulk profiling and migration-readiness assessment for Power BI reports (.pbit files)
  and semantic models (.tmdl files)
  before converting them to Databricks AI/BI dashboards. Load this skill when the user
  asks to assess, profile, audit, or evaluate Power BI reports for migration complexity,
  or when bulk-importing Power BI files from a Unity Catalog Volume.
---

# Power BI Migration Assessment Skill

This skill runs a **read-only profiling pass** over one or more Power BI files
(`.pbit` reports, `.tmdl` semantic models) and produces a concise Migration
Assessment Report. Every ✅/⚠️/🔧 classification is anchored to what the
`/importBI` migration agent reports it can handle; the **Automation Uplift**
shows how [uc-semantics-patterns](https://github.com/databricks-solutions/uc-semantics-patterns)
recipes can raise the Auto with review share further. Bulk runs (2+ files) open
with a **Migration Summary Report** followed by one **Individual Report** per
file (compact for 6+ files). Nothing is converted.

## Rules

> **CRITICAL** — these rules apply to every run. Breaking them makes the report
> unusable.

1. **Exact format.** Use the exact headings and tables in
   [Report Structure](#report-structure). No numbered sections (`## 1.`,
   `## 2.`), no extra sections, no omitted sections.
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
   [Reference Patterns](#reference-patterns)). Facts read from the model
   definition (table lists, measure references) are allowed; classifications
   are not.
4. **Concise — group and count.** Never list individual measure names,
   relationship edges, or calculated-column DAX in the main report (write
   "Simple aggregations | 18 | ✅ Auto"). Measure names appear only in the
   🔧 Manual Adjustment Report. Limits: ≤ 300 lines per full Individual Report,
   ≤ 25 per compact one, ≤ 150 for the Migration Summary Report. Never shorten a
   report beyond the compact form.
5. **✅/⚠️/🔧 only** — never ❌. See [Buckets](#buckets).
6. **One pass.** Run every step for every file in one turn. Between the Step 1
   file count and the final report, print only `Profiled <i>/<n> — <file name>`
   per file. Never print a profile or a per-file report while profiling, and
   never stop to ask the user to "continue" or confirm the next file.
7. **Read-only.** Never convert, create datasets, or create widgets — this
   applies to the `/importBI` handoffs too.
8. **Counting Rules everywhere.** Measure populations, rates, root 🔧 measures,
   feature groups, auto date/time exclusion, 🔗 external measures, and shared
   models follow [Counting Rules](#counting-rules).
9. **Never omit referenced queries.** A query used by another query (merge,
   append, reference) is never marked omittable.
10. **Checks are mandatory.** Run Step 5 before printing every report, and the
    Manual Adjustment check before every Manual Adjustment Report.
11. **Power BI only.** Use Power BI terms (DAX, measures, slicers, Power Query /
    M). Tableau files use a separate skill.

## When to Use

- User attaches one or more `.pbit` or `.tmdl` files and asks to assess or profile them
- User points to a UC Volume path containing Power BI files and asks for bulk assessment
- User asks about migration complexity, blockers, or readiness for Power BI → AI/BI migration

## Workflow

### Step 1 — Enumerate Files

If the user provides a Volume path (e.g. `/Volumes/catalog/schema/volume/`):
1. List all `.pbit` and `.tmdl` files in that path
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
- **Query dependencies**: Record which queries use which (see Rule 9).
- **Source table inventory**: List UC schema.table references so the user can
  verify accessibility.
- **🔗 External measures**: Scan every DAX measure for `EXTERNALMEASURE(` and
  record the remote semantic model(s) — see [External Measures](#external-measures).

### Step 3 — Profile Each Report

For each file, hand off to the `/importBI` migration specialist on a
**temporary or existing dashboard** with a `continueMessage` that:

- begins with `/importBI` and includes the file name or path;
- states: **"Profile only — do NOT convert. Do not create any datasets or
  widgets."**;
- asks `/importBI` to state how it would handle **every field of the
  [Profile Digest](#profile-digest)** — grouped and counted, using the
  [Measure Feature Groups](#measure-feature-groups) names, one-line handling
  per row, no prose — and in particular:
  - relationships by pattern: standard M:1 active, inactive (USERELATIONSHIP),
    bidirectional, M:M, date table on the many side, fact-to-fact links, joins
    on differently named columns, disconnected tables (slicer helpers /
    TREATAS targets);
  - cross-table measures, split fact ÷ dimension vs fact ÷ fact;
  - every measure it cannot convert, with its name and the blocking DAX
    construct;
  - measure dependencies (which measures reference which).

If `/importBI` does not return measure dependencies, display measures, or the
model's table list, read them from the file's model definition
(`DataModelSchema` inside the `.pbit`, or the `.tmdl`) — facts, not
classifications (Rule 3).

Process files sequentially, all in the same turn (Rule 6):

1. Hand off the file to `/importBI`.
2. Immediately reduce its answer to a **Profile Digest** and keep only the
   digest — not the raw analysis — for the rest of the run.
3. Print one progress line: `Profiled <i>/<n> — <file name>`.
4. Continue with the next file without waiting for the user.

The digests are the only source for every report — including a full
Individual Report requested later in Step 6. Never re-profile a file that
already has a digest.

#### Profile Digest

A fixed-format, internal record per file (target 30–50 lines; never printed).
Every row is grouped and counted; handling text is copied as one line from the
`/importBI` answer, or `Not stated by /importBI — verify`. Apply the
[Counting Rules](#counting-rules) while filling it in.

```text
FILE: <name> | TYPE: .pbit/.tmdl | PAGES: <n> | VISUALS: <n> | STORAGE: import/DirectQuery/composite/live
MODEL SIGNATURE: tables <n> (<sorted table names, auto date/time excluded>) | measures <n> | calc columns <n>
AUTO DATE/TIME TABLES: <n> (excluded from all counts)
MEASURES: total <n> | business <n> | display <n> | unused <n> | 🔗 external <n> (remote: <model(s)>) | unused exclusion: applied / not applied (<reason>)
CALC COLUMNS / TABLES: <n> / <n> | CALC GROUPS: <n> | FACT / DIM: <n> / <n>
SECURITY: RLS roles <n> (static/dynamic) | OLS: yes/no
PARAMETERS: <name — resolved/unresolved>; …
SOURCES: <connection type — count — Databricks? >; … | SOURCE TABLES: <n> (<schema.table>, …)
M-QUERIES: direct <n> | db+transforms <n> | non-db <n> | dependent <n> (<query → query>; …) | handling: <…>
RELATIONSHIPS: <pattern — count — bucket — handling>; …
MEASURE GROUPS: <feature group — business/display — count — bucket — handling>; …
CALC COL/TABLE GROUPS: <pattern — count — bucket — handling>; …
VISUALS / INTERACTIVITY: <type or feature — count — bucket — issue>; …
LAYERS: model ✅ <n> ⚠️ <n> 🔧 <n> | visual ✅ <n> ⚠️ <n> 🔧 <n>
🔧 MEASURES: <measure — table — feature group — root | dependent of <root> — reason>; …
DEPENDENTS: <root → <n>: measure, measure 🔧, …>; …
🔗 EXTERNAL MEASURES: <measure — remote model>; …
DEPENDS ON 🔗: <n local measures>
```

Measure names are kept only in the 🔧 MEASURES, DEPENDENTS, and 🔗 EXTERNAL
MEASURES lines; they feed the Manual Adjustment Report.

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
4. **Group shared models** (bulk only) — see
   [Shared and Duplicate Models](#shared-and-duplicate-models).
5. **Then the portfolio.** Build Template A only by aggregating per-file
   results — never re-classify at portfolio level. Portfolio counts, including
   measures reclassified by patterns, are sums over **unique semantic models**
   (one representative file per model). The portfolio Uplift rolls up the
   per-file Uplift tables in the same way.
6. **Detect outliers** (3+ files) using the [Outlier Rules](#outlier-rules).

### Step 5 — Consistency Check (mandatory, before printing)

Silently verify the drafted report. Fix every mismatch before printing; do not
print the check itself.

**Per file**

1. Business + display + unused + 🔗 external = total measures, and every
   measure is in exactly one population. ✅ + ⚠️ + 🔧 = business measures; the
   same holds for display measures.
2. Every count is identical wherever it appears — header metrics, Inventory,
   Feature Classification, Automation Summary, Uplift baseline, and (bulk) the
   Per-Workbook rows for that file.
3. No calculated column or table is counted as a measure; auto date/time
   tables, columns, and relationships are in no count; the unused exclusion is
   applied only where [Measure Populations](#measure-populations) allows it.
4. Every group name comes from [Measure Feature Groups](#measure-feature-groups)
   (or `Other — <name>`). A measure in several 🔧 groups is counted **once**,
   under its primary (most blocking) group, with the note
   "n measures also involve <other group>".
5. Root 🔧 measures + 🔧 dependents = 🔧 measures, and every dependent names its
   root.
6. Every 🔧 item named in the Readiness Summary appears in Feature
   Classification.
7. The complexity score equals the sum of the rubric points shown.
8. Every bucket and handling / resolution cell traces to the `/importBI`
   output, or (Uplift only) to a cited uc-semantics-patterns folder. Anything
   else → `Not stated by /importBI — verify` and 🔧.
9. No 🔗 external measure is in any ✅/⚠️/🔧 count, percentage, Uplift row, or
   Manual Adjustment count. With 1+ 🔗 measures, the External Measures callout
   and the External Semantic Models table are shown (bulk: the portfolio
   callout too).
10. The pattern status is in every report header, every Uplift section is
    present, and no "with patterns" or "Uplift (pp)" cell is blank — it holds a
    value (`+0` when no pattern matches), or `n/a — pattern repo unavailable`.
    In every row, Uplift (pp) = with patterns − baseline of that same row
    (including the per-file median row).

**Bulk runs**

11. Every Individual Report has the Rule 2 sections, with percentages from its
    own counts.
12. Portfolio counts (✅ / ⚠️ / 🔧, baseline and with patterns, including
    reclassified measures) equal the sum over unique semantic models — over
    files when no model is shared. Files that share a model are listed
    together in Unique Semantic Models and counted once.
13. "All files" = "Excluding outliers" + each outlier, for every count column.

Then return the full report in the chat.

### Step 6 — Offer Follow-ups

After printing the main report, offer the follow-ups that apply.

**1–5 files** — ask:

> "Do you want a detailed 🔧 Manual Adjustment Report listing the measures
> that need manual work?"

**6+ files (compact mode)** — list the files (number, name, complexity,
Auto with review % baseline, outlier flag) and ask:

> "Individual reports are shown in compact form. Do you want:
> 1. a full Individual Report for a specific file — which one(s)?
> 2. a detailed 🔧 Manual Adjustment Report — for all files or for the
>    selected file(s)?"

Suggest starting with flagged outliers and the files with the most root 🔧
measures. For each file the user picks, print the full Template B from its
Profile Digest — do not re-profile. Its numbers must match the compact report
and the Per-Workbook Automation table.

Produce the [Manual Adjustment Report](#manual-adjustment-report-structure)
only if the user agrees. If they requested it (or a detailed list of manual
measures) in the first prompt, skip that question and print it directly after
the main report; in compact mode, still offer the full Individual Report.

## Deduplication Rules

Within each Individual Report, each feature appears in exactly ONE place:

- **Executive Overview** names each complexity driver once (count + brief
  resolution); detail lives in the Inventory.
- **Inventory** sub-sections: M-query transformations and dependencies →
  Prerequisites only; relationships → Relationships only; calculated columns /
  tables → Calculated Columns & Tables only; calculation groups, field
  parameters, RLS → Data Modeling only; slicers → filters only; bookmarks →
  interactivity only.
- **Automation Classification** references Inventory rows by name — no
  re-description.
- **Migration Summary Report** only aggregates and lists cross-cutting
  findings once; it never re-inventories features.

## Empty Report Handling

When a `.pbit` has **0 visuals**, or the file is a `.tmdl` (semantic model
only — `/importBI` creates metric views from it, no dashboard), collapse
Visualizations, Interactivity, and Filters into one callout:

> **Model-only template** — this `.pbit` / `.tmdl` contains a semantic model with no
> report visuals, slicers, bookmarks, or filters. The dashboard must be
> designed from scratch after conversion. Visual/interaction inventory is N/A.

Do NOT print empty tables for each section.

## Counting Rules

These rules apply to every report — full, compact, and summary — and to the
Manual Adjustment Report.

### Buckets

The baseline reflects what `/importBI` reported in Step 3 — not theoretical
possibility. Only classify ✅ or ⚠️ if `/importBI` stated it handles the item.

- ✅ **Auto** — /importBI stated it converts this with no user intervention.
- ⚠️ **Auto + workaround** — /importBI stated it converts this by applying a
  workaround automatically (e.g. a source view, derived column, or
  decomposition). The user reviews it but builds nothing manually.
- 🔧 **Manual** — /importBI cannot convert this, or did not state how it
  would. Must be redesigned after automated conversion completes.

**Cross-table measures** are always split:
- **Fact ÷ dimension** — the dimension joins to the fact in one metric view.
  Bucket as reported by /importBI.
- **Fact ÷ fact** — each side is aggregated separately to a shared grain (e.g.
  a pre-aggregated view or two metric views), then divided. Bucket as reported
  by /importBI, **capped at ⚠️** (never ✅); 🔧 if there is no shared conformed
  dimension. Describe the approach only as /importBI suggested it; otherwise
  reference a uc-semantics-patterns recipe in the Uplift section.

### Measure Populations

Every DAX measure belongs to exactly one population:

| Population | Definition | In headline rate |
|---|---|---|
| 🔗 External | Calls `EXTERNALMEASURE` — see [External Measures](#external-measures) | No |
| Unused | Not referenced by any visual, other measure, calculation item, or conditional-formatting rule in the file — **only where the unused exclusion applies** (below) | No |
| Display | Returns presentation output, not a business value: conditional-formatting colors / icons, dynamic titles / labels / tooltip text, text built with `FORMAT` or concatenation for display, sort or visibility helpers | No — own buckets and rate |
| Business | Every other measure | Yes |

When a measure fits several, the first match wins: 🔗 External → Unused →
Display → Business.

**The unused exclusion applies only when** the file has visuals **and** its
model is not shared with another file in the run. For model-only files
(`.tmdl`, or `.pbit` with 0 visuals) and for shared models, a measure that
nothing in this file references may still be used by other reports: keep it
as a business or display measure and show
`Not used in this file: <n> (info — not excluded)` instead of an unused count.

### Rates

- **Auto %** = ✅ ÷ business measures — converts with no intervention.
- **Auto with review %** = (✅ + ⚠️) ÷ business measures — the **headline
  rate**; ⚠️ items convert automatically but must be reviewed.
- **🔧 %** = 🔧 ÷ business measures.
- "With patterns" versions use the counts after the Automation Uplift
  reclassification (🔧 → ⚠️), so patterns raise Auto with review %, not Auto %.
- **Uplift (pp)** = Auto with review % (with patterns) − Auto with review %
  (baseline) **in the same row** — for a file, a portfolio view, or the median
  row. Never take a median or average of uplift values.
- **Per-file median row**: each % column is the median of that column's
  per-file values; its Uplift (pp) is the difference of the two medians shown
  in that row.
- **Layer rates** — Auto with review % per layer, each with its item count:
  - **Model layer** — relationships, calculated columns / tables, and M queries
    with transformations or dependencies, counted by Inventory rows.
  - **Measures** — the headline rate above (business measures).
  - **Visual layer** — visuals and interactivity / filter features; `N/A` for
    model-only files.
  - **Display measures** — reported separately; never part of the headline.
- Show every rate with its denominator in the same row or cell. Mark any rate
  computed on fewer than 10 items `(small n)`.

### Root and Dependent 🔧 Measures

- A **root 🔧 measure** is a 🔧 measure whose own DAX blocks conversion — not one
  that is 🔧 only because it references another 🔧 measure.
- A **dependent** is any measure (✅, ⚠️, or 🔧) that references a root
  directly or through other measures. It can only be converted once the root
  is rebuilt. A dependent of several roots is listed under the root it
  references most directly.
- Buckets stay as `/importBI` stated them. Report the number of root 🔧
  measures (the manual effort units) and of blocked dependents.
- Dependencies come from measure references (`[Measure]`) in the DAX —
  from `/importBI` or the model definition.

### Auto Date/Time Tables

Exclude `LocalDateTable_*` and `DateTableTemplate_*` tables, their columns,
and their relationships from every count. If any exist, record
`Auto date/time enabled — <n> hidden date tables (excluded from counts)` as a
Data Modeling row.

### External Measures

A measure whose DAX calls `EXTERNALMEASURE(...)` references a measure defined
in a **remote semantic model** (composite model / DirectQuery to a Power BI
semantic model or Analysis Services). Its logic is not in the assessed file,
so it is never bucketed and never counted in any rate. Mark it 🔗.

- Count only measures that call `EXTERNALMEASURE` directly. Record the remote
  model from the connection (e.g. `AnalysisServices.Database` / Power BI
  semantic model DirectQuery) or the `EXTERNALMEASURE` arguments; if it cannot
  be identified, write `Remote model not identified — verify`. Never guess its
  logic or bucket.
- Local measures that reference 🔗 measures are classified normally, with the
  note "n measures depend on 🔗 external measures" on their Feature
  Classification row.
- Exclude 🔗 measures from every bucket, percentage, Uplift row, outlier share,
  and Manual Adjustment count.
- When the count is > 0, print this callout under the report's metrics table
  and again under the Automation Summary:

  > 🔗 **External measures not included in the conversion rate**: <n> measures
  > use `EXTERNALMEASURE` and reference <remote model name(s)>. Their logic
  > lives in the source semantic model — assess that model separately (e.g.
  > export it as `.pbit` / `.tmdl` and run this skill on it). The automation
  > percentages in this report exclude them.

### Measure Feature Groups

Map every measure group returned by `/importBI` to exactly one of these
names, and use the same names in Data Modeling, Feature Classification,
Automation Uplift, the Manual Adjustment Report, and every cross-file
roll-up. The primary group is the most blocking construct in the measure.
Use `Other — <short name>` only if no group fits.

| # | Feature Group | Population | Typical DAX |
|---|---|---|---|
| 1 | Simple aggregations | Business | SUM, COUNT, AVERAGE, MIN / MAX, DISTINCTCOUNT |
| 2 | CALCULATE with filters | Business | CALCULATE with column / value filters |
| 3 | Time intelligence | Business | TOTALYTD, SAMEPERIODLASTYEAR, DATEADD, DATESINPERIOD |
| 4 | Iterators | Business | SUMX, AVERAGEX, MAXX, FILTER over tables |
| 5 | Filter-context modifiers | Business | ALL, ALLEXCEPT, ALLSELECTED, REMOVEFILTERS, KEEPFILTERS |
| 6 | Inactive relationships | Business | USERELATIONSHIP |
| 7 | Virtual relationships | Business | TREATAS, INTERSECT, CROSSFILTER |
| 8 | Cross-table: fact ÷ dimension | Business | ratio of a fact to a joinable dimension |
| 9 | Cross-table: fact ÷ fact | Business | ratio of two facts at a shared grain |
| 10 | Ranking / Top-N | Business | RANKX, TOPN |
| 11 | Semi-additive | Business | LASTNONBLANK, LASTDATE, closing / opening balance |
| 12 | Calculation groups | Business | calculation items, SELECTEDMEASURE |
| 13 | Field / what-if parameters | Business | NAMEOF, parameter tables, GENERATESERIES |
| 14 | Selection-dependent logic | Business | SELECTEDVALUE, ISINSCOPE, HASONEVALUE, SWITCH(TRUE()) |
| 15 | Conditional formatting | Display | color / icon / data-bar measures |
| 16 | Dynamic titles & labels | Display | text measures for titles, labels, tooltips |

### Shared and Duplicate Models

Bulk runs only. Compare the MODEL SIGNATURE lines of the digests:

- **Identical** — same table list and same measure count.
- **Variant** — same table list and measure counts within ±10%.

Files that match form one semantic model. Pick the file with the most
business measures as its representative.

- Individual Reports stay per file, with each file's own rates.
- Portfolio totals, rates, Uplift, and outlier shares count each model once,
  through its representative.
- The unused exclusion does not apply to files of a shared model (see
  [Measure Populations](#measure-populations)).
- List every group in the Unique Semantic Models table of Template A.

## Report Structure

These templates are the mandatory output format — copy the heading hierarchy
verbatim. Details such as fact-domain grouping or source views go INSIDE the
tables, never in new sections; relationship details go only in the grouped
Relationships table. Only list rows with a count > 0.

Formatting illustrations (not statements of what `/importBI` supports):
"Simple aggregations | 18 | ✅ Auto" · "Relationships (M:1, active) | 13 | ✅ Auto
| <handling as stated by /importBI>" · "Conditional formatting | 29 | 🔧 Manual".

- **Single file** — one Template B (full).
- **Bulk (2+ files)** — Template A, then one Template B (full, or compact for
  6+ files) per file, in the same order as the Per-Workbook Automation table.

Each report starts with its own `#` title, so section headings are identical
in single-file and bulk runs.

### Template A — Migration Summary Report (bulk only)

```markdown
# Migration Summary Report

**Date scanned**: <date> | **Files**: <count> | **Report mode**: full / compact
**/importBI**: <version, or "version not reported"> | **Reference patterns**: <read live — n patterns checked / Pattern repo unavailable>

| Metric | Total |
|---|---|
| Files (.pbit / .tmdl) | ... / ... |
| Unique semantic models | ... |
| Pages | ... |
| Business measures | ... |
| Display measures (not in headline rate) | ... |
| Unused measures (excluded) | ... |
| 🔗 External measures (EXTERNALMEASURE, not in rates) | ... |
| Root 🔧 measures (manual effort units) / blocked dependents | ... / ... |
| Calculated columns / tables | ... / ... |
| Physical data sources | ... |

<🔗 portfolio callout if any file has external measures — "<n> external
measures in <n> files reference <n> remote semantic model(s); not included in
any conversion rate below — see Cross-cutting Findings.">

## Unique Semantic Models

<"Each file has its own semantic model." or:>

| Semantic Model | Files | Match | Business Measures | Counted Through |
|---|---|---|---|---|
| <model> | <file, file> | Identical / Variant (±n measures) | ... | <representative file> |

## Per-Workbook Automation

| # | Workbook | Complexity (score) | Business Measures | Auto % | Auto with review % | 🔧 % | Root 🔧 | Auto with review % (with patterns) | Uplift (pp) | Outlier |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | ... | High (9) | ... | ...% | ...% | ...% | ... | ...% | +... | — / ⚑ <reason> |

**Distribution (Auto with review %, baseline)**: <n> files ≥ 80% · <n> files 50–80% · <n> files < 50%

## Portfolio Automation Summary

| View | Files / Models | Business Measures | ✅ | ⚠️ | 🔧 | Root 🔧 | Auto % | Auto with review % (baseline) | Auto with review % (with patterns) | Uplift (pp) |
|---|---|---|---|---|---|---|---|---|---|---|
| All files (unique models, measure-weighted) | ... / ... | ... | ... | ... | ... | ... | ...% | ...% | ...% | +... |
| Excluding outliers (measure-weighted) | ... / ... | ... | ... | ... | ... | ... | ...% | ...% | ...% | +... |
| Per-file median | ... / — | — | — | — | — | — | ...% | ...% | ...% | +... |

## Automation Uplift with Reference Patterns

Roll-up of the per-file Uplift tables (each model once).

| 🔧 Feature Group | Applicable Pattern | Recipe | Files | Measures Reclassified to ⚠️ |
|---|---|---|---|---|
| <feature group> | <pattern name from repo> | <repo folder / recipe> | <file, file> | <n> |

> **Portfolio automation uplift**: applying
> [uc-semantics-patterns](https://github.com/databricks-solutions/uc-semantics-patterns)
> recipes raises Auto with review % from **<baseline>%** to
> **<with-patterns>%** (**+<delta>pp**) across all files, and from <x>% to <y>%
> excluding outliers. Largest gains: <file (+pp)>, <file (+pp)>.

<or the no-match / repo-unavailable line from Reference Patterns>

## Outliers

<"None — no file meets the outlier rules" or, per flagged file:>

| Workbook | Reason | Share of Portfolio Business Measures | Business Measures | ✅ | ⚠️ | 🔧 | Auto with review % (baseline) | Auto with review % (with patterns) | Effect on Portfolio |
|---|---|---|---|---|---|---|---|---|---|
| ... | Size: ...% of measures / Rate: ±..pp vs. portfolio | ...% | ... | ... | ... | ... | ...% | ...% | Lowers / raises the all-files rate by ...pp |

> **Reading the portfolio rate**: <1–2 sentences — e.g. "The all-files rate of
> 48% is driven by <outlier>; the remaining <n> files average 79%.">

## Cross-cutting Findings

- **Shared source tables / non-Databricks sources**: <listed once, with files using them>
- **Unresolved parameters across files**: <list or "None">
- **🔗 External semantic models**: <remote model — n external measures, files
  using it — "assess separately"; each remote model listed once, or "None">
- **Auto date/time**: <enabled in n files, or "None">
- **Recurring 🔧 groups**: <feature group — n files, n root 🔧, n 🔧 measures>

## Recommended Migration Sequence

| Wave | Workbooks | Why |
|---|---|---|
| 1 — Quick wins | ... | High Auto with review %, Low complexity |
| 2 | ... | ... |
| 3 — Redesign | ... | Outliers / many root 🔧 |
```

### Outlier Rules

Apply only when the run has **3+ files** (one representative per shared
model). Flag a file (⚑) when either is true:

1. **Size outlier** — the file holds **> 40%** of the portfolio's business
   measures **and** more than **2×** the average share (100% ÷ number of
   unique models).
2. **Rate outlier** — the file has **≥ 10 business measures** and its baseline
   Auto with review % differs by **more than 20 percentage points** from the
   measure-weighted rate of all files that are not size outliers. (Find size
   outliers first, compute that reference rate once, then test each file.)

Files with fewer than 10 business measures are never rate outliers; mark
their rates `(small n)`. Show every flagged file in the **Outliers** table and
keep it out of the "Excluding outliers" row. Never let an outlier's rate stand
in for the portfolio: the Reading-the-portfolio-rate line must name it.

### Template B — Individual Report (full)

Used for a single-file run, for every file in a 2–5 file run, and for any file
the user picks in Step 6.

```markdown
# Individual Report — <file name>

**File**: <file name> | **Type**: .pbit / .tmdl | **Storage**: Import / DirectQuery / composite / live | **Date scanned**: <date>
**/importBI**: <version, or "version not reported"> | **Reference patterns**: <read live — n patterns checked / Pattern repo unavailable>

| Metric | Count |
|---|---|
| Pages / visuals | ... / ... |
| Fact / Dimension tables (excl. auto date/time) | ... / ... |
| Auto date/time tables (excluded) | ... |
| Physical data sources | ... |
| Business measures | ... |
| Display measures | ... |
| Unused measures (excluded) — or "Not used in this file (info)" | ... |
| 🔗 External measures (EXTERNALMEASURE, not in rates) | ... |
| Root 🔧 measures / blocked dependents | ... / ... |
| Calculated columns / tables | ... / ... |
| Calculation groups | ... |
| RLS roles (static / dynamic) / OLS | ... / ... |

<🔗 External measures callout if count > 0>

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

### Non-Databricks Sources

<source type + count per type, or "None — all sources are Databricks">

### External Semantic Models

<"None — no EXTERNALMEASURE" or:>

| Remote Semantic Model | 🔗 External Measures | Local Measures Depending on Them | Action |
|---|---|---|---|
| <model name / "Remote model not identified — verify"> | ... | ... | Assess the source model separately |

## Executive Overview

**Overall Complexity**: <Low / Medium / High> (score <n>) — <score breakdown, e.g. "root 🔧 2 · measures 1 · sources 1 · RLS 2">

**Rationale**: <2–3 sentences>

### Complexity Drivers (ranked by impact)

| # | Driver | Count | Impact | Resolution |
|---|---|---|---|---|
| 1 | ... | ... | 🔴/🟠/🟡 | ... |

## Feature Inventory

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

### Data Modeling

Measures by [feature group](#measure-feature-groups) — calculated columns go
in the next table.

| Feature Group | Population | Count | Classification | Note |
|---|---|---|---|---|
| Simple aggregations | Business | ... | ✅/⚠️/🔧 | ... |
| Cross-table: fact ÷ fact | Business | ... | ⚠️/🔧 (never ✅) | ... |
| Conditional formatting | Display | ... | ✅/⚠️/🔧 | ... |
| Auto date/time enabled — <n> hidden date tables (excluded from counts) | — | ... | — | Only if present |

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

Classify every Inventory feature using the [Buckets](#buckets).

### Feature Classification

| Feature (from Inventory) | Population | Count | Bucket | /importBI Behavior |
|---|---|---|---|---|
| ... | Business / Display / Model / Visual | ... | ✅/⚠️/🔧 | One line, as stated by /importBI (or "Not stated by /importBI — verify") |

### Automation Summary

| Bucket | Features | Business Measures | % of Business Measures |
|---|---|---|---|
| ✅ Auto | ... | ... | ...% |
| ⚠️ Auto + workaround | ... | ... | ...% |
| 🔧 Manual | ... | ... | ...% |

**Auto %**: <n>% · **Auto with review %**: <n>% (of <n> business measures)
**Root 🔧 measures**: <n> roots block <n> dependents (<n> of them 🔧)

| Layer | Items | ✅ | ⚠️ | 🔧 | Auto with review % |
|---|---|---|---|---|---|
| Model layer | ... | ... | ... | ... | ...% |
| Measures (business) | ... | ... | ... | ... | ...% |
| Visual layer | ... | ... | ... | ... | ...% / N/A |
| Display measures | ... | ... | ... | ... | ...% |

**Unused measures (excluded)**: <n> — or `Not used in this file: <n> (info — not excluded)`
**🔗 External measures (excluded — assess source model separately)**: <n>
**Calculated columns / tables (Model layer, not in measure %)**: ✅ <n> / ⚠️ <n> / 🔧 <n>

## Automation Uplift with Reference Patterns

| 🔧 Feature Group | Measures | Applicable Pattern | Reclassified To | Recipe |
|---|---|---|---|---|
| <feature group from Classification> | <n> | <pattern name from repo> | ⚠️ Auto + workaround | <repo folder / recipe, short description> |

<or only the no-match / repo-unavailable line from Reference Patterns — then
omit the Revised Automation Summary and the callout below>

**Revised Automation Summary (with patterns)**:

| Bucket | Business Measures (baseline) | Business Measures (with patterns) | % Baseline | % With Patterns |
|---|---|---|---|---|
| ✅ Auto | ... | ... | ...% | ...% |
| ⚠️ Auto + workaround | ... | ... | ...% | ...% |
| 🔧 Manual | ... | ... | ...% | ...% |

> **Automation uplift**: Applying
> [uc-semantics-patterns](https://github.com/databricks-solutions/uc-semantics-patterns)
> recipes during migration can raise Auto with review % from **<baseline>%** to
> **<with-patterns>%** (a **+<delta>pp** improvement), potentially shifting the
> overall complexity from <baseline rating> to <new rating>.

## Readiness Summary

**Primary blockers** (root 🔧 measures, by feature group):
- <list>

**Data prerequisites**:
- <UC tables/sources that must exist before conversion>
- <🔗 remote semantic model(s) to assess separately, if any>

**Pre-conversion remediation** (🔧 only):
- <what must be redesigned before /importBI can process the rest>

**Post-conversion manual work** (🔧 visuals/interaction):
- <unsupported visuals, custom visuals, complex interactivity>

**Recommended next steps**:
1. Resolve prerequisites (parameters, source access)
2. Rebuild root 🔧 measures (this unblocks their dependents)
3. Run /importBI for ✅ and ⚠️ items
4. Review ⚠️ workaround results
5. Build net-new visuals if model-only template

### Specific Risks
- <list>

### Validation Checks
- <list of things to verify after conversion>
```

### Template B-compact — Individual Report (6+ files)

At most **25 lines** per file. Same numbers as the full Template B; inventory
and prerequisite detail roll up into the Migration Summary Report's
Cross-cutting Findings. The full report for any file is available in Step 6.

```markdown
# Individual Report — <file name>

**Type**: .pbit / .tmdl | **Model**: <semantic model> | **Complexity**: <Low / Medium / High> (<score>) | **Outlier**: — / ⚑ <reason>
**Reference patterns**: <read live — n patterns checked / Pattern repo unavailable>

**Metrics**: <p> pages · <b> business + <d> display measures (+<u> unused, <e> 🔗 external) · <r> root 🔧 blocking <k> · <c> / <t> calc columns / tables · <s> non-Databricks sources · RLS <n>

<one-line 🔗 callout if external measures > 0: "🔗 <e> EXTERNALMEASURE measures (<remote model>) not in the rate — assess the source model separately.">

## Automation Classification

**⚠️ groups**: <group (n)>, … | **🔧 groups**: <group (n roots / n measures)>, …

## Automation Summary & Uplift

| Bucket | Business Measures (baseline) | % | Business Measures (with patterns) | % |
|---|---|---|---|---|
| ✅ Auto | ... | ...% | ... | ...% |
| ⚠️ Auto + workaround | ... | ...% | ... | ...% |
| 🔧 Manual | ... | ...% | ... | ...% |

**Auto %**: <n>% · **Auto with review %**: <baseline>% → <with patterns>% (+<delta>pp) via <recipe (n measures)>, … / "No matching pattern — no uplift" / "Pattern repo unavailable"

**Layers** (Auto with review %): Model <x>% (n) · Visual <y>% (n) / N/A · Display <z>% (n)

**Primary blockers** (root 🔧, top 3): <group — n roots>, …
```

> **REMINDER**: The templates above are the COMPLETE report — see Rules 1–2.

## Manual Adjustment Report Structure

Produced after the main report, when requested in the first prompt or
accepted in Step 6 — with the same structure and check either way, so the user
never needs to describe the format. In a bulk run it covers all files, or only
the file(s) the user selected. This is the only place where individual measure
names are listed.

- Organised by **root 🔧 measures**; each root lists the measures it blocks, so
  the manual effort is the number of roots.
- One `##` group per [feature group](#measure-feature-groups), in the same
  names and order as Feature Classification; display groups come after
  business groups.
- A 🔧 measure that is 🔧 only because it references a root is listed under
  that root (marked 🔧 in the Blocks column), not as its own row.
- Reasons come from the `/importBI` output — the blocking DAX constructs it
  reported.
- 🔗 External measures are in no group; if any exist, list them in a separate
  section after the 🔧 groups, outside the consistency totals.

```markdown
# 🔧 Manual Adjustment Report

**Root 🔧 measures**: <n> (manual effort units) | **Blocked dependents**: <n> (of which 🔧: <n>)

## <Feature group> — <n> roots, <n> 🔧 measures

| Root Measure | Table | Workbook (bulk only) | Reason | Blocks |
|---|---|---|---|---|
| Matrix Display | <table> | <workbook> | TREATAS on literals + ISINSCOPE + FORMAT text | 3: [Margin %] 🔧, [Margin LY], [Margin Δ] |

## <next feature group> — <n> roots, <n> 🔧 measures
...

**Per-workbook subtotals** (bulk only): <workbook — n roots, n 🔧 measures>; …

## 🔗 External measures — not in the 🔧 count (only if any)

| Measure | Workbook (bulk only) | Remote Semantic Model |
|---|---|---|
| ... | ... | ... — assess separately |

**Consistency**: <n> roots + <n> 🔧 dependents = <total> 🔧 measures = 🔧 in the
Automation Summary (business <n> + display <n>); group counts match the
Feature Classification table.
```

**Manual Adjustment consistency check (mandatory, before printing):**

1. Roots + 🔧 dependents listed = the 🔧 measure count (business + display) in
   the Automation Summary.
2. Every 🔧 measure appears exactly once — as a root row or as a 🔧 entry in
   one root's Blocks column.
3. For every feature group, the 🔧 count in Feature Classification equals the
   number of 🔧 measures of that group in this report, whether listed as a
   root or as a dependent.
4. Every root has a table and a non-empty reason.
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
| Root 🔧 measures | 0 | 1–5 | 6–15 | 16+ |
| Business measures | < 20 | 20–99 | 100+ | — |
| Non-Databricks source types | 0 | 1 | 2+ | — |
| Row / object-level security | None | Static RLS | Dynamic RLS or OLS | — |
| Composite / DirectQuery / live connection / 🔗 external measures | None | — | Present | — |
| Calculation groups, field parameters | None | One of them | Both | — |
| Fact ÷ fact measures, M:M or bidirectional relationships | None | Present | — | — |
| Custom or unsupported visuals | 0 | 1–3 | 4+ | — |
| Model or Visual layer Auto with review % below 50% | Neither | One | Both | — |

**Rating**: 0–3 **Low** · 4–7 **Medium** · 8+ **High**.

## Reference Patterns

Read `https://github.com/databricks-solutions/uc-semantics-patterns` live,
**once per run**, before building any report (Step 4), and reuse that pattern
list for every file. Never rely on a remembered or cached list — the repo
changes — and never skip the read because the run is long.

1. Read the repo's root `README.md`.
2. Follow its links to the pattern folders and read the recipe for any pattern
   that may match a 🔧 item (e.g. calculation groups, semi-additive measures,
   fact ÷ fact ratios, ranking, segmentation).
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
