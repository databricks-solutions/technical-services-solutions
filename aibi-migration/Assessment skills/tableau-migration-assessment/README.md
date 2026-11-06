# Tableau Migration Assessment

A read-only profiling skill that assesses Tableau files for migration to
Databricks AI/BI dashboards. It profiles each file, classifies every feature as
Auto / Auto + workaround / Manual (anchored to the `/importBI`
migration agent), and estimates the automation uplift from applying
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
| `.twb` | Raw workbook XML | Full workbook |
| `.twbx` | Zipped workbook (XML + extracts + resources) | Full workbook |
| `.tds` | Raw data-source definition (connection + calc fields) | Model-only |
| `.tdsx` | Zipped data source (`.tds` + extract) | Model-only |

`.tds` / `.tdsx` have no worksheets, dashboards, filters, or actions, so their
visual/interaction sections collapse into a single model-only callout.

## Example prompts

Start prompts with `@tableau-migration-assessment` so the skill is used.

Assess a UC Volume (bulk):
```
@tableau-migration-assessment assess the Tableau files in /Volumes/catalog/schema/volume/ for AI/BI migration.
```

Assess attached files:
```
@tableau-migration-assessment profile these workbooks for migration complexity. <attach .twb/.twbx/.tds/.tdsx files>
```

Run the assessment and get the 🔧 Manual Adjustment Report in one pass:
```
@tableau-migration-assessment assess the Tableau files in /Volumes/catalog/schema/volume/
and include the 🔧 Manual Adjustment Report.
```

If the run falls back to a plain `/importBI` assessment:
```
@tableau-migration-assessment wrap up the migration report.
```

Convert with the patterns repo (when the Automation Uplift section shows a
positive uplift):
```
/importBI Convert the workbook [attach the file, or provide a volume path], as additional
reference for the calculations conversion use https://github.com/databricks-solutions/uc-semantics-patterns
```

## What it does

1. **Enumerate** — lists all `.twb` / `.twbx` / `.tds` / `.tdsx` files at the path
   (or uses attached files) and reports the count before proceeding.
2. **Prerequisites check** — flags connection strings/parameters to resolve,
   non-Databricks sources (and their in-source transforms — custom SQL, unions,
   cross-DB joins, filters — to rebuild as source views), `.hyper` extracts, the
   source-table inventory, source dependencies (never drop a source another object
   uses), and relationship/join quality (disconnected sources, fact-to-fact,
   mismatched keys, many-to-many, cardinality overrides).
3. **Profile** — hands each file to the `/importBI` specialist in **profile-only**
   mode, asking it to state how it would handle each category (transformations,
   relationships by pattern, calculation families, row-level calcs/groups/bins/sets,
   cross-datasource ratios, unconvertible calcs with names, unused, display & gating
   calcs, calc dependencies). With **2+ files, profiling runs in parallel batches of
   up to 4 at a time where the environment supports concurrent handoffs**, otherwise
   sequentially; a single file is profiled directly. All files are profiled in one
   run — you only see a `Profiled <i>/<n>` progress line per file, with no need to
   reply "continue". Each answer is reduced to a short structured digest, so large
   batches fit.
4. **Consolidate** — reads uc-semantics-patterns live once per run (every report
   header shows whether it was read), builds an Individual Report for each file
   (with its own Automation Summary and Uplift), groups data sources shared across
   files, then aggregates everything into the Migration Summary Report and flags
   outliers.
5. **Consistency check (mandatory, silent)** — reconciles every calc population and
   bucket count, checks that calculation-family counts add up to the total, keeps
   row-level calcs and model features out of the calc %, checks root 🔧 + dependents
   and the complexity score, and — in bulk runs — that portfolio counts equal the sum
   over unique data sources.
6. **Follow-ups** — offers the 🔧 Manual Adjustment Report (printed straight away if
   requested up front). For 6+ files it also offers the full Individual Report for
   files you choose.

## Output

The report layout depends on how many files are assessed:

| Files | Report |
|---|---|
| 1 | One full Individual Report |
| 2–5 | Migration Summary Report + a full Individual Report per file |
| 6+ | Migration Summary Report + a compact Individual Report per file; ask for the full report of any file afterwards |

