# Phase d: Optimizer and Materialization

Status: approved 2026-11-05. Step 0 done.

## Goal

A validated metric view can be correct and still be slow or expensive. Phase d answers four questions before the
view is published:

1. **How does it perform?** A stress test runs realistic queries and measures them.
2. **Should it be materialized, and how?** Suggestions come from the stress test and the model, not from guesses.
3. **Does it follow best practices?** A rule-based review of the YAML, with fixes the user approves.
4. **What does it cost?** Statistics the customer can review: what the app ran, what it read, and what a
   materialization would add.

New module in the sub-project: **Optimize**, after Metric Designer. It opens only for a validated design.

## Facts this plan relies on

Checked on 2026-11-05 in the Databricks docs and the installed SDK.

- **Query History API** (`queryHistory.list` with `filter_by.statement_ids` and `include_metrics`) returns, per
  statement: execution, compilation and task time, bytes read, pruned bytes and files, cache bytes, spill to disk,
  rows read and produced, and `result_from_cache`. No system table access is needed.
- **Materialization** in the YAML (`materialization: schedule, mode: relaxed, materialized_views: [...]`) creates a
  managed Lakeflow pipeline. Types: `aggregated` (named dimensions and measures) and `unaggregated` (at most one; the
  joined and filtered data, with `cluster_by` or `partition_by`).
- Query rewrite tries **exact match, then rollup, then unaggregated**. Rollup works only for additive measures and
  not with one-to-many joins. Non-additive measures (COUNT DISTINCT, percentiles) need an exact match. Rewrite is
  `relaxed`: matched queries return data from the last refresh.
- `EXPLAIN EXTENDED` shows `__materialization_mat_...` in the leaf node when a materialization was used.
- Requirements: serverless enabled, DBR 17.3+ for materialization, no row filters, column masks or ABAC on the view
  or its sources, no `current_user()` or `is_member()`, no parameters.
- Refreshes bill as Lakeflow pipeline DBUs. The pipeline inherits the **custom tags of the SQL warehouse** that
  created it, so cost can be attributed in `system.billing.usage`.
- **Conflict with phase f:** after a materialization exists, the owner of the metric view cannot be changed, and
  groups cannot own a materialized metric view. Transfer ownership before materializing.

## Steps

### Step 0: Spike (no UI)

Test with the user's OBO token, as we learned with `grants.getEffective`:

- `queryHistory.list` with the current app scopes (`sql`). If it needs another scope, use the statement result
  manifest and wall-clock time only, and say so in the UI.
- `EXPLAIN EXTENDED` on a sandbox metric view, to parse the materialization match.
- One sandbox materialization on the TPC-H view: time to first refresh, and the DBUs in the pipeline run.

Output: a short note with the results. The rest of the plan changes if a test fails.

**Results (2026-11-05, workspace ag_dev):**

- **Query History works with the OBO token and the `sql` scope.** No new scope. `queryHistory.list` with
  `statement_ids` and `include_metrics` returned execution and task time, bytes read, pruned bytes, rows read, spill
  and `result_from_cache` within a few seconds of the statement end.
- **Result cache:** the same SQL text returns from the cache (0 bytes read). A SQL comment does not bypass it. A
  no-op filter with a unique value (`WHERE <run tag> > 0`) or a unique literal column does. The app uses the no-op
  filter, so the result columns do not change.
- **Materialization works here.** `CREATE VIEW ... WITH METRICS` with a `materialization` block, sent through the
  Statement Execution API, created a managed pipeline. The first refresh took about 37 seconds on serverless (cause
  `DBSQL_REQUEST`). `DESCRIBE EXTENDED` shows the pipeline id and the latest refresh status.
- **Match detection works.** `EXPLAIN EXTENDED` contains `__materialization_mat_<pipeline id>___metric_view_mat_`
  for an exact match, a rollup (fewer dimensions, additive measures) and a filtered query. A plain query on the
  source has no such marker.
- **Billing:** `system.billing.usage` was readable for this user (an admin), but the pipeline had no rows yet.
  Billing data arrives hours later, so the Cost tab shows the refresh time at once and the DBUs later.
- **Clean-up:** `DROP VIEW` on the metric view leaves its pipeline (state `IDLE`). The app must delete the pipeline
  itself when it removes a sandbox materialization.
- **CLI note:** `databricks experimental aitools tools query` strips the YAML indentation. Use the Statement
  Execution API for metric view DDL.

### Step 1: Workload

The stress test needs queries that look like real use. Sources, in this order:

- The key questions and measures of the confirmed brief.
- The validation tests of the design.
- Generated combinations: each measure by each time grain, and by the most selective dimensions, with typical
  filters (last 12 months, one region).

The user sees the list, can remove or add queries, and approves it. Each query has a label in business terms
("Net Revenue by month, last 12 months").

