# Source extracts

Offline extractors that write **local `.sql` files** in the layout Databricks Lakebridge Analyzer expects.

Run them on a **laptop or jump host** with network access to the source platform. Do **not** run them in Databricks.

Use this kit when the live Profiler / query-history path cannot run: privilege limits, scale, or the customer will not let query text leave the account.

## Sources

| Source | Path | Status |
|---|---|---|
| Snowflake | [`snowflake`](snowflake) | Ready |

Each source is self-contained: its own exporter, credentials template, and runbook.

## Shared rules

| Rule | Why |
|---|---|
| Run on a laptop or jump host | The machine must reach the source; Databricks is the wrong place. |
| DDL first | Object definitions are enough for a first Analyzer pass. |
| Workloads optional | Historical SQL usually needs extra grants and is the step customers block. |
| One statement per file | Analyzer expects that. |
| No customer SQL in git | Output folders stay local. |
| Credentials via env / `.env` | Copy `.env.example`. Never commit `.env`. |

## Typical flow

1. Confirm the customer role can read metadata (DDL). Workload SQL is optional.
2. Copy `.env.example` → `.env` (gitignored) or export the same variables in your shell.
3. Run the exporter for that source.
4. Give the output directory to Lakebridge Analyzer.

## Adding another source

```
dw-migration/source-extracts/
  snowflake/
  <engine>/
    README.md
    export.py
    .env.example
    requirements.txt
```

Keep the same contract: local run, DDL by default, one `.sql` file per object or statement, session tags so the customer can audit the extract, no secrets in the repo.

Write extracts under a local folder such as `sf_export/`. Use a **separate output directory per source account**.
