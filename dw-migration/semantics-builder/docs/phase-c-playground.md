# Phase (c): Semantic Modeler Playground

Goal: a library of metric view patterns that a user can read, run in the sandbox, and adapt to the
project sources. Each pattern is proven on sample data before it is offered.

## Principles carried over from phases (a) and (b)

- The model never writes SQL or YAML text. "Apply to my data" returns the same structured design as
  the Metric Designer; the server checks it against live profiles and renders the YAML.
- Every DDL shows the exact SQL and runs only after approval, as the user, through the audited runner.
- Pattern views live only in the sandbox schema, with a `__gsb_<8 hex>` name, so the existing
  approved DROP removes them.
- Lakebase stores metadata only: run status, row counts, and the SQL. No result values.

## Steps

1. **Pluggable pattern library.** One folder per pattern under `patterns/<slug>/`, same structure for all:
   - `pattern.yml`: title, category, scenario, sample question, sample sources, roles (for example
     `order_date`, `amount`, `customer_key`), test query with a `{{view}}` placeholder, expected output
     (columns and a few rows), minimum DBR, and an attribution line.
   - `metric_view.yml`: the measure YAML, validated by the phase (b) schema.

   The server loads and validates every folder at startup with zod. An invalid folder is skipped with a
   log line, so one bad pattern cannot break the app. A unit test fails the build on an invalid folder.
2. **Seed patterns (upstream categories).** Time intelligence (period over period, period to date,
   rolling), semi-additive, ranking, currency conversion with historical FX, static segmentation,
   dynamic segmentation, and calendars (fiscal, NRF 4-5-4). Sample data: `samples.tpch`, and
   `samples.tpcds_sf1` where it fits better (inventory snapshots for semi-additive, `date_dim` fiscal
   columns for the fiscal calendar). Reference data that the samples do not have (FX rates, budgets,
   segment bands, the 4-5-4 calendar) comes from SQL query sources (`VALUES` or `sequence`), so no
   CREATE TABLE is necessary.
3. **Extended patterns.** SCD2 (point-in-time join on a synthetic history), role-playing dimensions
   (customer nation and supplier nation from one `nation` table; ship, commit and receipt dates),
   many-to-many bridge (`partsupp` between part and supplier, with the fan-out warning explained),
   ratio and derived measures, distinct-count handling (exact vs approximate, why it does not roll up),
   budget vs actual (different grains), cohort and retention, and funnel (order lifecycle stages).
4. **Pattern checks in CI.** A test renders every `metric_view.yml` and checks it with
   `validateMetricView`, and checks that the test query passes the read allowlist. A script (not CI)
   runs each pattern on the dev warehouse and refreshes the expected output, so the stored output
   comes from a real run.
5. **Try in sandbox.** On the Playground page, "Try in sandbox" shows the approved
   `CREATE OR REPLACE VIEW <sandbox>.<slug>__gsb_<project 8 hex>` statement. Then the server runs the
   test query as the user and compares the rows with the expected output (`compareRows`, same
   tolerance). The page shows pass or fail, the SQL, and "Remove sandbox view".
6. **Apply to my data.** The model gets the pattern (YAML, roles, scenario), the brief and the live
   source profiles. It returns a structured design that maps each role to a project column. This
   needs window measure support in `DesignOutput` and `buildDesign`. The result becomes a new designer
   draft version with origin `pattern` (migration 004 widens the origin check). The user then edits
   and validates it in the Metric Designer as in phase (b). If no column fits a role, the model must
   say so and the server stops with a clear message.
7. **Playground page.** New project module "Playground": pattern cards grouped by category, a filter,
   and a detail view (scenario, sample question, YAML, test query, expected output, last run).
   Du Bois components, light and dark mode, the four data states, WCAG AA.
8. **TPC-H demo and phase summary.** Run three patterns in the sandbox (period over period,
   role-playing, budget vs actual), then apply period over period to the "TPC-H Sales (sandbox copy)"
   project and validate the new draft.

## Defaults (change if needed)

- Patterns are original work for this app, with an attribution link to
  `databricks-solutions/uc-semantics-patterns`. Upstream files are not copied (see question 2).
- Patterns need a DBR that the dev serverless warehouse has. A pattern that needs a newer DBR is shown
  with a "needs DBR x" tag and "Try in sandbox" is disabled.
- `MEASURE()` is used in all patterns. `AGG()` is accepted by the editor, but patterns do not use it.
- Pattern runs are not stored per pattern history; only the latest run per project and pattern.

## Risks

- Expected outputs depend on the sample data. If Databricks changes `samples`, the CI check still
  passes but a live run fails. The refresh script fixes it.
- Some window features need DBR 18.1+ (dated offset, one_to_many), 18.2+ (window parameters) or 19+
  (numeric offset). Customer warehouses can be older.
- SQL query sources in joins and range join conditions (SCD2) must be confirmed on the warehouse in
  step 2. If they fail, SCD2 uses a query source for the fact instead.
- "Apply to my data" quality depends on role mapping. A wrong mapping is caught only by validation in
  the designer, not at apply time.
- Upstream license: the upstream repo allows redistribution only with Databricks Services and needs
  notices on modified files. Original patterns avoid this.
