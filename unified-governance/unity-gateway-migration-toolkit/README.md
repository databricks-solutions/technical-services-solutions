# Unity Gateway Migration Toolkit (prototype, v0.9.0)

Toolkit and Databricks App for moving legacy model serving endpoints (AI Gateway v1/v2) to Unity Gateway (v3). Planning and scans only read (GET calls and read-only SQL). Writes happen only when you ask: results tables for the app, snapshots, and apply/rollback of Unity Gateway services.

Prototype from Databricks Shared Technical Services, provided as is. Review results before acting on them.

## Quick start (inside the workspace, about 5 minutes)

1. Download `unity-gateway-migration-toolkit-0.9.0.zip` and unzip it. The installer is at the top of the zip: `INSTALL_unity_gateway_migration_toolkit_0_9_0.py`. In your workspace, open **Workspace**, go to your home folder and choose **Import**. Import that file. You only need that one file in the workspace: it carries the rest of the toolkit.
2. Open it, set **Results catalog** (an existing catalog) and pick a **SQL warehouse**. The other widgets have defaults. Set **Allowed secret schemas** only if you will map API keys to Unity Catalog secrets.
3. Click **Run all**. It prints the link to the **Unity Gateway Migration Toolkit** app.
4. Before you apply anything, create the target schema (default `ai_gateway.migrated`) and give the jobs' identity `CREATE SERVICE` on it. Apply never creates schemas.
5. In the app: **Overview**, Refresh snapshot; then **Scans**, Start scan; then **Apply** for external model and Provisioned Throughput endpoints (dry run first, then execute).

Run the installer as a workspace admin with access to the system tables (the app's jobs run as you), or as a service principal. To update, run a newer installer with the same widgets; to remove, set **Action** to `uninstall`. Upgrading from 0.8.0 or 0.7.0: see [USER_GUIDE.md](USER_GUIDE.md) section 3. The runbook (order of work, owner communication, verifying callers, rollback) is in section 4. Results are explained in [HOW_TO_READ.md](HOW_TO_READ.md).

Prefer the command line or CI/CD? The same toolkit runs as Python scripts and as a Declarative Automation Bundle (`databricks.yml`); see below.

**Tags:** the toolkit's jobs (snapshot, scan and apply, from the installer or the bundle) carry the tags `tool = ug-migration-toolkit`, `Project = unity-gateway-migration-toolkit`, `app = <app name>` and `role` (`snapshot`, `scan` or `apply`), so the usage of this toolkit can be identified. They are only labels: they don't send data anywhere and don't change how the jobs run. Nothing else the toolkit creates is tagged (the app and the Unity Gateway services don't accept tags).

## What it does

