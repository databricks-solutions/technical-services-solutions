# SDP Schema Evolution with the Rescued Data Column

Agent runbook for an AI coding harness (Cursor, Claude Code, Codex, etc.).
A customer should be able to open this project and say: **run README.md**.
Follow every step in order.
Do not skip pauses.
Do not invent credentials or workspace settings.

## What this demo teaches

Bronze uses a fixed schema and Auto Loader `schemaEvolutionMode = rescue`.
Column renames, type changes, and new columns land in `_rescued_data` instead of breaking the stream.
Silver recovers those values with `reconcile` (`coalesce` against rescued JSON).
No full refresh.
No bronze/silver drift.

Rule to remember: **fixed bronze schema -> rescue everything -> reconcile in silver -> never full-refresh.**

## Agent operating rules

1. Use only the CLI flags the user confirmed in Prerequisites.
2. After every `databricks bundle run` / `deploy`, wait for SUCCESS before the next step.
3. On failure: read the error, fix local code or config, redeploy if needed, re-run the failed command.
   Do not continue to the next demo step until the current one is green.
4. When this runbook says **PAUSE**, stop.
   Message the user with the exact SQL (or UI action) below.
   Wait for them to reply before continuing.
5. Do not flip the Step 4 reconcile toggle until that step says to.
6. Prefer the Databricks CLI over clicking around the workspace UI, except for SQL verification pauses (SQL editor).

## Prerequisites (configure before anything else)

**PAUSE.**
Do not deploy yet.
Ask the user to confirm these three values.
They are mandatory.

| Setting | Where it lives | Example |
| --- | --- | --- |
| **CLI profile** | Databricks CLI auth profile name | `my-profile` |
| **Catalog name** | `variables.catalog.default` in `databricks.yml` | `main` |
| **Workspace URL** | `targets.dev.workspace.host` in `databricks.yml` | `https://YOUR_WORKSPACE.cloud.databricks.com/` |

Also confirm:

- The user can already authenticate with that profile (`databricks auth login --profile <PROFILE>` if needed).
- Unity Catalog is enabled and they can create a schema + volume in that catalog.
- Serverless compute is enabled.
- Schema name (default `sdp_evolution` via `variables.schema.default`) is acceptable, or they want a different one.

Then update `databricks.yml` if their values differ from the defaults/examples above.

Every bundle command in this runbook uses:

```bash
databricks bundle <deploy|run|validate> --profile <PROFILE> --target dev
```

Substitute `<PROFILE>` with the confirmed profile.
Substitute `<CATALOG>` and `<SCHEMA>` in SQL with the confirmed catalog and schema.

**Do not continue until the user has confirmed profile, catalog name, and workspace URL.**

## Layout (read-only context)

| Path | Role |
| --- | --- |
| `databricks.yml` | Bundle: catalog/schema vars, workspace host, targets. |
| `resources/uc.yml` | UC schema + managed `landing` volume (created on deploy). |
| `resources/pipeline.yml` | Serverless SDP pipeline. |
| `resources/seed_jobs.yml` | `seed_v1_job` / `seed_v2_job`. |
| `resources/test_job.yml` | Unit-test notebook job. |
| `src/pipeline.py` | Bronze (rescue) + silver (STATE 1 passthrough / STATE 2 reconcile). |
| `src/reconcile.py` | Pure `reconcile(df)`. |
| `src/seed_data.py` | Writes JSON into the landing volume (does not create UC objects). |
| `tests/test_reconcile_notebook.py` | Assert-based reconcile tests. |

Shipped silver state for a fresh run must be **STATE 1**: passthrough `return df.select(...)` is live; `return reconcile(df)` is inactive.
If a previous run left STATE 2 active, restore STATE 1 before Step 0 (unwrap the passthrough from the triple-quoted block and comment out or remove the active `return reconcile(df)`).

---

## Step 0: validate and deploy

```bash
databricks bundle validate --profile <PROFILE> --target dev
databricks bundle deploy --profile <PROFILE> --target dev
```

Deploy creates the UC schema and managed `landing` volume, plus jobs and the pipeline.
Expected: `Validation OK!` then `Deployment complete!`

---

## Step 1: run the unit-test gate

```bash
databricks bundle run test_job --profile <PROFILE> --target dev
```

Expected: job `TERMINATED SUCCESS`.
Any failed assert fails the job.

---

## Step 2: seed clean v1 data

```bash
databricks bundle run seed_v1_job --profile <PROFILE> --target dev
```

Expected: SUCCESS and a log line writing `orders_v1.json` under:

```text
/Volumes/<CATALOG>/<SCHEMA>/<landing-volume>/orders
```

v1 shape: `order_id`, `cust_name`, `amount` (string), `order_ts`.

---

## Step 3: baseline pipeline (v1 only)

