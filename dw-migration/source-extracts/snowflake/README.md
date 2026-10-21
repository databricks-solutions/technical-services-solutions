# Snowflake extract

Exports Snowflake metadata for Lakebridge Analyzer using `SHOW` + `GET_DDL`.

Do **not** run this in Databricks. Run it on a laptop or jump host that can reach the Snowflake account.

DDL is the default. Workload SQL is optional (`ACCOUNT_USAGE`) and is what usually fails on locked-down estates.

## Output layout

```
sf_export/
  SALES_MART/
    tables/          SCHEMA.TABLE.sql
    views/
    materialized_views/
    functions/
    procedures/
    sequences/
    file_formats/
    streams/
    tasks/
    pipes/
    masking_policies/
    row_access_policies/
    tags/
    queries/         # only with --include-workloads
  RISK_HUB/
    tables/
    views/
    ...
  export_summary.json
```

One folder per database. Object-type subfolders inside it. Files are named `{schema}.{object}.sql`.

Snowflake has no classic triggers; streams, tasks, and pipes are exported instead. Stages are not exported (`GET_DDL` does not support them).

## Prerequisites

| Need | DDL | Workloads |
|---|---|---|
| Python 3.9+ | yes | yes |
| Role with `USAGE` on target databases/schemas | yes | yes |
| Privileges to `GET_DDL` each object | yes | — |
| Running warehouse | yes | yes |
| `IMPORTED PRIVILEGES` on database `SNOWFLAKE` | no | yes (ACCOUNTADMIN grant) |

Every statement is tagged `lakebridge_export` in Snowflake query history.

## Run

```bash
cd dw-migration/source-extracts/snowflake
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # then edit
set -a && source .env && set +a

python export.py --output sf_export
```

`.env.example` fields: `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_ROLE`, `SNOWFLAKE_WAREHOUSE`, optional `SNOWFLAKE_PASSWORD` or `SNOWFLAKE_AUTHENTICATOR=externalbrowser`.

Restrict scope:

```bash
python export.py --databases SALES_MART,RISK_HUB --output sf_export
```

Omit `--databases` (and leave `SNOWFLAKE_DATABASES` unset) to export every non-system database.

Optional query history (90 days, deduped by `query_parameterized_hash`):

```bash
python export.py --include-workloads --days 90 --databases SALES_MART
```

Hand `sf_export/` to Lakebridge Analyzer. Do not commit it.

## Grants

```sql
GRANT USAGE ON DATABASE sales_mart TO ROLE metadata_reader;
GRANT USAGE ON ALL SCHEMAS IN DATABASE sales_mart TO ROLE metadata_reader;

-- Workload path only
USE ROLE ACCOUNTADMIN;
GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE metadata_reader;
```

## Notes

- System databases `SNOWFLAKE` and `SNOWFLAKE_SAMPLE_DATA` are skipped.
- `SHOW` is paginated (10k rows) so large schemas still complete.
- Functions and procedures use `SHOW USER ...` plus the argument signature `GET_DDL` requires.
- Filenames include a short hash when quoted identifiers would collide.
- One Snowflake account per output folder. For several accounts, run once each with a different `--output`.
- `ACCOUNT_USAGE.QUERY_HISTORY` can lag up to ~45 minutes after statements run.