**Migration Summary Report** (bulk runs, opens the report):

- **Unique Data Sources** — data sources shared across files (e.g. a `.tdsx` and the
  workbooks that use it) are grouped and counted once in every portfolio total.
- **Complexity Distribution** and overall portfolio complexity.
- **Per-Workbook Automation** — each file's complexity score, Auto % and Auto with
  review % (baseline and with patterns), root 🔧 calcs, uplift, and outlier flag,
  plus a distribution line.
- **Portfolio Automation Summary** — the rate for all files (unique data sources),
  excluding outliers, and the per-file median.
- **Automation Uplift with Reference Patterns** — roll-up of the per-file uplift.
- **Outliers** — files flagged (3+ file runs) because they hold more than 40% of the
  portfolio's classified calcs and more than twice the average share, or (with at
  least 10 classified calcs) their rate is more than 20pp away from the rest. Their
  statistics are shown separately.
- **Cross-cutting Findings** and a **Recommended Migration Sequence**.

**Individual Report** (one per file): metrics, prerequisites (including a **Data
Source Transformations** table), executive overview with the complexity score and
drivers, a feature inventory with a grouped **Relationships** table and a separate
**Row-level Calculations, Groups, Bins & Sets** block, Automation Classification
(✅ Auto / ⚠️ Auto + workaround / 🔧 Manual) with layer rates, Automation Uplift with
reference patterns, and a readiness summary. The **compact** form (6+ files, up to
~25 lines each) keeps a metrics line, the ⚠️/🔧 families, a combined Automation
Summary & Uplift table, and the top root 🔧 blockers.

Individual 🔧 item names are **not** inlined in the main report — they appear only
in the optional **🔧 Manual Adjustment Report**, organised by **root 🔧 calcs** (the
calcs whose own formula blocks conversion), each with its data source, reason, and
the calcs it blocks — no top-N cap. It uses the same format whether you ask for it
in the first prompt or later.

The report is returned in chat (summary first, then the per-file sections). You can
optionally ask to save the results in MD and HTML format in your user folder.

## How the numbers are counted

- **Auto %** = ✅ ÷ classified calcs (aggregate calcs, LODs, table calcs,
  cross-datasource ratios). **Auto with review %** = (✅ + ⚠️) ÷ classified calcs — the
  headline rate; ⚠️ items convert automatically but need review. Rates on fewer than
  10 items are marked `(small n)`.
- **Display & gating calcs** — color / shape / label / title calcs and visibility /
  zone / action flags — are reported separately and not in the headline rate.
  Gating calcs are still assessed for readiness.
- **Unused calcs** are excluded only when the file has worksheets and its data
  source isn't shared. For `.tds` / `.tdsx` files, model-only workbooks, and shared
  data sources they're shown as "not used in this file" and stay in the counts.
- **Root 🔧 calcs** are the manual effort units: a 🔧 calc blocked only because it
  references another 🔧 calc is listed under that root.
- **Calculation families** come from a fixed list (simple aggregations, FIXED and
  INCLUDE / EXCLUDE LODs, constant and dynamic LOOKUP, analytical and
  mark-positioning windows, cross-datasource ratios, row-level, display, gating), so
  they compare across files and runs.
- **Complexity** is a points score (root 🔧 calcs, calc volume and depth, sources and
  extracts, blends, LODs, table-calc types, actions and dynamic zone visibility,
  user filters, worksheet volume, advanced visuals, layer rates): 0–3 Low, 4–7
  Medium, 8+ High.

## Notes

- **Read-only.** The skill never converts, creates datasets, or creates widgets —
  this constraint applies to parallel subagents too.
- **`/importBI` is the source of truth.** Every ✅/⚠️/🔧 bucket and handling cell
  comes from the `/importBI` profile; anything it did not state is marked
  `Not stated by /importBI — verify` and classified 🔧 Manual.
- **Tableau only.** Power BI files use a separate framework
  (`pbi-migration-assessment`).
- Classification reflects what `/importBI` reports **today**; the Automation Uplift
  section shows the additional automation achievable with uc-semantics-patterns
  recipes (read live) on top of that baseline.
- `SKILL.md` is the authoritative specification; if this README diverges from it,
  `SKILL.md` wins.
