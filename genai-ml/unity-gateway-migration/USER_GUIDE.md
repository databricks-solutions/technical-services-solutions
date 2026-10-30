# Unity Gateway Migration Toolkit: User Guide

Version 0.7.0 (prototype)

> Prototype from Databricks Shared Technical Services (STS), provided as is. Planning and scans only read your workspace and system tables. Things are written only when you ask: the app and its jobs store results in the results schema (including matched code lines), snapshots append to tables, apply and rollback create or delete Unity Gateway services, and the dashboard step creates a dashboard. Review every result before acting on it.

---

## Contents

1. [What the toolkit does](#1-what-the-toolkit-does)
2. [Before you start](#2-before-you-start)
3. [Install](#3-install)
4. [The recommended migration process](#4-the-recommended-migration-process)
5. [Account view (`ug_migration_account.py`)](#5-account-view)
6. [Workspace planner (`ug_migration_planner.py`)](#6-workspace-planner)
7. [Reading the results](#7-reading-the-results)
8. [Apply, rollback and Terraform (`ug_migration_apply.py`)](#8-apply-rollback-and-terraform)
9. [Progress tracking: snapshots and dashboard](#9-progress-tracking)
10. [Running in Databricks: the app, notebooks and bundle](#10-running-in-databricks)
11. [Safety and data handling](#11-safety-and-data-handling)
12. [Troubleshooting](#12-troubleshooting)
13. [Limitations](#13-limitations)
14. [FAQ](#14-faq)
15. [Reference: files and options](#15-reference)

---

## 1. What the toolkit does

Legacy model serving endpoints are being retired: legacy v2 workspace endpoints stop serving first (on **November 30, 2026**) and v1 endpoints stop serving on **March 30, 2027**. These dates come from Databricks migration communications as of October 30, 2026; confirm them with your account team. Nothing moves to Unity Gateway automatically, and settings on legacy endpoints (rate limits, guardrails, inference tables, permissions) don't carry over.

The toolkit turns the migration into a guided, measurable process:

| Step | What it gives you | Tool |
|---|---|---|
| **Find** | Every legacy endpoint in the account, its traffic and callers, ranked by workspace and sorted into migration waves | Account view |
| **Plan** | For each endpoint, the Unity Gateway target and the settings to re-create | Workspace planner |
| **Fix code** | Every notebook, job, query, function, app, agent and repo that still calls a legacy endpoint, with the exact old and new line | Workspace planner |
| **Decide** | Whether each workspace is safe to enforce, and what's blocking it | Workspace planner (readiness report) |
| **Create** | The Unity Gateway services and grants for external model and PT endpoints, with rollback, or the same as Terraform | Apply |
| **Track** | Weekly snapshots and a dashboard showing legacy traffic falling and ready workspaces rising | Account view + dashboard |

What it **doesn't** do: it never edits your code, never changes or deletes legacy endpoints, and never turns on *Enforce Unity Gateway*. Those stay human decisions.

### Key terms

| Term | Meaning |
|---|---|
| **Legacy endpoint (v1)** | A model serving endpoint called at `/serving-endpoints/<name>/invocations`. Includes Databricks-hosted `databricks-*` endpoints, external model endpoints and Provisioned Throughput (PT) endpoints |
| **v2 endpoint** | A workspace AI Gateway endpoint (Beta, created Feb to Aug 2026) called at `/ai-gateway/...` with a plain model name |
| **Unity Gateway (v3)** | Unity Catalog governed AI traffic: **model services** (`catalog.schema.name`, including the built-in `system.ai.*`), **model provider services** (credentials for external providers) and MCP services |
| **Enforce Unity Gateway** | Workspace setting that blocks legacy `databricks-*` pay-per-token endpoints (calls fail with `PERMISSION_DENIED`) and allows new external model / PT endpoints only through Unity Gateway. Existing external model and PT endpoints stay queryable until they retire |
| **External/PT endpoints** | Legacy external model and Provisioned Throughput endpoints: the ones apply can create Unity Gateway services for. ("Custom ML model" endpoints are your own models and aren't affected.) |
| **Wave** | A group of workspaces migrated together, from "ready now" to "high volume" |

---

## 2. Before you start

### Requirements

| Need | Why |
|---|---|
| Python 3.10+ with `databricks-sdk>=0.158.0` and `requests` | To run the scripts locally (notebooks install the SDK themselves) |
| Databricks CLI with a profile for the workspace (`databricks auth login --host <url> --profile <name>`) | Authentication for local runs |
| A SQL warehouse (serverless is fine) | System table queries when running locally. Notebooks use their own Spark session instead |
| Terraform 1.x and Databricks provider 1.124.0+ | Only if you use the Terraform output |

### Permissions

| Task | Needs |
|---|---|
| Traffic and account view | `SELECT` on `system.serving.endpoint_usage`, `system.serving.served_entities`, `system.ai_gateway.usage`, `system.access.workspaces_latest`. By default only account admins can query these tables; admins can grant access to others |
| Inventory | Read access to serving endpoints and their permissions (workspace admin, or `CAN_VIEW` on the endpoints) |
| Code scan | Read access to the folders, jobs, queries, dashboards, apps, Genie Agents (formerly Genie spaces), pipelines and Unity Catalog objects to scan. The scan only sees what the identity can see |
| Apply | `USE CATALOG`, `USE SCHEMA` and `CREATE SERVICE` on the target schema; `EXECUTE` on the underlying model for PT wrappers; `MANAGE` or ownership to grant; access to the provider secrets |
| Callers after migration | `EXECUTE` on the model service plus `USE CATALOG` and `USE SCHEMA` on its catalog and schema. All account users have `EXECUTE` on `system.ai` services by default |
| Snapshots | `USE CATALOG`, `USE SCHEMA`, `CREATE TABLE` and `MODIFY` on the snapshot schema |
| Dashboard | Permission to create dashboards in the target folder and `CAN USE` on the warehouse |
| Deep scan of other workspaces | An identity that can log in to each of them, ideally one service principal assigned to all of them |

### Pick an identity

For one workspace, a workspace admin's CLI login is enough. For an account, use **one service principal** with account admin (for system tables) that is assigned to every workspace you want to deep-scan, and set `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET`. Only scan workspaces you are authorized to review.

---

## 3. Install

**Recommended: the installer notebook (everything inside the workspace, about 5 minutes).**

1. In the workspace, open **Workspace**, go to your home folder, and choose **Import**. Import the file `INSTALL_ug_migration_toolkit_<version>.py`.
2. Open the notebook. At the top, set **Results catalog** (an existing catalog where you can create a schema) and pick a **SQL warehouse**. The other widgets have defaults: results schema `ug_migration`, **Operators** = you, app name `ug-migration`, install folder in your home folder.
3. Click **Run all**. At the end it prints the link to the app, the dashboard and the three jobs (if you run it as a job, the links are also the notebook's result in the run output).

Before you apply anything from the app, create the target schema for the new model services (the scan form's **Target catalog** and **Target schema**, `ai_gateway.migrated` by default) and give the identity that runs the jobs `CREATE SERVICE` on it. Scans work without it; apply, including a dry run, stops if the schema is missing.

It needs: serverless compute for notebooks and jobs, Databricks Apps, and permission to create apps, jobs and (if missing) the schema. The jobs run as the person who runs the installer, so run it as someone with the permissions in section 2 (or as a service principal). To update, import the newer installer and run it again with the same widgets; history is kept. To change the operators, run it again with the **Operators** widget updated. To remove it, set **Action** to `uninstall` and run it again: the app, jobs, toolkit files and the `output` folder are deleted and the dashboard moves to Trash; results tables stay unless **Drop results tables** is `yes`; Unity Gateway services created by apply and the `apply_logs` folder stay (roll back first, section 8, if you want those services gone).

The other ways to install, for command-line use, CI/CD, or to change the bundle:

**A. Local (laptop or CI)**

```bash
unzip ug-migration-toolkit-0.7.0.zip && cd ug-migration-toolkit-0.7.0
python -m venv .venv && . .venv/bin/activate
pip install "databricks-sdk>=0.158.0" requests
python ug_migration_planner.py --help
```

**B. In a workspace as notebooks.** Upload the folder (or just `ug_migration_*.py` and `notebook/`) to a workspace folder, keeping the layout. Open `notebook/run_planner` or `notebook/run_account`. See [section 10](#10-running-in-databricks).

**C. As a Declarative Automation Bundle (CI/CD, or a Git folder).** Deploys the same things as the installer: the app, the snapshot job (paused), the scan and apply jobs, and the dashboard. From a Git folder in the workspace you can also deploy it with the bundle **Deploy** button instead of the CLI:

```bash
databricks bundle deploy -t dev \
  --var warehouse_id=<warehouse-id> --var snapshot_catalog=<catalog> --var snapshot_schema=<schema>
```

Then start the app with `databricks bundle run ug_migration_app -t dev --var ...`. Needs serverless jobs, an existing results schema, a warehouse, and user authorization for apps. See [section 10](#10-running-in-databricks).

---

## 4. The recommended migration process

| Phase | Do this | Toolkit |
|---|---|---|
| **0. Size it** | Run the account view. Note v2 workspaces (November 30, 2026 deadline), wave counts, the busiest endpoints and name collisions | `ug_migration_account.py` |
| **1. Inventory** | For each workspace in scope, run the planner. Give owners the "Who calls legacy endpoints" table and `CODE_FIXES.md` | `ug_migration_planner.py` |
| **2. Design** | Agree on the target catalog/schema, permission model (who may use which models) and provider secrets (UC secrets preferred). Decide what to do with AI Search (formerly Vector Search) indexes and Agent Bricks agents | Plan and readiness outputs |
| **3. Create** | For external model and PT endpoints, run apply as a dry run, then `--execute` one wave at a time (or use Terraform) | `ug_migration_apply.py` |
| **4. Move callers** | Owners apply code fixes, move tokens to the `ai-gateway` scope, redeploy apps and jobs, and grant each caller `EXECUTE` on its model service plus `USE CATALOG` and `USE SCHEMA` (apply copies the legacy endpoint permissions when grants are on) | `CODE_FIXES.md` |
| **5. Validate** | Re-run the planner. Traffic on legacy endpoints should drop to zero; `target_status` should be `exists` | Planner, `READINESS.md` |
| **6. Close** | Optionally rate-limit unused legacy endpoints to 0 (commands in `READINESS.md`). When the status is `READY`, a workspace admin enables *Enforce Unity Gateway* | `READINESS.md` |
| **7. Track** | Schedule weekly snapshots and share the dashboard | Bundle job + dashboard |

Typical order inside a workspace: **coding agents and simple SDK callers first, then apps, then `ai_query` jobs, then AI Search and agents last.**

---

## 5. Account view

`ug_migration_account.py` covers every workspace in the account in one run, using account-level system tables (it's always account-wide; `--workspace` picks workspaces to deep-scan, it doesn't filter the view). A run takes about 20 seconds for a hundred workspaces.

### Run it

```bash
python ug_migration_account.py --profile <profile> --warehouse-id <id> --out ./account_out --days 30
```

| Option | Default | Meaning |
|---|---|---|
| `--profile` | default auth | CLI profile (any workspace in the account) |
| `--warehouse-id` | none | SQL warehouse for the queries (not needed in a notebook) |
| `--out` | `./ug_account_out` | Output folder |
| `--days` | 30 | Traffic window |
| `--deep-scan N` | off | Also run the workspace planner on the N busiest workspaces |
| `--workspace <id>` | off | Deep-scan specific workspaces (repeatable) |
| `--deep-warehouse-id` | none | SQL warehouse **in the scanned workspaces** for their traffic and Unity Catalog queries. Without it those parts are reported as not confirmed (the account run's own Spark session is never used for another workspace) |
| `--target-catalog`, `--target-schema` | `ai_gateway`, `migrated` | Proposed target names. Deep scans use `<schema>_<workspace_id>` to avoid collisions |
| `--snapshot-table` | off | Append results to `<catalog.schema.prefix>_workspaces` and `_endpoints` (the only write) |

### What you get

- **`ACCOUNT_SUMMARY.md`:**
  - Requests for legacy v1, legacy v2 and Unity Gateway (distinct request IDs) and the share already on Unity Gateway.
  - Endpoints by kind and workspaces per wave.
  - The busiest workspaces and endpoints, and name collisions.
- **`account_workspaces.csv`:** one row per workspace (legacy endpoints, external/PT endpoints, active endpoints, v1 requests, legacy requests (v1 + v2), tokens, throttled, v2 and Unity Gateway requests, share on Unity Gateway, wave, hint).
- **`account_endpoints.csv`:** one row per live legacy endpoint (kind, provider, requests, callers, throttled, last request, creator).
- **`account_collisions.csv`:** custom endpoint names that exist in several workspaces.
- With a deep scan: **`workspaces/<id>/`** (the full workspace report) and **`deep_scans.json`**.

### Waves

| Wave | Rule | Next step |
|---|---|---|
| `v2 first` | v2 traffic in the window | Migrate before November 30, 2026 |
| `0: enforce candidate` | No legacy traffic and no external/PT endpoints | Run the workspace readiness check, then enforce |
| `1: cleanup` | External/PT endpoints but no traffic | Confirm with owners, retire or apply, then enforce |
| `1: small` | Under 10,000 legacy requests in the window | Migrate with the owners |
| `2: high volume` | 10,000+ legacy requests | Plan per workload |

### Deep-scan authentication

For each workspace URL the tool tries, in order:
1. The same host as `--profile`.
2. Any CLI profile in `~/.databrickscfg` with that host.
3. A service principal from `DATABRICKS_CLIENT_ID`/`DATABRICKS_CLIENT_SECRET`.
4. A CLI login for that host.

Failures are recorded in `deep_scans.json` and don't stop the run.

---

## 6. Workspace planner

`ug_migration_planner.py` analyzes one workspace in depth. It only reads: GET calls and read-only SQL (sent through the SQL Statement API).

### Run it

```bash
python ug_migration_planner.py --profile <profile> --warehouse-id <id> --out ./out --days 30
# Also scan cloned repos or bundle projects
python ug_migration_planner.py --profile <profile> --warehouse-id <id> --out ./out --local-path ~/src/rag-app
```

| Option | Default | Meaning |
|---|---|---|
| `--profile` | default auth | CLI profile for the workspace |
| `--warehouse-id` | none | SQL warehouse (not needed in a notebook) |
| `--out` | `./ug_migration_out` | Output folder |
| `--days` | 30 | Traffic window |
| `--target-catalog`, `--target-schema` | `ai_gateway`, `migrated` | Where proposed model services would live. **Use the same values as apply**, so the plan and code fixes show the real names |
| `--scan-root <path>` | `/Users`, `/Shared`, `/Repos` | Workspace folders to scan (repeatable) |
| `--max-objects` | 20000 | Cap on notebooks and files listed |
| `--threads` | 16 | Parallel API calls |
| `--local-path <folder>` | none | Also scan local folders (repeatable) |
| `--skip-scan` | off | Inventory, traffic and plan only |
| `--workspace-id` | auto | Override the detected workspace ID |

A full scan of about 3,600 notebooks and files takes about 3 minutes.

### What it looks at

| Area | Details |
|---|---|
| Serving endpoints | Every endpoint, classified as `system_ppt` (`databricks-*`), `external_model`, `provisioned_throughput`, `custom_model` or `agent`, with gateway settings, traffic split, tags and permissions |
| Traffic | Requests, callers and last request per endpoint from `system.serving.endpoint_usage`; callers resolved to service principal names |
| Code | Notebooks and files (identical copies such as app deployment snapshots reported once), jobs, saved SQL queries, dashboards, Genie Agents, Lakeflow pipeline settings, Unity Catalog SQL functions and views, environment variables of custom model endpoints, apps and their resources, and local folders |
| Dependencies | AI Search indexes on legacy embedding endpoints, Knowledge Assistants with AI Search sources, Supervisor Agents that use them, app serving-endpoint resources (workspace apps and bundle YAML) |

**Patterns detected:**
- `ai_query('databricks-...')`, including multi-line calls.
- `/serving-endpoints` URLs, including `/serving-endpoints/<name>/invocations` and OpenAI-style routes.
- `ChatDatabricks(endpoint=...)` or `ChatDatabricks(model=...)`, including calls over several lines (the fix uses `model=`, since `endpoint=` is a deprecated alias in databricks-langchain, and adds `use_ai_gateway=True`), and MLflow judge URIs `endpoints:/...`.
- Management API calls on legacy endpoints (`/api/2.x/serving-endpoints...`), reported without a rewrite.
- Quoted legacy endpoint names, and unquoted values in YAML/HCL/`.env` (`default: databricks-...`).
- Bundle `serving_endpoint:` resources.

---

## 7. Reading the results

The workspace planner writes these files:

| File | Use it for |
|---|---|
| `READINESS.md`, `readiness.json` | Whether you can enforce, and what blocks it |
| `SUMMARY.md` | Overview: endpoints, active endpoints, callers, provider services, items needing a human, code references |
| `CODE_FIXES.md` | Line-by-line changes per asset |
| `migration_plan.csv` | One row per legacy endpoint: target, destination, rate limits, routing, inference table, grants, tags, notes, traffic, `target_status` |
| `client_references.csv` | Every code reference: location, pattern, line, proposed fix and confidence |
| `callers.csv` | Caller to endpoint to the code found in the caller's folders |
| `provider_services.csv` | Provider services to create: provider, models, secret names (never values), legacy endpoints |
| `legacy_endpoints.csv`, `system_ai_map.json` | Raw inventory and the mapping from legacy `databricks-*` names to `system.ai` services |

### READINESS.md

**Status:**
- **READY:** nothing blocks enforcement.
- **INCOMPLETE:** no blockers found, but a scan surface failed, was cut off or was skipped, or traffic couldn't be confirmed from the system tables (`traffic`; listed with the reason). Readiness can't be confirmed and nothing is offered for closing.
- **READY_WITH_WARNINGS:** nothing breaks when you enforce, but work remains: code still references legacy endpoints, or external model / PT endpoints still get traffic (`legacy_traffic_kept_after_enforce`: Enforce leaves them queryable, but they retire with v1).
- **BLOCKED:** see the blockers.

| Blocker | Meaning | Action |
|---|---|---|
| `legacy_traffic` | A legacy `databricks-*` pay-per-token endpoint was called in the window; these calls fail under Enforce | Find the caller in `SUMMARY.md` / `callers.csv`; move it to the listed target |
| `vector_search` | An index embeds with a legacy endpoint | Re-index on a `system.ai` embedding service once AI Search supports it (expected around mid-November 2026), or switch to self-managed embeddings; don't enforce before |
| `agent_bricks_vector_search` | A Knowledge Assistant (or a Supervisor Agent using one) reads an AI Search index | Switch the source to files/volume, or wait for support |
| `app_resource` | An app or bundle uses a legacy serving-endpoint resource | Replace the resource, grant the app service principal `EXECUTE`, update the code |
| `ai_query_custom` | `ai_query` calls a custom legacy endpoint | Not supported on Unity Gateway yet; keep the legacy endpoint for now |
| `agent` | An agent is served on a model serving endpoint | Redeploy on Databricks Apps |

**"Can be closed now"** lists external model endpoints with no traffic, no dependents and no references, and only when traffic was confirmed and the scan was complete. Provisioned Throughput endpoints are never listed: their Unity Gateway services route through them. For each one it shows whether the Unity Gateway target exists, a close command that sets the endpoint rate limit to 0 while keeping its other rate limits and settings, and an undo command that restores the current configuration. The traffic window may miss rare callers: confirm with the owner first.

### CODE_FIXES.md

Each entry shows the asset, line number, confidence, old line (`-`) and new line (`+`):

| Confidence | Examples | What to do |
|---|---|---|
| `auto` | `ai_query('databricks-gpt-5-5', ...)` to `ai_query('system.ai.gpt-5-5', ...)`; `endpoints:/databricks-x` to `databricks:/system.ai.x` | Apply as is. `ai_query` on Unity Gateway only gets usage tracking (no rate limits, fallbacks, inference tables or service policies) |
| `review` | Base URLs to `/ai-gateway/mlflow/v1`, `/invocations` to `/chat/completions` (the request body changes to OpenAI format, with the model service as `model`), model names, `ChatDatabricks(..., use_ai_gateway=True)` (needs `databricks-langchain>=0.19.0`), YAML/Terraform values | Check and test |

When you change a URL, move the token from the `all-apis` PAT scope to `ai-gateway` (or use OAuth). An `ai-gateway`-scoped token on a legacy URL returns 403.

### migration_plan.csv: key columns

| Column | Meaning |
|---|---|
| `action` | `use_system_ai` (just change callers), `create_model_service` (apply can create it), `out_of_scope` (custom ML models), `manual` |
| `target_service` | Proposed or existing Unity Gateway name |
| `target_status` | `system`, `exists` or `missing` (checked live) |
| `rate_limits`, `routing`, `inference_table`, `grants` | What will be re-created on the target |
| `needs_human` | Decisions to make: guardrails (with specific service policy advice), retired models, endpoints open to all users, dependencies, zero-traffic endpoints to retire |

---

## 8. Apply, rollback and Terraform

`ug_migration_apply.py` creates the Unity Gateway objects that the plan proposes for **external model and Provisioned Throughput endpoints**. Databricks-hosted `databricks-*` endpoints need nothing new: their `system.ai` services already exist.

### What apply creates

| Object | From | Details |
|---|---|---|
| Model provider service | External model endpoints | One per provider + credential (endpoints sharing a key share one service); explicit model list (`allow_all_targets = false`) |
| Model service | Each external model or PT endpoint | Destinations and traffic split (must add up to 100); with legacy fallback enabled, served entities at 0% become ordered fallbacks (at most 5), otherwise 0% entities are left out; all rate-limit scopes; a new inference table `<prefix>_ug_payload` when the legacy endpoint had one enabled |
| Grants | Endpoint permissions | `CAN_QUERY` becomes `EXECUTE`, `CAN_MANAGE` becomes `EXECUTE` + `MANAGE`; `CAN_VIEW` alone grants nothing; workspace-local `admins`/`users` skipped |

It **doesn't** touch legacy endpoints, move callers or enable Enforce.

### Step by step

```bash
# 1. The target schema must exist
# 2. Dry run (default): shows what would be created, nothing changes
python ug_migration_apply.py --profile <p> apply --endpoints ep1,ep2 \
  --target-catalog ai_gateway --target-schema migrated \
  --uc-secret-map '{"llm/openai": "secrets/ai_gateway.migrated.openai_key"}'

# 3. Create, one wave at a time
python ug_migration_apply.py --profile <p> apply --endpoints ep1,ep2 \
  --target-catalog ai_gateway --target-schema migrated --uc-secret-map map.json \
  --execute --log wave1_log.jsonl

# 4. Re-run the planner with the same target to see target_status = exists
python ug_migration_planner.py --profile <p> --warehouse-id <id> --target-catalog ai_gateway --target-schema migrated

# Undo exactly what step 3 created (dry run first, then --execute)
python ug_migration_apply.py --profile <p> rollback --log wave1_log.jsonl
python ug_migration_apply.py --profile <p> rollback --log wave1_log.jsonl --execute
```

Note that `--profile` goes before the subcommand.

| Option (apply) | Meaning |
|---|---|
| `--endpoints a,b` / `--all` | One wave of legacy endpoints, or all external/PT endpoints |
| `--target-catalog`, `--target-schema` | Where to create the services |
| `--uc-secret-map` | JSON file or string: `"scope/key"` to `"secrets/catalog.schema.name"` (preferred) |
| `--allow-secret-read` | Instead, read the workspace secret value at run time, only with `--execute` (a dry run never reads it); never printed or logged |
| `--no-grants` | Skip grants |
| `--execute` | Actually create (otherwise dry run) |
| `--log` | Log of created objects for rollback (default `apply_log.jsonl`) |

### Results

Each line of output is a JSON record:

| Action | Meaning |
|---|---|
| `would_create`, `would_grant` | Dry run: what it would do |
| `created`, `granted` | Done |
| `exists` | Already there, skipped (safe to re-run) |
| `ok`, `mismatch` | The read-back check of the service matched or didn't |
| `manual` | Needs a person (unsupported provider, Entra auth, secret not mapped, PT endpoint serving a deleted model) |
| `error` | API error, with the message |
| `skipped` | Not an external/PT endpoint, or its provider service couldn't be created |
| `creating` | Logged just before a create call, so an interrupted run can still be rolled back |
| `would_delete`, `deleted`, `already_gone` | Rollback: what it would delete, what it deleted, objects already removed |
| `kept` | Rollback left the object: it lost the toolkit's mark, or another execute run created or reuses it |
| `note`, `skipped_lines` | Rollback notices: a create was interrupted; unreadable log lines were skipped |

**Supported providers:** OpenAI, Azure OpenAI (API key) and Anthropic. Others are reported as `manual`.

**Checks before creating:** traffic percentages add up to 100; at most 10 primary and 5 fallback destinations; routes name real served entities; every rate limit translates (hourly limits stay hourly; unknown keys or periods stop that endpoint as `manual`); an existing provider service with the same name must match the plan (provider, models, secret reference, base URL) or the endpoint is reported as `manual`. Provider service names are stable, built from the provider and the secret they use (`<provider>_<scope>_<key>`).

**Exit code:** 0 when everything succeeded or was skipped, 2 when anything ended as `error`, `manual` or `mismatch`.

**Rollback** deletes model services, then provider services, that the log shows as created (or as interrupted mid-create), and only if they still carry this tool's comment. Unreadable log lines are skipped and reported. Inference tables stay.

### Terraform instead of API calls

```bash
python ug_migration_apply.py --profile <p> terraform --endpoints ep1,ep2 \
  --target-catalog ai_gateway --target-schema migrated --out ug_migration.tf
terraform init && terraform plan
```

- **Resources written:** `databricks_ai_gateway_model_provider_service`, `databricks_ai_gateway_model_service` and `databricks_grants` (authoritative per new service). Provider requirement: `databricks/databricks >= 1.124.0`.
- **Secrets** become `sensitive` variables named `secret_<scope>_<key>`. Set them with `TF_VAR_secret_<scope>_<key>`, or use `--uc-secret-map` for UC secret references. Values are never read.
- **Checks:** the output passes `terraform validate` and `terraform fmt -check`.
- **State:** with input variables, Terraform stores the secret values in its state in plaintext. Protect the state, or prefer `--uc-secret-map`.

---

## 9. Progress tracking

### Snapshots

Each account-view run with `--snapshot-table catalog.schema.prefix` appends:
- **`<prefix>_workspaces`:** one row per workspace (legacy endpoints, active endpoints, v1 requests, legacy requests (v1 + v2), tokens, throttled, v2, Unity Gateway requests, share on Unity Gateway, wave).
- **`<prefix>_endpoints`:** one row per live legacy endpoint (kind, provider, requests, callers, throttled, last request).

Each row has a `snapshot_time`. Example burn-down query:

```sql
SELECT snapshot_time, sum(legacy_requests) AS legacy, sum(v3_requests) AS unity_gateway,
       count_if(wave LIKE '0%') AS enforce_candidates
FROM main.ug_migration.snap_workspaces
GROUP BY snapshot_time ORDER BY snapshot_time
```

### Dashboard

```bash
python ug_migration_dashboard.py --profile <p> --warehouse-id <id> \
  --snapshot-table main.ug_migration.snap --parent-path /Workspace/Users/me@x.com/ug-migration --publish
# Update later (same link)
python ug_migration_dashboard.py --profile <p> --warehouse-id <id> \
  --snapshot-table main.ug_migration.snap --dashboard-id <id> --publish
```

**Contents:**
- **KPIs:** legacy requests (v1 + v2), share of model traffic on Unity Gateway, active legacy endpoints, enforce candidates.
- **Trends:** legacy vs Unity Gateway traffic; active endpoints vs ready workspaces.
- **Waves:** workspaces by wave.
- **Tables:** workspaces and busiest legacy endpoints from the latest snapshot.

`--json-only file.json` writes the definition without deploying (no warehouse needed).

---

## 10. Running in Databricks

### The app (recommended)

The installer (or the bundle) deploys **Unity Gateway Migration**, a Databricks App that keeps the day-to-day process in one place: snapshots, scans, readiness, code fixes and apply. Account deep scans of other workspaces, Terraform output and scanning local folders stay command-line only.

| Tab | What you do there |
|---|---|
| **Overview** | See every workspace with legacy endpoints or Unity Gateway traffic, its wave, the share already on Unity Gateway and the trend across snapshots. **Refresh account snapshot** starts the account snapshot job. |
| **Scans** | Start a workspace scan (traffic window, extra scan roots, target catalog and schema). It reads the workspace; results go to the results schema. Open a scan to see readiness, endpoints, callers, code fixes (diffs) and all client references, plus copyable close and undo commands. |
| **Apply** | Pick a scan, choose external model and PT endpoints, map API keys to UC secrets (or allow reading the existing secret), then **Dry run**. **Execute** needs the word `EXECUTE` typed in. Every run is kept in the history; **Roll back** an execute run by typing `ROLLBACK`. |
| **About** | Dates, the recommended order of work and the identity model. |

How it works:

- **Scans, snapshots and applies run as Lakeflow jobs** **under the identity that installed the app** (the person who ran the installer, or the identity that deployed the bundle). The installer names them `[<app name>] Unity Gateway migration workspace scan`, `... snapshot` and `... apply`; the bundle names them `[<target>] Unity Gateway migration ...` (resources `ug_migration_scan`, `ug_migration_snapshot`, `ug_migration_apply`). For a shared install, use a service principal so the jobs don't run with a person's rights. The app's service principal has `CAN_MANAGE_RUN` on these three jobs and `CAN USE` on the warehouse, nothing else. The apply job runs one at a time.
- **Operators and viewers.** Only the users in **Operators** (installer widget, or the bundle variable `operators`; comma-separated emails; default: the person who installed) can start snapshots, scans and apply runs. Everyone else who can open the app sees results only. Because jobs act with the deployer's rights, keep the operators list short.
- **Results go to Delta tables** in the results schema (installer: **Results catalog** and **Results schema**; bundle: `<snapshot_catalog>.<snapshot_schema>`): `ug_migration_scans`, `ug_migration_scan_items`, `ug_migration_applies`, `ug_migration_apply_items`, plus the snapshot tables `ug_migration_workspaces` and `ug_migration_endpoints`.
- **Pages read those tables as the signed-in user** (user authorization with the `sql` scope) through the SQL warehouse, so Unity Catalog permissions on the results schema decide who sees what. Each app user needs `CAN USE` on the app, `CAN USE` on the warehouse, and `USE CATALOG`, `USE SCHEMA` and `SELECT` on the results schema.
- **Scans store code excerpts.** Matched code lines from every scanned folder are stored in the results schema (credential-looking values are replaced with `<hidden>`). Keep the schema limited to the migration team.
- Scan and apply runs record **who asked for them** (`requested_by`); snapshot runs show up in the job's run history. Secret values never go to the results tables or logs; apply results are masked. With "read the workspace secret values" (`--allow-secret-read`), apply copies the key value into the Unity Gateway provider service itself; prefer Unity Catalog secret references. Endpoints that use a plaintext API key stop as `manual`: store the key as a Unity Catalog secret first.
- **Rollback** rebuilds the undo list from the stored execute results (or, if the execute run was interrupted, from the log it wrote as it went, in `apply_logs/` next to the toolkit files). Each execute run can be rolled back once. Rollback keeps objects that another execute run created, and provider services that another run's new model services use. Re-running the same selection doesn't take ownership: roll back the run that created the services.

Install it with the installer notebook (section 3) or the bundle (next section), then open the app from **Compute, Apps** (`ug-migration` by default with the installer, `ug-migration-app` with the bundle; with the bundle, start it with `databricks bundle run ug_migration_app -t dev --var ...`). The jobs' identity needs the permissions in section 2 (system table access, workspace admin or read access to what you scan, `CREATE SERVICE` on the target schema for apply) plus `USE CATALOG`, `USE SCHEMA`, `CREATE TABLE` and `MODIFY` on the results schema.

### Notebooks

| Notebook | Widgets | Writes |
|---|---|---|
| `notebook/run_planner` | `out_dir` (workspace or volume path; default next to the notebook), `days`, `scan_root` | Output files only |
| `notebook/run_account` | `days`, `out_dir`, `snapshot_table` (blank = none), `deep_scan` (N) | Output files; snapshot tables if set |
| `notebook/run_scan` | Set by the app (`run_id`, `results_schema`, `days`, `scan_roots`, target) | `ug_migration_scans`, `ug_migration_scan_items` |
| `notebook/run_apply` | Set by the app (`mode`, `endpoints`, target, `uc_secret_map`, `rollback_of`) | Unity Gateway services and grants (execute only); `ug_migration_applies`, `ug_migration_apply_items` |

They run on serverless job compute (the bundle sets no cluster, so the workspace needs serverless jobs), install the SDK themselves and use the notebook's Spark session for system tables (no warehouse needed). Keep `ug_migration_*.py` in the notebook's folder or one level up.

### Bundle

`databricks.yml` deploys:
- The toolkit files and the notebooks.
- **`ug_migration_app`:** the app described above (name `ug-migration-app`).
- **`ug_migration_snapshot`:** a weekly job (Mondays 06:00 UTC), **deployed paused**, that runs the account view and appends to `<snapshot_catalog>.<snapshot_schema>.ug_migration_*`.
- **`ug_migration_scan`** and **`ug_migration_apply`:** the jobs the app starts (no schedule).
- **`ug_migration_progress`:** the dashboard, bound to the snapshot schema.

```bash
databricks bundle validate -t dev --var warehouse_id=<id> --var snapshot_catalog=<c> --var snapshot_schema=<s>
databricks bundle deploy   -t dev --var ...
databricks bundle run ug_migration_snapshot -t dev --var ...   # first snapshot now
databricks bundle run ug_migration_app -t dev --var ...        # start the app
# Unpause the job in the UI (or set pause_status: UNPAUSED) for weekly runs
databricks bundle destroy  -t dev --var ...                    # remove the app, jobs, dashboard and files
```

| Variable | Meaning |
|---|---|
| `warehouse_id` | Warehouse for the app and the dashboard |
| `snapshot_catalog`, `snapshot_schema` | Where snapshot tables go (must exist) |
| `days` | Traffic window (default 30) |
| `operators` | Emails of the users who can start jobs from the app (default: you) |

**Shared install (`prod` target):** deploy while authenticated as a service principal (for example `DATABRICKS_CLIENT_ID` / `DATABRICKS_CLIENT_SECRET`) that has the permissions above. The jobs then run as that service principal, and the files live in its home folder, which other users can't edit. Pass `--var operators=a@x.com,b@x.com`.

**Update:** unzip the new version and run `databricks bundle deploy` again with the same variables; history in the results tables is kept. A redeploy (and a rerun of the installer) sets the weekly snapshot schedule back to paused; unpause it again if you use it. **Uninstall:** `bundle destroy` doesn't delete data. Drop the results tables (`ug_migration_scans`, `_scan_items`, `_applies`, `_apply_items`, `_workspaces`, `_endpoints`) and the `apply_logs` folder when you no longer need them. Unity Gateway services created by apply stay until you roll them back or delete them.

Use catalog and schema names made of letters, digits and underscores for the results schema. **One dashboard is enough:** the installer and the bundle each create the progress dashboard; use `ug_migration_dashboard.py --publish` only when you run snapshots from the command line without either.

---

## 11. Safety and data handling

| Topic | Behavior |
|---|---|
| **Read-only by default** | The planner, account view and code scan only make GET calls and run read-only SQL |
| **Writes** | Only `apply --execute`, `rollback --execute`, snapshots and dashboard deployment write anything |
| **Legacy endpoints** | Never modified or deleted by the toolkit. The rate-limit-0 commands are printed for you to run |
| **Code** | Never edited. Fixes are proposals |
| **Secrets** | Reports show secret names (`scope/key`), never values; literal keys found on legacy endpoints are redacted. Apply reads a value only with `--allow-secret-read --execute`, and never prints or logs it. Environment variables that reference secrets are skipped by the scan |
| **What's in the reports** | Endpoint names, user and service principal identifiers, workspace names and code lines that mention legacy endpoints. Treat outputs as internal to the organization |
| **Scope** | Only scan workspaces you're authorized to review |

---

## 12. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "0 endpoints with traffic" but you know there's traffic | No access to `system.serving.*`, or the window is too short | Grant `SELECT`, run as an account admin, or raise `--days`. The tool reads the workspace ID from the API response header; override with `--workspace-id` if needed |
| INCOMPLETE with `traffic` under "Incomplete scan" | No warehouse locally, no access to the system tables, or no rows for this workspace | Pass `--warehouse-id` (or run the notebook), grant `SELECT` on the system tables, and check the workspace ID in `readiness.json` |
| Scan stops at `--max-objects` | Large workspace | Raise `--max-objects`, or scan specific `--scan-root` folders |
| Apply: `Target schema ... doesn't exist` | Schema missing | Create it first; apply never creates schemas |
| Apply: `manual: secret ...` | Secret not mapped | Add it to `--uc-secret-map`, or pass `--allow-secret-read` |
| Apply: inference table already exists | Name in use | New services use `<prefix>_ug`; if that's taken too, change the legacy prefix or remove the table |
| Apply: `manual: PT endpoint serves ..., which no longer exists` | The PT endpoint's model was deleted | Retire or redeploy the PT endpoint |
| Readiness is `INCOMPLETE` | A scan surface failed, was cut off or was skipped | See "Incomplete scan" in `READINESS.md`; fix access or raise `--max-objects`, then run again |
| Apply exits with code 2 | Something ended as `error`, `manual` or `mismatch` | Read the JSON lines with those actions; fix and re-run (existing objects are skipped) |
| Apply: `already exists with a different configuration` | A provider service with that name exists but differs | Rename the target schema, or reconcile the provider by hand |
| Account summary shows "Query errors" | A system table query failed | No snapshot is written for that run; fix access and run again |
| Deep scan: `can't authenticate` | No credentials for that workspace | Use a service principal assigned to it, or `databricks auth login --host <url>` |
| Code fix points to `ai_gateway.migrated.*` but you created services elsewhere | Planner run with default target | Re-run the planner with the same `--target-catalog`/`--target-schema` as apply |
| Dashboard shows nothing | No snapshots yet, or wrong schema | Run the account view with `--snapshot-table`, or the bundle job once |
| Numbers differ from other Databricks dashboards | Different sources and windows | Base decisions on the toolkit's numbers (from your own system tables) and expect differences from other dashboards |
| Installer: `Results catalog ... doesn't exist` | Catalog missing or not visible to you | Pick an existing catalog you can create a schema in |
| App shows "No user token" (401) | User authorization isn't enabled for the app | Re-run the installer (it sets the `sql` scope), or add `user_api_scopes: [sql]` to the bundle app |
| App: "Only the app's operators can start ..." (403) | You aren't in Operators | Re-run the installer with your email added to **Operators** (bundle: `--var operators=...`) |
| App: "A scan is already running" / "Another apply run is in progress" (409) | One run of each job at a time | Wait for it to finish (see the job run link) |
| App pages are empty after a scan | No `SELECT` on the results schema, or a different results schema | Grant `USE CATALOG`, `USE SCHEMA` and `SELECT`; check **Results schema** |
| Installer: app name already exists | Another app uses the name | Choose another **App name**, or uninstall the old install first |

---

## 13. Limitations

- **Prototype:** test on a non-production workspace first and review every result.
- **Apply providers:** OpenAI, Azure OpenAI (API key) and Anthropic only. Bedrock, Gemini, Microsoft Foundry and Azure Entra auth are manual.
- **AI Search:** AI Search didn't accept `system.ai` embedding endpoints when this version was tested (October 30, 2026); as of that date Databricks indicated support around mid-November 2026 (not confirmed). Until then, indexes on legacy `databricks-*` embeddings block enforcement. If you must enforce sooner, one option is to switch those indexes to self-managed embeddings computed with `ai_query('system.ai.<embedding model>', ...)` and query them with `query_vector` (not tested by the toolkit; validate it first).
- **`ai_query`:** can't call custom model services yet, so `ai_query` on custom legacy endpoints stays on legacy for now.
- **Code outside the workspace:** only visible with `--local-path`. Coding agents on developer laptops show up as callers, not code.
- **MLflow judges:** judges registered in experiments aren't scanned (no public API); judge URIs in notebook code are.
- **Usage data:** can lag by a few hours, and the traffic window (30 days by default) can miss rare callers. Caller-to-code linking works when the code lives in the caller's folder (for example an app's service principal folder).
- **Budgets:** Unity Gateway budgets cover pay-per-token usage; tracking external model usage is an opt-in Beta option and Provisioned Throughput isn't tracked (as of October 30, 2026).

---

## 14. FAQ

**Is this the same as the migration notebook in the Databricks knowledge base?**
No. The knowledge base runbook inventories endpoints and migrates one workload at a time, copying basic rate limits. This toolkit covers the whole workspace or account, plans every endpoint, finds the code to change, reports readiness, creates services in waves with rollback, and tracks progress. They work well together.

**Do I need apply if we only use Databricks-hosted models?**
No. `databricks-*` endpoints map to existing `system.ai` services. The work is changing callers (`CODE_FIXES.md`) and permissions, then enforcing.

**Does apply cause downtime?**
No. It creates new services next to the legacy endpoints. Callers keep using legacy endpoints until their code changes.

**Can I run it repeatedly?**
Yes. The planner and account view are read-only. Apply skips existing objects. Snapshots append a new point each run.

**How do I know a workspace is done?**
`READINESS.md` says `READY`, the busiest-endpoints table is empty for that workspace, and its wave is `0: enforce candidate`. Then enable *Enforce Unity Gateway*.

**Who should own what?**
- **Platform or account admins:** the account view, apply, snapshots and enforcement.
- **Application, job and app owners:** the code fixes, using `callers.csv` to route them.

---

## 15. Reference

### Files

| File | Purpose |
|---|---|
| `ug_migration_planner.py` | Workspace inventory, traffic, plan, code scan, readiness, code fixes |
| `ug_migration_account.py` | Account view, waves, deep scans, snapshots |
| `ug_migration_apply.py` | Apply, rollback, Terraform export |
| `ug_migration_dashboard.py` | Progress dashboard |
| `ug_migration_store.py` | Delta tables for the app's scan and apply runs |
| `notebook/run_planner.py`, `notebook/run_account.py` | Notebook entry points (one workspace, account view and snapshots) |
| `notebook/run_scan.py`, `notebook/run_apply.py` | Job notebooks the app starts (scan; dry run, execute and rollback) |
| `app/` | The Unity Gateway Migration app (FastAPI backend, React frontend build in `app/frontend/static`) |
| `INSTALL_ug_migration_toolkit_<version>.py` | Installer notebook (shipped separately): installs, updates or removes everything inside a workspace |
| `dashboard/ug_migration_progress.lvdash.json` | Dashboard definition used by the bundle |
| `databricks.yml` | Bundle: app, snapshot, scan and apply jobs, dashboard |
| `HOW_TO_READ.md` | Short guide to the outputs |
| `README.md` | Technical overview |

### Command summary

```bash
# Account view (+ optional deep scans and snapshot)
python ug_migration_account.py --profile P --warehouse-id W --out ./account_out [--days 30] \
  [--deep-scan N | --workspace ID ...] [--deep-warehouse-id W2] [--target-catalog C --target-schema S] \
  [--snapshot-table c.s.prefix]

# Workspace planner
python ug_migration_planner.py --profile P --warehouse-id W --out ./out [--days 30] [--workspace-id ID] \
  [--target-catalog C --target-schema S] [--scan-root PATH ...] [--local-path DIR ...] [--skip-scan] \
  [--max-objects 20000] [--threads 16]

# Apply (dry run unless --execute), Terraform, rollback
python ug_migration_apply.py --profile P apply (--endpoints a,b | --all) --target-catalog C --target-schema S \
  [--uc-secret-map MAP | --allow-secret-read] [--no-grants] [--execute] [--log FILE]
python ug_migration_apply.py --profile P terraform (--endpoints a,b | --all) --target-catalog C --target-schema S \
  [--uc-secret-map MAP] [--no-grants] [--out FILE.tf]
python ug_migration_apply.py --profile P rollback --log FILE [--execute]

# Dashboard
python ug_migration_dashboard.py --profile P --warehouse-id W --snapshot-table c.s.prefix \
  --parent-path /Workspace/... [--dashboard-id ID] [--publish] [--json-only FILE]
```
