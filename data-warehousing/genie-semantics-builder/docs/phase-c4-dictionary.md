# Phase c4: Metric dictionary import and template

Status: plan, not approved. Date: 2026-11-05.

## Goal

Teams often keep their metric definitions in a spreadsheet or a wiki page. The app should read that
dictionary once and reuse it everywhere, so a metric view uses the team's own names, formulas and
synonyms, and the tables get better descriptions.

Decisions (2026-11-05):

- The dictionary belongs to the **parent project**. Every sub-project reuses it.
- Formats: **Excel (.xlsx), CSV and Markdown**.
- Definitions that map to columns become **UC table and column comments**, through the existing fix flow
  with the user's approval.
- Built after phase d step 5.

## What a dictionary holds

One row per entry. Only `name` and `definition` are required; the rest improves the result.

| Column | Meaning |
|---|---|
| `kind` | `metric`, `dimension` or `term` (glossary only). Default `metric`. |
| `name` | Business name, for example Net Revenue. |
| `display_name` | Label for charts. |
| `definition` | What it means, in business words. |
| `formula` | How it is computed, in words or SQL, for example `SUM(extended_price * (1 - discount))`. |
| `aggregation` | sum, count, count_distinct, avg, min, max, ratio, other. |
| `format` | currency (with code), percentage, number, date. |
| `synonyms` | Other words users type, separated by `;`. |
| `grain` | day, week, month, quarter, year. |
| `source` | `catalog.schema.table.column` the value comes from, when known. |
| `owner` | Person or team that owns the definition. |
| `status` | draft, approved, certified. |

Column names are matched without case and with common aliases (`description` for `definition`,
`expression` for `formula`, and so on). Extra columns are kept as notes.

## Steps

### Step 1: Template

- Download **Excel** (sheets `Metrics`, `Dimensions`, `Glossary`, `Read me`) and **Markdown** (one table per
  section) from the project page.
- The template follows the metric view fields, so a filled row passes the best-practice rules of phase d
  step 4: description, synonyms, display name, format, safe ratios.
- The `Read me` sheet explains each column with an example row from TPC-H.

### Step 2: Import

- Upload on the project page. Server-side parsing only. Limits: 5 MB, 2,000 rows, 50 columns, text cells up to
  4,000 characters. Formulas in Excel cells are read as their cached value, never run. Macros are ignored.
- Markdown: every pipe table with a `name` column; a heading becomes the `kind` when it says Metrics,
  Dimensions or Glossary.
- A preview shows the rows, the mapped columns and the problems (missing name, duplicate name, unknown
  aggregation). The user confirms the import; nothing is stored before that.
- Stored in Lakebase `gsb.dictionary_entry` (project, kind, name, fields, source file name, imported by and at).
  Importing again shows a diff: added, changed and removed entries.
- Excel library: picked in this step after a check of its advisories (candidates: `exceljs`,
  `read-excel-file`). CSV and Markdown need no library.

### Step 3: Reuse in the app

- **Intent & Context:** the chat and discovery get the dictionary entries that match the sources, so ideas and
  briefs use the team's names and formulas. Entries already in the brief are marked.
- **Metric Designer:** generation gets the matched entries; measure names, comments, synonyms, display names
  and formats come from the dictionary when present. The design shows which fields came from it.
- **Sources & Readiness:** a coverage line: how many dictionary metrics the chosen tables can support, and
  which source columns they need.
- **Matching:** rules first (the `source` column, then name and synonym matches to column names and comments),
  the model only for the rest, with metadata and dictionary text, never data rows.

### Step 4: Table context

- Entries with a column match become proposed `COMMENT ON COLUMN` and `COMMENT ON TABLE` fixes in the
  improvement plan, marked "From the dictionary", with the readiness score gain.
- Same approval flow as today: the user sees the SQL, the app checks permissions, nothing runs without approval.

## Security

- Uploads are untrusted. The model gets dictionary text as quoted data with an instruction to ignore any
  instructions inside it.
- Only text is stored; the file itself is not kept.
- Comments written to UC are the definitions the user approved, with quotes escaped by the existing builder.

## Demo

Download the template, fill five TPC-H metrics with formulas and synonyms, import it into the Order fulfilment
project, generate a new design and show the dictionary names, then apply two column comments from it.

## Questions to decide

1. Should a certified dictionary entry lock the measure name and formula in the designer, or only suggest them?
2. Should the import also accept a Unity Catalog volume path, besides a browser upload?
