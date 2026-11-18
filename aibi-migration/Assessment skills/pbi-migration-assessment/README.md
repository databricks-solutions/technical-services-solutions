# Power BI Migration Assessment

A read-only profiling skill that assesses Power BI report templates (`.pbit`) and
semantic models (`.tmdl`) for migration to Databricks AI/BI dashboards and metric
views. It profiles each report, classifies every
feature as Auto / Auto + workaround / Manual (anchored to the
`/importBI` migration agent), and estimates the automation uplift from applying
[uc-semantics-patterns](https://github.com/databricks-solutions/uc-semantics-patterns).

It **does not convert anything** — no datasets, no widgets, no dashboards are created.

**Current version**: 2.0.0 — see [CHANGELOG.md](CHANGELOG.md).

> [!CAUTION]
> Results are produced by an LLM-based agent under active development and are
> **indicative only** — review and validate them before planning a migration. See
> the full [Disclaimer](../README.md#disclaimer).

For installation, invocation, prerequisites (including GitHub access for the
Automation Uplift), and troubleshooting, see the [main README](../README.md).

## Supported file types

| Type | What it is | Profiled as |
|---|---|---|
| `.pbit` | Power BI report template (model + report layout, no data) | Full report |
| `.tmdl` | Semantic model definition (Tabular Model Definition Language) | Model-only |

A `.tmdl` file, or a `.pbit` with 0 visuals, is treated as a **model-only
template**: its visualization, interactivity, and filter sections collapse into a
single callout. `/importBI` converts a `.tmdl` into metric views, not a dashboard.
See [Import BI files using Genie Code](https://docs.databricks.com/aws/en/dashboards/manage/import-bi)
for the file types `/importBI` supports.

## Example prompts

Start prompts with `@pbi-migration-assessment` so the skill is used.

Quick start:

```
@pbi-migration-assessment assess the Power BI reports in /Volumes/<catalog>/<schema>/<volume>/
```

Run the assessment and get the 🔧 Manual Adjustment Report in one pass:

```
@pbi-migration-assessment assess the Power BI report(s) <attached file | in
/Volumes/<catalog>/<schema>/<volume>/> and include the 🔧 Manual Adjustment Report.
```

After a bulk run of 6+ files, get the full Individual Report for a chosen file:

```
@pbi-migration-assessment show the full Individual Report for <file name>.
```

Request the 🔧 Manual Adjustment Report later, in the same conversation:

```
@pbi-migration-assessment create the 🔧 Manual Adjustment Report.
```

If the run falls back to a plain `/importBI` assessment:

```
@pbi-migration-assessment wrap up the migration report.
```

Convert with the patterns repo (when the Automation Uplift section shows a
positive uplift):

```
/importBI Convert the report [attach the report, or provide a volume path], as additional
reference for the calculations conversion use https://github.com/databricks-solutions/uc-semantics-patterns
```

## What it does

1. **Enumerate** — lists all `.pbit` / `.tmdl` files at the Volume path (or uses
   attached files) and reports the count before proceeding.
2. **Prerequisites check** — scans M-queries and flags parameters that must
   resolve before conversion, non-Databricks sources (which need data migration
   or federation), M-query transformations and dependent queries, query
   dependencies (a query another query uses is never marked omittable), and the
   source-table inventory. Measures that use `EXTERNALMEASURE` are counted and
   their remote semantic model recorded.
3. **Profile** — hands each file to the `/importBI` specialist in **profile-only**
   mode, one file at a time, asking it to state how it would handle M-query
   transformations, relationships (grouped by pattern), calculated columns and
   tables, cross-table measures (fact ÷ dimension vs fact ÷ fact), unconvertible
   measures with their blocking DAX construct, and unused measures. All files
   are profiled in one run — you only see a `Profiled <i>/<n>` progress line per
   file, with no need to reply "continue". Each answer is reduced to a short
   structured digest, so large batches fit.
4. **Consolidate** — reads uc-semantics-patterns live once per run (every report
   header shows whether it was read), builds an Individual
   Report for each file (with its own Automation Summary and Uplift), then
   aggregates them into the Migration Summary Report and flags outliers.
5. **Consistency check (mandatory, silent)** — reconciles every measure
   population and bucket count, keeps calculated columns and auto date/time
   tables out of measure counts, counts each measure once under its primary
   feature group, checks root 🔧 + dependents, the complexity score, and that
   every handling cell traces to the `/importBI` output, and — in bulk runs —
   that portfolio counts equal the sum over unique semantic models.
6. **Follow-ups** — offers the 🔧 Manual Adjustment Report (printed straight away
   if requested up front). For 6+ files it also offers the full Individual Report
   for files you choose.

## Output

The report layout depends on how many files are assessed:

| Files | Report |
|---|---|
| 1 | One full Individual Report |
| 2–5 | Migration Summary Report + a full Individual Report per file |
| 6+ | Migration Summary Report + a compact Individual Report per file; ask for the full report of any file afterwards |

**Migration Summary Report** (bulk runs, opens the report):

- **Unique Semantic Models** — files that share the same (or a near-identical)
  model are grouped and counted once in every portfolio total.
- **Per-Workbook Automation** — each file's complexity score, Auto % and Auto with
  review % (baseline and with patterns), root 🔧 measures, uplift, and outlier
  flag, plus a distribution line.
- **Portfolio Automation Summary** — the rate for all files (unique models),
  excluding outliers, and the per-file median, so one large or unusual file
  doesn't skew the overall picture.
- **Automation Uplift with Reference Patterns** — roll-up of the per-file uplift:
  which uc-semantics-patterns recipes apply, in which files, and the portfolio
  Auto with review % before and after patterns.
- **Outliers** — files flagged (3+ file runs) because they hold more than 40% of
  the portfolio's business measures and more than twice the average share, or
  (with at least 10 business measures) their rate is more than 20pp away from
  the rest. Their statistics are shown separately, with their effect on the
  portfolio rate.
- **Cross-cutting Findings** and a **Recommended Migration Sequence**.

**Individual Report** (one per file):

- **Prerequisites** — M-query parameters, source tables, M-query transformations,
  non-Databricks sources.
- **Executive Overview** — complexity rating with its score and breakdown, and
  complexity drivers ranked by impact.
- **Feature Inventory** — data sources, grouped relationships, data modeling,
  calculated columns & tables, visualizations, interactivity & filters.
- **Automation Classification** — ✅ Auto / ⚠️ Auto + workaround / 🔧 Manual per
  feature group, with an Automation Summary, root 🔧 count, and layer rates.
- **Automation Uplift with Reference Patterns** — 🔧 items that a
  uc-semantics-patterns recipe can reclassify, and the percentage-point uplift.
- **Readiness Summary** — blockers, specific risks, and validation checks.

The **compact** Individual Report (6+ files, up to ~25 lines each) keeps a
metrics line, the ⚠️/🔧 groups, a combined Automation Summary & Uplift table, and
the top root 🔧 blockers. Feature Inventory and prerequisite detail roll up into the
Migration Summary Report; ask for the full report of any file afterwards.

Individual measure names are **not** listed in the main report. They appear only
in the optional **🔧 Manual Adjustment Report**, which is organised by **root 🔧
measures** — the measures whose own DAX blocks conversion — grouped the same way
as the Feature Classification table. Each root has its table, a short reason
(e.g. `Matrix Display | TREATAS on literals + ISINSCOPE + FORMAT text`), and the
measures it blocks. It ends with a consistency line checked against the main report's 🔧
counts — with per-workbook subtotals in bulk runs. This is the default format —
whether you ask for it in the first prompt or later — so the prompt doesn't need
to describe it. In a bulk run you can ask for it for all files or for selected
files.

## How the numbers are counted

- **Auto %** = ✅ ÷ business measures. **Auto with review %** = (✅ + ⚠️) ÷ business
  measures — the headline rate; ⚠️ items convert automatically but need review.
  Rates on fewer than 10 items are marked `(small n)`.
- **Business vs display measures** — formatting, color, and dynamic title / label
  measures are reported separately and are not in the headline rate.
- **Unused measures** are excluded only when the file has visuals and its model
  isn't shared. For `.tmdl` files, model-only `.pbit` files, and shared models
  they're shown as "not used in this file" and stay in the counts, because other
  reports may use them.
- **Root 🔧 measures** are the manual effort units: a 🔧 measure that is blocked
  only because it references another 🔧 measure is listed under that root.
- **Feature groups** come from a fixed list (simple aggregations, time
  intelligence, iterators, calculation groups, …), so groups compare across files
  and runs.
- **Auto date/time tables** (`LocalDateTable_*`, `DateTableTemplate_*`) are
  excluded from all counts and flagged as a modeling finding.
- **Complexity** is a points score (root 🔧 measures, measure count, sources,
  security, composite / DirectQuery, calculation groups, fact ÷ fact and M:M
  relationships, custom visuals, layer rates): 0–3 Low, 4–7 Medium, 8+ High.

## Notes

- **`/importBI` is the source of truth.** Every ✅/⚠️/🔧 bucket and handling cell
  comes from the `/importBI` profile; anything it did not state is marked
  `Not stated by /importBI — verify` and classified 🔧 Manual.
- **Calculated columns are not measures** — they are reported in their own block
  and never counted in measure totals.
- **🔗 External measures (`EXTERNALMEASURE`) are not in the conversion rate.**
  Measures that call `EXTERNALMEASURE` take their logic from a remote semantic
  model (composite model / DirectQuery to a Power BI semantic model or Analysis
  Services). The report flags them, lists the remote model(s), and excludes them
  from every ✅/⚠️/🔧 count and percentage. Assess the source semantic model
  separately — e.g. export it as `.pbit` / `.tmdl` and run this skill on it.
- **Power BI only.** Tableau files use a separate skill
  (`tableau-migration-assessment`).
- `SKILL.md` is the authoritative specification; if this README diverges from it,
  `SKILL.md` wins.