```bash
databricks bundle run orders_pipeline --profile <PROFILE> --target dev
```

Expected: pipeline update COMPLETED / SUCCESS.

### PAUSE - verify baseline data

Before you continue, tell the user:

> Go to the SQL editor in workspace `<WORKSPACE_URL>`.
> Run the queries below.
> Confirm bronze has rows with `_rescued_data` null, and silver has populated `customer_name` / `amount` with `loyalty_tier` null.
> Come back after you verified that and tell me to continue.

```sql
SELECT * FROM <CATALOG>.<SCHEMA>.orders_bronze ORDER BY order_id;
-- Expect: rows present; _rescued_data is null for v1.

SELECT * FROM <CATALOG>.<SCHEMA>.orders_silver ORDER BY order_id;
-- Expect: customer_name + amount populated; loyalty_tier null.
```

**Do not start Step 4 until the user confirms the baseline looks correct.**

---

## Step 4: introduce schema drift (v2)

```bash
databricks bundle run seed_v2_job --profile <PROFILE> --target dev
```

Expected: SUCCESS writing `orders_v2.json` with three drifts vs v1:

1. Rename: `cust_name` -> `customer_name`
2. Type change: `amount` string -> number
3. New column: `loyalty_tier`

---

## Step 5: re-run pipeline and observe the break (still STATE 1)

```bash
databricks bundle run orders_pipeline --profile <PROFILE> --target dev
```

Expected: pipeline SUCCESS (ingest does not crash).
Drift is rescued, not fatal.

### PAUSE - verify rescued / broken silver

Before you continue, tell the user:

> Go to the SQL editor.
> Run the queries below.
> Confirm new v2 bronze rows have values in `_rescued_data`, and silver shows null `customer_name` / `amount` for those v2 rows.
> Come back after you verified that and tell me to continue.

```sql
SELECT order_id, cust_name, amount, _rescued_data
FROM <CATALOG>.<SCHEMA>.orders_bronze
WHERE _rescued_data IS NOT NULL
ORDER BY order_id;
-- Expect: v2 rows; cust_name/amount null in base columns; JSON in _rescued_data.

SELECT * FROM <CATALOG>.<SCHEMA>.orders_silver ORDER BY order_id;
-- Expect: v1 rows still fine; v2 rows have null customer_name / amount.
```

**Do not apply the reconcile fix until the user confirms they saw the break.**

---

## Step 6: apply the reconcile fix in `src/pipeline.py` (STATE 2)

Open `src/pipeline.py`, find `orders_silver` (section marked `STEP 4`).

Disable STATE 1 by wrapping the passthrough return in a triple-quoted string:

```python
    # START OF STATE 1
    """
    return df.select(
        "order_id",
        F.col("cust_name").alias("customer_name"),
        F.col("amount").cast("double").alias("amount"),
        F.lit(None).cast("string").alias("loyalty_tier"),
        "order_ts",
    )"""
    # END OF STATE 1
```

Activate STATE 2 by making this the live return:

```python
    # START OF STATE 2
    return reconcile(df)
    # END OF STATE 2
```

Do not deploy yet.

### PAUSE - user continues after the code change

Tell the user:

> I wrapped the STATE 1 passthrough return in triple quotes and activated `return reconcile(df)`.
> Reply **continue** when you want me to deploy and re-run the pipeline.

**Do not deploy or run until the user says to continue.**

---

## Step 7: redeploy and re-run (reconcile on)

```bash
databricks bundle deploy --profile <PROFILE> --target dev
databricks bundle run orders_pipeline --profile <PROFILE> --target dev
```

Expected: deploy complete, pipeline SUCCESS.
Bronze is not fully refreshed; silver recomputes with reconcile.

### PAUSE - verify silver recovered

Before you declare the demo done, tell the user:

> Go to the SQL editor one last time.
> Run the query below.
> Confirm every row has `customer_name` and `amount`, and v2 rows also have `loyalty_tier`.
> Come back after you verified that.

```sql
SELECT * FROM <CATALOG>.<SCHEMA>.orders_silver ORDER BY order_id;
-- Expect: all rows recovered; v2 rows carry loyalty_tier; no full refresh of bronze required.
```

When the user confirms, the demo is complete.

---

## Why this avoids full recomputes

- Bronze keeps a fixed schema, so drift does not force a bronze rewrite.
- Drift is preserved in `_rescued_data`, so nothing is lost.
- Reconciliation runs in silver (materialized view) only.
- Old and new rows share business columns via `coalesce`.

## Applying this across a pipeline portfolio

1. Fixed bronze schema + `schemaEvolutionMode = rescue` + `rescuedDataColumn = _rescued_data`.
2. Small `reconcile`-style function per silver table.
3. On source drift, update only the reconcile mapping - no full refresh, no downtime.