1. **Inventory:** every serving endpoint, classified as `system_ppt` (`databricks-*`), `external_model`, `provisioned_throughput`, `custom_model` or `agent`, with its gateway settings (rate limits, guardrails, inference table, fallback), traffic split, tags and permissions.
2. **Traffic:** requests, requesters and last request per endpoint from `system.serving.endpoint_usage` (default last 30 days).
3. **Plan:** for each endpoint, the target and what to re-create:
   - `databricks-*` endpoints map to their `system.ai` model service (resolved from each `system.ai` service's destination, with name matching as a fallback).
   - External model endpoints get one model service each plus shared **provider services** (one per provider and secret).
   - Provisioned Throughput (PT) endpoints get a model service that wraps the existing endpoint.
   - Rate limits are translated for all scopes (endpoint, user, user default, group, service principal).
   - `CAN_QUERY` becomes `EXECUTE` and `CAN_MANAGE` becomes `EXECUTE` + `MANAGE`. Workspace-local `admins`/`users` are skipped and flagged. `CAN_VIEW` alone grants nothing.
   - Guardrails get specific service policy advice. Endpoints with no traffic are flagged as retire candidates.
   - Each row has `provider_status`: `automated` (apply creates it), `manual_supported`, `no_ug_provider` or `unknown_provider`.
4. **Client scan:** notebooks and files (parallel, identical copies such as app deployment snapshots reported once), jobs, saved SQL queries, dashboards, apps, AI Search (formerly Vector Search) indexes, **Knowledge Assistants and Supervisor Agents** (AI Search-backed sources are blockers), **Genie Agents (formerly Genie spaces)**, **environment variables of custom model endpoints**, **Unity Catalog SQL functions and views** (`ai_query` inside them, including multi-line calls) and **Lakeflow pipeline settings**, plus local folders with `--local-path`. Finds `ai_query('databricks-...')`, `/serving-endpoints` URLs, `ChatDatabricks(endpoint=...)`, MLflow `endpoints:/` judge URIs, app serving-endpoint resources, legacy embedding endpoints on indexes, and quoted legacy endpoint names. Each hit has a suggested replacement. In YAML/HCL/.env files it also catches unquoted values (`default: databricks-...`) and treats a bundle app's `serving_endpoint:` resource as an app blocker.
5. **Callers:** links each traffic requester (user or service principal, resolved to a name) to the code references in its folders, so you can see who calls what and where the code is.
6. **Enforce readiness:** `READY`, `READY_WITH_WARNINGS`, `INCOMPLETE` (part of the scan failed or was skipped, or traffic couldn't be confirmed; listed with the reason) or `BLOCKED`, with the blockers and the endpoints that can be closed now (no traffic, no dependents, not referenced in code), with a rate-limit-0 command that keeps their other gateway settings. READY needs zero legacy requests in the whole window (default 30 days). The readiness report lists the workspace folders it scanned.
7. **Proposed code fixes:** for each reference, the exact old and new line. `auto` fixes are mechanical (`ai_query` and MLflow judge URIs); `review` fixes need a check (URLs, model names, `ChatDatabricks`, rewritten to `model=` with `use_ai_gateway=True`).

## Output

| File | Content |
|---|---|
| `SUMMARY.md` | Readable overview: counts, active endpoints, callers, provider services, items that need a human, client references |
| `migration_plan.csv` | One row per legacy endpoint with target, destination, rate limits, routing, inference table, grants, tags, notes, traffic, `provider_status` |
| `provider_services.csv` | Provider services to create, with models, secrets (scope/key names only) and legacy endpoints |
| `client_references.csv` | Every code reference with location and suggestion |
| `callers.csv` | Requester to endpoint to linked code |
| `READINESS.md`, `readiness.json` | Enforce readiness, blockers, warnings, scanned folders, endpoints that can be closed now |
| `CODE_FIXES.md` | Proposed line changes per asset, as a reviewable diff |
| `legacy_endpoints.csv`, `system_ai_map.json` | Raw inventory and the legacy-name to `system.ai` mapping |

## Run

Requirements: `databricks-sdk>=0.158.0`, `requests`. Traffic needs read access to `system.serving.*` (account admin by default) and a SQL warehouse.

```bash
python ug_migration_planner.py --profile <cli-profile> --warehouse-id <warehouse-id> --out ./out --days 30
```

Options: `--local-path <folder>` (repeatable: also scan cloned Git repos, Declarative Automation Bundles projects or Terraform; skips `.git`, `node_modules`, virtualenvs, build folders, binaries and files over 2 MB), `--scan-root <path>` (repeatable; replaces the defaults `/Users`, `/Shared`, `/Repos`; the limit `--max-objects 20000` applies per root), `--threads 16`, `--skip-scan`, `--workspace-id` (override), `--target-catalog` / `--target-schema` for proposed service names (default `ai_gateway.migrated`).

In a notebook: upload `ug_migration_planner.py` and `notebook/run_planner.py` to the same workspace folder and run `run_planner`. It uses the notebook's Spark session for traffic (no warehouse needed) and writes the output next to it, or to the `out_dir` widget (a workspace or volume path). Tested on serverless.

## Account-wide view

`ug_migration_account.py` covers **every workspace in the account in one run** (about 20 seconds), using account-level system tables: `system.serving.served_entities` (live legacy endpoints and what they serve), `system.serving.endpoint_usage` (legacy traffic), `system.ai_gateway.usage` (v2 and Unity Gateway traffic) and `system.access.workspaces_latest` (names and URLs). Needs read access to those tables (account admin by default).

```bash
python ug_migration_account.py --profile P --warehouse-id W --out ./account_out --days 30
# Then deep-scan the busiest workspaces (or specific ones) with the per-workspace planner
python ug_migration_account.py --profile P --warehouse-id W --out ./account_out --deep-scan 5
python ug_migration_account.py --profile P --warehouse-id W --out ./account_out --workspace <id> --workspace <id>
# Track progress over time: append each run to Delta tables (opt-in, the only write)
python ug_migration_account.py --profile P --warehouse-id W --out ./account_out --snapshot-table main.ug_migration.snap
```

Output: `ACCOUNT_SUMMARY.md` (v1, v2 and Unity Gateway requests counted as distinct request IDs, share on Unity Gateway, waves, busiest workspaces and endpoints, name collisions), `account_workspaces.csv`, `account_endpoints.csv`, `account_collisions.csv`, and with a deep scan `workspaces/<id>/` (the full per-workspace report) plus `deep_scans.json`.

**Waves:** `v2 first` (v2 traffic; v2 endpoints stop serving first, on November 30, 2026 per Databricks communications as of October 30, 2026), `0: no legacy traffic` (no v1 requests in the window; not ready until a workspace scan passes), `0: traffic unknown` (live legacy endpoints with no usage rows in 365 days), `1: cleanup` (external model or PT endpoints with no traffic), `1: small` (under 10,000 legacy requests in the window), `2: high volume`. `no endpoint data` and `not running` workspaces aren't counted as wave 0.

**Deep-scan auth:** for each workspace it tries the same host as `--profile`, then any CLI profile with that host, then a service principal from `DATABRICKS_CLIENT_ID`/`DATABRICKS_CLIENT_SECRET`, then a CLI login for the host. For many workspaces, use a service principal assigned to them. Deep scans use the target schema `<target-schema>_<workspace_id>` to avoid name collisions when workspaces share a metastore.

**Snapshots:** `--snapshot-table catalog.schema.prefix` appends one row per workspace (`<prefix>_workspaces`) and per endpoint (`<prefix>_endpoints`) with a `snapshot_time`, for burn-down charts, for example:

```sql
SELECT snapshot_time, sum(legacy_requests) AS legacy, sum(v3_requests) AS v3,
       count_if(wave LIKE '0%') AS enforce_candidates
FROM main.ug_migration.snap_workspaces GROUP BY snapshot_time ORDER BY snapshot_time
```

## Progress tracking

Schedule `ug_migration_account.py --snapshot-table ...` (for example weekly, as a job), or use the app: its **Overview** charts every snapshot (legacy vs Unity Gateway traffic, workspaces ready to enforce, waves) and exports the workspaces, all legacy endpoints and the trend as CSV.

## Terraform

```bash
python ug_migration_apply.py --profile P terraform --endpoints ep1,ep2 --target-catalog ai_gateway --target-schema migrated \
  --allowed-secret-schemas ai_gateway.migrated --uc-secret-map '{"llm/openai": "secrets/ai_gateway.migrated.openai_key"}' \
  --out ug_migration.tf
```

Writes `databricks_ai_gateway_model_provider_service`, `databricks_ai_gateway_model_service` and `databricks_grants` (authoritative per service) for the same objects the apply step would create. Secrets become `sensitive` input variables (`TF_VAR_secret_<scope>_<key>`), or UC secret references with `--uc-secret-map` (which needs `--allowed-secret-schemas`); values are never read. Endpoints with legacy guardrails are skipped unless `--ack-guardrails`. The output is marked as a draft and passes `terraform validate` and `terraform fmt -check` (tested with Databricks provider 1.140.0).

## App, bundle and notebooks (for customers)

`databricks.yml` deploys the toolkit as a Declarative Automation Bundle: the **Unity Gateway Migration Toolkit app** (`app/`, FastAPI + React), the scan, apply and snapshot jobs it starts (`notebook/run_scan.py`, `run_apply.py`, `run_account.py`) and `notebook/run_planner.py` for ad hoc runs. The snapshot job is deployed **paused**, and a redeploy pauses it again.

The app has four tabs: Overview (account snapshot with charts), Scans (readiness, callers, code fixes), Apply (dry run, execute with typed confirmation, rollback) and About. Every view exports its data (CSV, or Markdown for the reports). Jobs write results to Delta (`ug_migration_scans`, `_scan_items`, `_applies`, `_apply_items` via `ug_migration_store.py`); pages read them as the signed-in user through the SQL warehouse. The app's service principal can only start and watch the three jobs. See USER_GUIDE section 10.

Frontend development: `cd app/frontend && npm install && npm run build` (output goes to `app/frontend/static`, which the bundle syncs; see DEVELOPING.md for local runs).

```bash
databricks bundle deploy -t dev --var warehouse_id=<id> --var snapshot_catalog=<catalog> --var snapshot_schema=<schema>
databricks bundle run ug_migration_snapshot -t dev --var ...
databricks bundle run ug_migration_app -t dev --var ...
```

Snapshot tables are `<catalog>.<schema>.ug_migration_workspaces` and `_endpoints`. `HOW_TO_READ.md` is the guide to reading the outputs.

## Apply (opt-in) and rollback

`ug_migration_apply.py` creates what the plan proposes for **external model and Provisioned Throughput endpoints**: model provider services (shared per provider and key), model services (destinations, fallback, all rate-limit scopes, a new inference table) and `EXECUTE`/`MANAGE` grants, then reads each service back to check it. It doesn't touch the legacy endpoints, so it can run before clients move. `databricks-*` endpoints need no new objects (their `system.ai` services already exist).

```bash
# Dry run (default): prints what it would create
python ug_migration_apply.py --profile P apply --endpoints ep1,ep2 --target-catalog ai_gateway --target-schema migrated \
  --allowed-secret-schemas ai_gateway.migrated \
  --uc-secret-map '{"llm/openai": "secrets/ai_gateway.migrated.openai_key"}'
# Create, one wave at a time; every created object goes to the log (JSON lines)
python ug_migration_apply.py --profile P apply --endpoints ep1,ep2 ... --execute --log wave1.jsonl
# Undo exactly what was created (dry run without --execute)
python ug_migration_apply.py --profile P rollback --log wave1.jsonl --execute
```

- **Secrets:** prefer `--uc-secret-map` (Unity Catalog secret references). Each secret's schema must be in `--allowed-secret-schemas`; otherwise the run stops before any change. `--allow-secret-read` reads the workspace secret value at run time instead (only with `--execute`, and only with `--allow-secret-read-enabled`, the CLI equivalent of the installer's setting); it's never printed or logged. Literal keys found on legacy endpoints are redacted in every output (`<redacted plaintext XXXXXXXX>`).
- **Guardrails:** an endpoint with legacy guardrails that aren't migrated is blocked unless you pass `--ack-guardrails`. Set the service policies first, then acknowledge.
- **Providers in this prototype:** OpenAI, Azure OpenAI (API key) and Anthropic. Others (Bedrock, Gemini, Foundry, Entra auth, unmapped tasks) are reported as `manual`.
- **Idempotent:** a toolkit-owned service with the planned config is reused; anything else with the same name is `manual`. Grants are added only after the service reads back as planned.
- **Pre-checks:** the target schema must exist; PT endpoints whose model was deleted are reported as `manual`.
- **Validation before create:** traffic percentages must add up to 100, at most 10 primary and 5 fallback destinations, routes must name real served entities, and rate limits that can't be translated stop that endpoint as `manual`. Toolkit safety caps: 20 rate limits per model service, 5 of them group-specific. Hourly limits map to hourly limits.
- **Fallback:** with legacy fallback enabled, the 0%-traffic destinations become the fallback in listing order. If none is at 0%, no fallback is created and the item says so.
- **Smoke test (optional):** `--smoke` reads each created model service back (no inference calls).
- **Exit code** is 2 when anything ended as `error`, `manual`, `mismatch`, `needs_attention`, `smoke_failed` or `kept`.
- **Rollback** deletes only what this run's log shows it created, and only if the object still carries the toolkit's mark for that run. Changed objects are kept unless `--force`. A provider service is kept while a model service still uses it. Inference tables created by the services stay in place.
- **Terraform state** stores provider secret values in plaintext when you use input variables; protect the state, or use `--uc-secret-map`.
- After apply, re-run the planner with the same `--target-catalog`/`--target-schema`: `target_status` shows `exists` and the code fixes point to the real service names.

## Known limits

- Scanning only covers what's in the workspace. Code in external repos, apps outside Databricks and local developer machines (coding agents) isn't visible: use the callers table to find them.
- AI Search didn't accept `system.ai` embedding endpoints when this version was tested (October 30, 2026); as of that date Databricks indicated support around mid-November 2026 (not confirmed). Until then, indexes on legacy `databricks-*` embeddings block enforcement. If you must enforce sooner, one option is to switch those indexes to self-managed embeddings computed with `ai_query('system.ai.<embedding model>', ...)` and query them with `query_vector` (not tested by the toolkit; validate it first).
- `ai_query` can't call custom model services yet, so references to custom endpoints from `ai_query` are flagged, not rewritten.
- `system.ai` services are shared across the metastore. Legacy limits on `databricks-*` endpoints are flagged instead of copied.
- Other dashboards can count the backend leg of Unity Gateway calls as v1 traffic. This tool uses your own system tables.
