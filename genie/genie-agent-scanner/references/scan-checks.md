# Scan checks — the IQ rubric

The scan is deterministic and rule-based (no LLM). It scores a single Genie
space 0-12 (each check = 1 point, no weights) and assigns a maturity tier. This
is a faithful port of Genie Workbench's `iq_scan` scoring core.

It reads two inputs: the space `serialized_space` config AND Unity Catalog (UC)
metadata per table (comment, `table_type`, columns). UC is what lets the
table-description and metric-view checks match Workbench. When UC metadata is
missing for some or all tables, those checks fall back to config-only and the
report sets `uc_status` to `partial` or `unavailable`.

## The 12 checks

Checks 1-10 are configuration checks; checks 11-12 are optimization outcomes.

| # | Check | Passes when | Fails when | Warning band |
|---|-------|-------------|------------|--------------|
| 1 | Data sources exist | >= 1 table or metric view configured | none configured | — |
| 2 | Table descriptions | >= 80% of TABLES described (space-level description OR UC comment) | < 80% of tables | 80-99% ("aim for 100%") |
| 3 | Column descriptions | >= 50% of CONFIGURED columns described | < 50%, including 0 configured columns (0/0 fails) | 50-79% ("aim for 80%+") |
| 4 | Text instructions | >= 1 instruction, total length > 50 chars | missing or too brief | > 2000 chars, OR SQL logic detected in prose (see detector) |
| 5 | Join specifications | >= 1 join spec (only checked when multi-source) | 0 specs AND > 1 data source | — |
| 6 | Data source count | 1 <= total <= 12 | > 12 ("consider a multi-room architecture") | — |
| 7 | Example SQL count | >= 8 `example_question_sqls` | < 8 | 8-9 ("10-15 is the sweet spot"); advisory if > half lack `usage_guidance` |
| 8 | SQL snippets | >= 1 of functions / expressions / measures / filters | none | missing `filters` or `measures` |
| 9 | Entity / format matching | >= 1 column with `enable_entity_matching` or `enable_format_assistance` | none | > 100 columns (approaching the 120/space cap); > 120 (excess ignored); advisory if RLS tables present |
| 10 | Benchmark coverage | >= 10 `benchmarks.questions` | < 10 | — |
| 11 | Optimization workflow completed | an optimization run exists | none | — |
| 12 | Optimization accuracy >= 85% | `optimization_run.accuracy >= 0.85` | < 85% | — |

Severity per check is `pass`, `warning`, or `fail`. Warnings do not cost a
point on their own in the strict score, but they DO trigger the check's fix
lever (see below) and should be surfaced in the report.

### Data sources, metric views, and denominators
- A data source is classified as a **metric view** only when its UC
  `table_type == "METRIC_VIEW"`; every other type is a **table**. When UC
  metadata is absent, classification falls back to how the config declared it.
- Check 2's denominator is **tables only** (metric views are graded
  separately). A table is "described" if it has a space-level description OR a
  UC comment. A metric-view-only space passes check 2 (no tables to grade); a
  truly empty space (0 data sources) fails it (and check 1).
- Check 3's denominator is **only the columns explicitly configured in the
  space**. It NEVER counts Unity Catalog columns. A space with 0 configured
  columns fails 0/0: configuring and describing columns is the fix, not reading
  UC comments.

## Scoring and maturity tiers

- `score = number of checks that passed` (0-12).
- Maturity tier:
  - **Trusted** — all 12 checks pass.
  - **Ready to Optimize** — all 10 configuration checks (1-10) pass, but 11-12
    do not.
  - **Not Ready** — any configuration check (1-10) fails.

Report the score, the tier, each check's pass/warning/fail with a one-line
evidence detail, and a ranked next-steps list. Cap long lists at 8 items.

## Which checks are fixable (`SCAN_CHECK_TO_LEVERS`)

Only these checks can be fixed by editing config. A failing OR warning state on
one of them should trigger its lever during guided optimize:

| Check | Fix lever (surface to edit) |
|-------|-----------------------------|
| 2 Table descriptions | Lever 1 — tables & columns |
| 3 Column descriptions | Lever 1 — tables & columns |
| 4 Text instructions | Lever 5 — instructions |
| 5 Join specifications | Lever 4 — joins |
| 7 Example SQL | Lever 6 — SQL expressions / example SQL |
| 8 SQL snippets | Lever 6 — SQL expressions |
| 9 Entity / format matching | Lever 1 — tables & columns |

Checks **1, 6, 10, 11, 12 are intentionally NOT fixable** by a config patch:
- 1 (no data sources) and 6 (too many sources) are structural / architectural.
- 10 (benchmarks), 11 (optimization run), 12 (accuracy) require running a
  benchmark or optimization workflow, not a config edit.

For these, the report should recommend the corresponding action (add a data
source, split the room, author/run benchmarks) rather than an auto-patch.

> Note on benchmarks: the `add_benchmark_question` fix operation exists and may
> be applied to *seed* benchmark rows, but that does not make check 10
> config-fixable. Passing check 10 requires genuine benchmark curation (quality
> questions with verified answers, run through the benchmark workflow), which is
> a user process — so a fix must not claim `check_id: 10`, and `optimize.py`
> rejects one that does.

## SQL-in-prose detector (check 4)

Check 4 warns when a text instruction contains SQL logic that belongs in a SQL
expression, snippet, or example instead of prose. A line is flagged as
SQL-in-prose when:

1. It matches a SQL anchor pattern (e.g. `SELECT ... FROM`, `JOIN ident ON`,
   `WHERE ident <op>`, `GROUP BY ... HAVING`), OR
2. It contains >= 2 distinct SQL keywords AND a structural signal (a dotted
   identifier like `t.col`, a comparator, an aggregate, or `IS NULL`).

A line is NOT flagged if it starts with a prose imperative such as "Do not",
"Don't", "Never", "Always", "When", "If", "Prefer", "Avoid", "Combine", "Link",
"Pair", "Associate", "Consider", or "Note" — those are legitimate guidance.

## RLS / column-mask audit

**v1 status:** the deterministic offline scan does NOT run this live audit — it
requires warehouse SQL against `information_schema`, which is out of scope for a
config-only linter. Check 9 is scored from config alone, and its evidence notes
that RLS-tainted tables were not evaluated. Treat the audit below as the
recommended manual verification and a planned live-mode enhancement: before
enabling entity matching, confirm the table is not RLS/mask tainted.

When run live, the audit gives each table a verdict of `clean`, `tainted`, or
`unknown`, from four privilege-aware probes against
`<catalog>.information_schema.*` (never `system.*`):

1. **Direct row filters** — `information_schema.row_filters`.
2. **Direct column masks** — `information_schema.column_masks`.
3. **Inherited RLS** — views whose base tables (from `view_table_usage`, with a
   regex fallback on the view definition) carry a filter or mask.
4. **Dynamic views** — DDL that calls `current_user()`, `session_user()`,
   `is_account_group_member()`, or `is_member()`.

Fail-open: if a probe errors, the verdict is `unknown` and treated as clean
unless strict mode is enabled.

**Why it matters:** Genie silently disables entity matching on RLS-tainted
tables. Enabling entity matching there wastes a value-dictionary slot (120/space
cap) and does nothing. Never recommend entity matching on a `tainted` table;
call it out in the report.