### Step 2: Stress test

- Runs the approved workload on the sandbox metric view, as the user, on the app's SQL warehouse.
- Each query runs **cold once and warm N times** (default N = 2), with the result cache off
  (`SET use_cached_result = false`), so the numbers show real work.
- Per query: p50 and max latency, bytes read, pruned bytes, spill, rows read, from the Query History API.
- Flags: slow (over a target the user sets, default 5 s), full scans (low pruning), spill to disk, huge row counts.
- Concurrency: optional, at most 4 parallel queries. It shows whether the warehouse queues. Off by default.

### Step 3: Materialization suggestions

Rules first, the model explains:

- Group the slow or frequent queries by their dimension set. Suggest one **aggregated** materialization per group,
  with those dimensions and measures. Include the filter columns as dimensions, so filtered queries match.
- Mark measures that need an exact match (non-additive) and joins that block rollup (one-to-many).
- Suggest **unaggregated** with `cluster_by` on the most filtered dimensions when many joins make all queries slow.
- Suggest a schedule from the freshness the user needs (from the brief or a question), not "every 1 hour" by default.
- Check the requirements above and stop with a clear reason when one fails (row filters, parameters, DBR).

**Try it:** the user approves the YAML change, the app creates the materialized version in the sandbox, waits for the
first refresh, then runs the same workload again. The report shows before and after per query, and whether the
query matched a materialization (`EXPLAIN EXTENDED`). The sandbox pipeline is removed with the sandbox view.

### Step 4: Best practices

Rule-based checks on the YAML, each with a reason and, where possible, a fix as a new design version:

- Every measure and dimension has a comment; key fields have synonyms and display names (Genie).
- Formats on currency, percentage and date fields.
- Joins have a declared primary key on the joined table (many-to-one confirmed).
- Ratios use `NULLIF` on the divisor; ratios are built from measures, not re-aggregated.
- COUNT DISTINCT and percentiles noted as non-additive, so they need exact matches.
- High-cardinality dimensions (ids, free text) flagged; they make materializations large.
- A filter on the view when the brief scopes the data (for example, completed orders only).
- One fact table per view (the Genie design rule).

The checks reuse the validation warnings the designer already shows. No new model call is needed for the checks.

### Step 5: Cost control and statistics

**Control, before anything runs:**

- Every run shows its plan: number of queries, repetitions, the warehouse, and an estimate of warehouse time from
  the last run. The user approves it.
- Hard limits per run: query count, a timeout per query, `LIMIT` on result rows, and a stop button.
- A per-project budget for app-run warehouse time, set by the project owner. Runs stop at the budget.
- Materialization tries are explicit actions with their own approval, because they start a pipeline.

**Statistics the customer reviews, in a Cost tab:**

- Per run: queries, total and p50 execution time, bytes read, task time, cache hits. Stored in Lakebase, so no
  system table access is needed.
- Per materialization suggestion: refresh time and the pipeline DBUs from the sandbox try, plus the query time it
  saved in the second stress run. Shown as a trade-off: refresh cost per day against the query time saved per day at
  the expected query volume, which the user enters.
- Optional, when the user can read `system.billing.usage`: actual DBUs by the warehouse custom tags. Otherwise the
  tab says who can see it (an account or workspace admin).
- Export as CSV.

The app shows DBUs and time, not money. List prices differ by cloud, region and contract, so the user can enter
their rate to see an estimate.

## Data (Lakebase)

- `gsb.stress_run` (project, design version, workload, settings, status, created by and at).
- `gsb.stress_query` (run, label, SQL, statement ids, metrics json, flags).
- `gsb.materialization_try` (project, design version, YAML, pipeline id, refresh metrics, before and after runs).

## Risks

- A stress test on a large source can be expensive. The plan, the limits and the budget are the control.
- Query History metrics can arrive a few seconds after a statement ends. The app polls with a timeout.
- Materialization status in this workspace is not confirmed (the page does not say Preview or GA). Step 0 checks
  that it works here.
- The sandbox is not production: the numbers depend on the sandbox data size. The report says which tables it read.

## Questions to decide

1. Should the stress test run on the app's SQL warehouse, or can the user pick another warehouse?
2. Is a per-project budget enough, or do you also want a workspace-wide budget set by the app admin?
3. Should materialization tries run in the sandbox only (my recommendation), or also against the real sources?
4. For cost, is showing DBUs and time with an optional user rate enough, or do you want list prices?

## Demo (TPC-H)

`net_revenue_order_performance` in the sandbox copy: generate the workload from the brief, run the stress test,
get one aggregated suggestion (Net Revenue by Order Month and Region), try it, and compare before and after with
the match shown by `EXPLAIN EXTENDED`. Then review the Cost tab.
