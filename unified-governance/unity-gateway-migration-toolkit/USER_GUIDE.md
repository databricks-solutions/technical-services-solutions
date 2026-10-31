# Unity Gateway Migration Toolkit: User Guide

Version 0.9.0 (prototype)

> Prototype from Databricks Shared Technical Services (STS), provided as is. Planning and scans only read your workspace and system tables. Things are written only when you ask: the app and its jobs store results in the results schema (including matched code lines), snapshots append to tables, and apply and rollback create or delete Unity Gateway services. Review every result before acting on it.

---

## Contents

1. [What the toolkit does](#1-what-the-toolkit-does)
2. [Before you start](#2-before-you-start)
3. [Install, update and remove (including upgrades from 0.7.0 and 0.8.0)](#3-install)
4. [The recommended migration process (runbook)](#4-the-recommended-migration-process)
5. [Account view (`ug_migration_account.py`)](#5-account-view)
6. [Workspace planner (`ug_migration_planner.py`)](#6-workspace-planner)
7. [Reading the results](#7-reading-the-results)
8. [Apply, rollback and Terraform (`ug_migration_apply.py`)](#8-apply-rollback-and-terraform)
9. [Progress tracking: snapshots, charts and exports](#9-progress-tracking)
10. [Running in Databricks: the app, notebooks and bundle](#10-running-in-databricks)
11. [Safety and data handling](#11-safety-and-data-handling)
12. [Troubleshooting](#12-troubleshooting)
13. [Limitations](#13-limitations)
14. [FAQ](#14-faq)
15. [Reference: files and options](#15-reference)

---

## 1. What the toolkit does

Legacy model serving endpoints are being retired: legacy v2 workspace endpoints stop serving first (on **November 30, 2026**) and v1 endpoints stop serving on **March 30, 2027**. These dates come from Databricks migration communications as of October 30, 2026; confirm them with your account team. Nothing moves to Unity Gateway automatically. For external model and PT endpoints, apply re-creates rate limits, routing, inference tables and grants. Guardrails, budget policies and usage policies on legacy endpoints don't carry over and need a person. Legacy rate limits, guardrails and inference tables on `databricks-*` endpoints are reported, not copied.

The toolkit turns the migration into a guided, measurable process:

| Step | What it gives you | Tool |
|---|---|---|
| **Find** | Every legacy endpoint in the account, its traffic and callers, ranked by workspace and sorted into migration waves | Account view |
| **Plan** | For each endpoint, the Unity Gateway target and the settings to re-create | Workspace planner |
| **Fix code** | Every notebook, job, query, function, app, agent and repo that still calls a legacy endpoint, with the exact old and new line | Workspace planner |
| **Decide** | Whether each workspace is safe to enforce, and what's blocking it | Workspace planner (readiness report) |
| **Create** | The Unity Gateway services and grants for external model and PT endpoints, with rollback, or the same as Terraform | Apply |
| **Track** | Weekly snapshots and in-app charts showing legacy traffic falling and ready workspaces rising, with CSV exports | Account view + app |

What it **doesn't** do: it never edits your code, never changes or deletes legacy endpoints, and never turns on *Enforce Unity Gateway*. Those stay human decisions.

### Key terms

| Term | Meaning |
|---|---|
| **Legacy endpoint (v1)** | A model serving endpoint called at `/serving-endpoints/<name>/invocations`. Includes Databricks-hosted `databricks-*` endpoints, external model endpoints and Provisioned Throughput (PT) endpoints |
| **v2 endpoint** | A workspace AI Gateway endpoint (Beta, created Feb to Aug 2026) called at `/ai-gateway/...` with a plain model name |
| **Unity Gateway (v3)** | Unity Catalog governed AI traffic: **model services** (`catalog.schema.name`, including the built-in `system.ai.*`), **model provider services** (credentials for external providers) and MCP services |
| **Enforce Unity Gateway** | Workspace admin setting that blocks legacy `databricks-*` pay-per-token endpoints (calls fail with `PERMISSION_DENIED`) and allows new external model / PT endpoints only through Unity Gateway. Existing external model and PT endpoints stay queryable until they retire. Confirm the exact location in current Databricks docs |
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
| Apply | `USE CATALOG`, `USE SCHEMA` and `CREATE SERVICE` on the target schema; `EXECUTE` on the underlying model for PT wrappers; `MANAGE` or ownership to grant; read access to each Unity Catalog secret in the secret map (the dry run checks it exists without reading the value) |
| Callers after migration | `EXECUTE` on the model service plus `USE CATALOG` and `USE SCHEMA` on its catalog and schema. All account users have `EXECUTE` on `system.ai` services by default |
| Snapshots | `USE CATALOG`, `USE SCHEMA`, `CREATE TABLE` and `MODIFY` on the snapshot schema |
| Deep scan of other workspaces | An identity that can log in to each of them, ideally one service principal assigned to all of them |

### Pick an identity

For one workspace, a workspace admin's CLI login is enough. For an account, use **one service principal** with account admin (for system tables) that is assigned to every workspace you want to deep-scan, and set `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET`. Only scan workspaces you are authorized to review.

---

## 3. Install

**Recommended: the installer notebook (everything inside the workspace, about 5 minutes).**

1. Download `unity-gateway-migration-toolkit-0.9.0.zip` and unzip it. In the workspace, open **Workspace**, go to your home folder, and choose **Import**. Import `INSTALL_unity_gateway_migration_toolkit_0_9_0.py` from the unzipped folder (the installer is at the top of the zip). Only that file goes into the workspace: it carries the rest of the toolkit and writes it to the install folder.
2. Open the notebook. At the top, set **Results catalog** (an existing catalog where you can create a schema) and pick a **SQL warehouse**. The other widgets have defaults (table below).
3. Click **Run all**. It runs read-only checks first and stops with a list of what to fix if one fails ("Nothing was changed"). Otherwise it prints the link to the app and the three jobs (if you run it as a job, the links are also the notebook's result in the run output).

| # | Widget | Default | What it does |
|---|---|---|---|
| 1 | Action | install | `install` or `uninstall` |
| 2 | Results catalog | `main` | Must exist; the results schema is created in it |
| 3 | Results schema | blank | Blank = `ug_migration` for the default app name, else the app name with `_` for `-`. A blank widget reuses the schema of an existing install of the same app |
| 4 | SQL warehouse | first one | Warehouse the app and the notebook's checks use |
| 5 | Operators | blank | Emails, comma-separated; blank = you. Required when the notebook runs as a service principal |
| 6 | App name | `unity-gateway-migration` | 2 to 30 characters |
| 7 | Install folder | blank | Blank = `/Workspace/Users/<you>/<app name>-toolkit` (the older folder for the default app name). A blank widget reuses the folder of an existing install of the same app |
| 8 | Drop results tables | no | Uninstall only. Refused if another install reads the same results schema |
| 9 | Adopt existing app | no | Lets install or uninstall replace or delete an app whose description isn't a toolkit app |
| 10 | Allow downgrade | no | Needed to install an older version over a newer one |
| 11 | Allow a second install | no | Lets a second install (another app name) run in the same workspace. It still needs its own results schema and install folder |
| 12 | Allowed secret schemas | blank | Comma-separated `catalog.schema`. Blank = Unity Catalog secret mapping is off |
| 13 | Allow reading secret values | no | Lets apply copy workspace secret values into provider services (fixed on the apply job) |

The notebook refuses to continue when: the app name belongs to another toolkit install (the message names it: set App name to that name to update it, or uninstall it first); the results schema or folder is used by another install; the results schema's comment says it belongs to another app; the install folder path is not under `/Workspace/Users/...` or `/Workspace/Shared/...`; the SQL warehouse can't run the system table check; or an apply run is active (uninstall only).

Before you apply anything from the app, create the target schema for the new model services (the scan form's **Target catalog** and **Target schema**, `ai_gateway.migrated` by default) and give the identity that runs the jobs `CREATE SERVICE` on it. Scans work without it; apply, including a dry run, stops if the schema is missing.

It needs: serverless compute for notebooks and jobs, Databricks Apps, and permission to create apps, jobs and (if missing) the schema. The jobs run as the person who runs the installer, so run it as someone with the permissions in section 2 (or as a service principal). To update, import the newer installer and run it again with the same widgets; history is kept. To change the operators, run it again with the **Operators** widget updated. To remove it, set **Action** to `uninstall` and run it again: the app, jobs, toolkit files and the `output` folder are deleted; results tables stay unless **Drop results tables** is `yes`; Unity Gateway services created by apply and the `apply_logs` folder (in the install folder) stay. Roll back first (section 8) if you want those services gone, and see "Rollback after uninstall" in section 8.

On update the installer also keeps the app's own settings (budget policy, usage policy, compute size and so on), removes files that a newer version dropped from the install folder, and keeps the weekly snapshot's paused or unpaused state. It moves the dashboard **Unity Gateway migration progress** (created by versions before 0.8.0) to Trash, since charts and exports are now in the app.

#### Upgrading from 0.8.0 or 0.7.0

- **From 0.8.0:** run the 0.9.0 installer with the same widgets. Schemas and folders from 0.8.0 are reused. Allowed secret schemas is blank, so Unity Catalog secret mapping stays off until you list the schemas (section 4). Downgrades are refused unless **Allow downgrade** is `yes`.
- **From 0.7.0:** the default app name was `ug-migration`. In 0.9.0 the default is `unity-gateway-migration`, so the installer stops and names the existing install. To update that install in place, set **App name** to `ug-migration`. Otherwise uninstall the old install first (keeping its results and apply logs as needed), then install with the new default name.
- **Changes to know, from both:**
  - The app's charts and exports are in the app (Overview and Scans). The old dashboard is no longer created.
  - **Grants are off by default in the app** (tick "Copy legacy endpoint permissions" to include them). The command-line tool still copies grants unless you pass `--no-grants`.
  - **Execute requires a matching dry run** of the same selection and options. The app refuses an execute that doesn't match.
  - **Scans older than 14 days need confirmation** before apply (the app offers "apply anyway"). The limit is fixed at 14 days.
  - **Guardrails need an explicit acknowledgement** (`--ack-guardrails` on the command line, the guardrails checkbox in the app) before an endpoint with legacy guardrails can be applied.
  - **The bundle's app is renamed** from `unity-gateway-migration` to `ug-migration-bundle`. Run `databricks bundle plan -t <target>` before a deploy over an existing bundle deployment: the plan creates a new app, so delete the old app by hand afterwards.
  - **New widgets:** Allowed secret schemas, Allow reading secret values, Adopt existing app, Allow a second install, Allow downgrade (table above).
  - **New wording in the account view:** wave 0 is now `0: no legacy traffic` (it was `0: enforce candidate`). It means no v1 requests, not ready. Also `0: traffic unknown`, `no endpoint data` and `not running` (section 5).

The other ways to install, for command-line use, CI/CD, or to change the bundle, use the rest of the same zip:

**A. Local (laptop or CI)**

```bash
unzip unity-gateway-migration-toolkit-0.9.0.zip && cd unity-gateway-migration-toolkit-0.9.0
python -m venv .venv && . .venv/bin/activate
pip install "databricks-sdk>=0.158.0" requests
python ug_migration_planner.py --help
```

**B. In a workspace as notebooks.** Upload the folder (or just `ug_migration_*.py` and `notebook/`) to a workspace folder, keeping the layout. Open `notebook/run_planner` or `notebook/run_account`. See [section 10](#10-running-in-databricks).

**C. As a Declarative Automation Bundle (CI/CD, or a Git folder).** Deploys the same things as the installer: the app, the snapshot job (paused), and the scan and apply jobs. From a Git folder in the workspace you can also deploy it with the bundle **Deploy** button instead of the CLI:

```bash
databricks bundle deploy -t dev \
  --var warehouse_id=<warehouse-id> --var snapshot_catalog=<catalog> --var snapshot_schema=<schema>
```

Then start the app with `databricks bundle run ug_migration_app -t dev --var ...`. Needs serverless jobs, an existing results schema, a warehouse, and user authorization for apps. The bundle's app is named `ug-migration-bundle` by default (variable `app_name`), so it doesn't collide with an installer app. See [section 10](#10-running-in-databricks).

---

## 4. The recommended migration process

| Phase | Do this | Toolkit |
|---|---|---|
| **0. Size it** | Run the account view. Note v2 workspaces (November 30, 2026 deadline), wave counts, the busiest endpoints and name collisions | `ug_migration_account.py` |
| **1. Inventory** | For each workspace in scope, run the planner. Give owners the "Who calls legacy endpoints" table and `CODE_FIXES.md` | `ug_migration_planner.py` |
| **2. Design** | Agree on the target catalog/schema, permission model (who may use which models) and provider secrets (UC secrets preferred). Decide what to do with AI Search (formerly Vector Search) indexes and Agent Bricks agents | Plan and readiness outputs |
| **3. Create** | For external model and PT endpoints, run apply as a dry run, then `--execute` one wave at a time (or use Terraform) | `ug_migration_apply.py` |
| **4. Move callers** | Owners apply code fixes, move tokens to the `ai-gateway` scope, redeploy apps and jobs, and grant each caller `EXECUTE` on its model service plus `USE CATALOG` and `USE SCHEMA` (apply copies the legacy endpoint permissions when grants are on) | `CODE_FIXES.md` |
| **5. Validate** | Re-run the scan with `--days 7` to watch traffic fall. `READY` needs zero legacy requests in the whole window (30 days by default), so callers moved today still show; `target_status` should be `exists` | Planner, `READINESS.md` |
| **6. Close** | Optionally rate-limit unused legacy endpoints to 0 (commands in `READINESS.md`). When the status is `READY`, a workspace admin enables *Enforce Unity Gateway* (workspace admin settings; confirm the location in current Databricks docs) | `READINESS.md` |
| **7. Track** | Schedule weekly snapshots and follow the Overview charts (export them to share) | Snapshot job + app |

Typical order inside a workspace: **coding agents and simple SDK callers first, then apps, then `ai_query` jobs, then AI Search and agents last.**

### Runbook details

**Before apply (phase 3)**

1. **Target schema.** Create the schema for the new model services (`--target-catalog` / `--target-schema`, default `ai_gateway.migrated`). Apply never creates schemas. The identity that runs the apply job needs `USE CATALOG`, `USE SCHEMA` and `CREATE SERVICE` on it. Use the same target in the scan form, so code fixes show the real names.
2. **Unity Catalog secrets for API keys.** Each key in the secret map is a Unity Catalog secret, for example `"llm/openai": "secrets/ai_gateway.migrated.openai_key"`. Create each secret in its schema with the Unity Catalog secrets interface or API (check the current Databricks docs for the exact command). The identity that runs apply must be able to read it; the dry run checks that the secret exists without reading its value.
3. **Allowed secret schemas.** The schema in each secret reference (`ai_gateway.migrated` above) must be listed in the installer's **Allowed secret schemas** widget (`catalog.schema`, comma-separated). If it isn't, apply stops before any change. Blank means UC secret mapping is off. To add a schema, run the installer again with the widget updated.
4. **Dry run first, then execute one wave.** Execute in the app needs a successful dry run of the same selection and options.

**Tell the endpoint owners (phase 4).** A short template:

> Subject: `<endpoint>` is moving to Unity Gateway
>
> `<endpoint>` will be served by `<catalog.schema.service>` in Unity Gateway. Please change your calls to it (the proposed change is in CODE_FIXES.md, section `<asset>`), and make sure your identity has `EXECUTE` on that service plus `USE CATALOG` and `USE SCHEMA` on its catalog and schema. Legacy v2 endpoints stop serving on November 30, 2026; v1 endpoints on March 30, 2027. Rate limits, guardrails and inference tables on the old endpoint don't carry over: tell us if you depend on them. Reply when it's deployed so we can check traffic.

**Verify callers moved (phase 5).** Scan again with `--days 7` (or the app's traffic window) to watch traffic fall. The Callers table and export list the callers with requests in the window, so an empty export means no legacy caller in that window. READY still needs zero legacy requests across the full window, so keep the endpoints in place until the window passes with no requests, then enforce.

**Smoke test (optional).** `apply --execute --smoke` reads each created model service back and checks it exists with the planned number of destinations. It makes no inference calls, so it doesn't prove that a request will succeed: send a test call from an identity with `EXECUTE`. The app doesn't offer the smoke test; it's a command-line option.

**Before turning on Enforce (phase 6).** Rolling back an apply run after callers have moved breaks their traffic: rollback deletes the services they now call. Move callers back first, or accept the outage.

**Enforce, and turning it back off.** *Enforce Unity Gateway* is in the workspace admin settings. Confirm the exact location in current Databricks docs. Turning it off lets legacy pay-per-token calls work again. Enforce only when the status is `READY`.

**Post-retirement cleanup.** After the retirement dates (v2 on November 30, 2026, v1 on March 30, 2027) and when you no longer need the results:

1. Roll back any apply run whose services you no longer want (section 8). Uninstall doesn't remove Unity Gateway services.
2. Uninstall the toolkit (**Action** = `uninstall`). Set **Drop results tables** = `yes` to drop the results tables (`ug_migration_scans`, `_scan_items`, `_applies`, `_apply_items`, `_workspaces`, `_endpoints`), or drop them yourself.
3. Delete the `apply_logs` folder in the install folder by hand. Uninstall keeps it.

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
| `--wave <prefix>` | off | Deep-scan the workspaces in one wave (`0` = wave 0 candidates, `1`, `2`, `v2`). With `--deep-scan N`, the N busiest in that wave |
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
| `0: no legacy traffic` | No v1 requests in the window, and no external/PT endpoints with traffic data | Not ready by itself: run the workspace scan, and enforce only when it's `READY` |
| `0: traffic unknown` | Live legacy endpoints with no usage rows in 365 days (usage tracking may be off) | Scan the workspace to confirm traffic |
| `1: cleanup` | External/PT endpoints but no traffic | Confirm with owners, retire or apply, then enforce |
| `1: small` | Under 10,000 legacy requests in the window | Migrate with the owners |
| `2: high volume` | 10,000+ legacy requests | Plan per workload |
| `no endpoint data` | Nothing for the workspace in the account tables | A workspace scan confirms it |
| `not running` | Workspace isn't running; not counted | None |

The app's Overview shows each wave-0 workspace's readiness next to it: "Ready to enforce (scan passed)" when its latest successful scan (READY or READY_WITH_WARNINGS) finished within the window, otherwise "No recent traffic; scan required", "Traffic unknown; scan required", or "Scan blocked".

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
| `--scan-root <path>` | `/Users`, `/Shared`, `/Repos` | Workspace folders to scan (repeatable). **Replaces** the defaults, so pass every folder you want. A narrowed list makes the scan incomplete, and the readiness report lists the folders it scanned. The app's folder field works the same way |
| `--max-objects` | 20000 | Cap on notebooks and files listed, per scan root |
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
- **READY:** nothing blocks enforcement, and there are no legacy requests in the whole traffic window (30 days by default). A caller that moved recently still shows until the window passes.
- **INCOMPLETE:** no blockers found, but a scan surface failed, was cut off or was skipped, or traffic couldn't be confirmed from the system tables (`traffic`; listed with the reason). Readiness can't be confirmed and nothing is offered for closing.
- **READY_WITH_WARNINGS:** nothing breaks when you enforce, but work remains: code still references legacy endpoints, or external model / PT endpoints still get traffic (`legacy_traffic_kept_after_enforce`: Enforce leaves them queryable, but they retire with v1).
- **BLOCKED:** see the blockers.

| Blocker | Meaning | Action |
|---|---|---|
| `legacy_traffic` | A legacy `databricks-*` pay-per-token endpoint was called in the window; these calls fail under Enforce | Find the caller in `SUMMARY.md` / `callers.csv`; move it to the listed target |
| `pay_per_token_call` | Code references a `databricks-*` endpoint (any pattern except the management API), with or without traffic | Move the code to the `system.ai` service in `CODE_FIXES.md`; Enforce turns these calls off |
| `vector_search` | An index embeds with a legacy endpoint | Re-index on a `system.ai` embedding service once AI Search supports it (expected around mid-November 2026), or switch to self-managed embeddings; don't enforce before |
| `agent_bricks_vector_search` | A Knowledge Assistant (or a Supervisor Agent using one) reads an AI Search index | Switch the source to files/volume, or wait for support |
| `app_resource` | An app or bundle uses a legacy serving-endpoint resource | Replace the resource, grant the app service principal `EXECUTE`, update the code |
| `ai_query_custom` | `ai_query` calls a custom legacy endpoint | Not supported on Unity Gateway yet; keep the legacy endpoint for now |
| `agent` | An agent is served on a model serving endpoint | Redeploy on Databricks Apps |

Warnings (code that breaks if it still runs) include `pt_wrapper_on_legacy_endpoint` (a PT Unity Gateway service routes to a legacy v1 endpoint, which retires on March 30, 2027), `no_traffic_in_window` (no requests in the window and usage tracking off: confirm with owners that no infrequent job calls the endpoint) and `serving_endpoint_route_url` (a route-optimized URL that goes away with its legacy endpoint).

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
| `action` | `use_system_ai` (just change callers), `create_model_service` (apply can create it), `out_of_scope` (custom ML models), `manual` (for example a provider apply doesn't create) |
| `target_service` | Proposed or existing Unity Gateway name |
| `target_status` | `system`, `exists` or `missing` (checked live) |
| `provider_status` | `automated` (apply creates it: OpenAI without Entra, Anthropic), `manual_supported` (Bedrock, Gemini, Foundry, Entra-based OpenAI), `no_ug_provider` (Cohere, AI21, Mistral, PaLM, Databricks model serving) or `unknown_provider` |
| `rate_limits`, `routing`, `inference_table`, `grants` | What will be re-created on the target |
| `needs_human` | Decisions to make: guardrails (with specific service policy advice), retired models, endpoints open to all users, dependencies, zero-traffic endpoints to retire |

---

## 8. Apply, rollback and Terraform

`ug_migration_apply.py` creates the Unity Gateway objects that the plan proposes for **external model and Provisioned Throughput endpoints**. Databricks-hosted `databricks-*` endpoints need nothing new: their `system.ai` services already exist.

### What apply creates

| Object | From | Details |
|---|---|---|
| Model provider service | External model endpoints | One per provider + credential (endpoints sharing a key share one service); explicit model list (`allow_all_targets = false`) |
| Model service | Each external model or PT endpoint | Destinations and traffic split (must add up to 100); with legacy fallback enabled, the served entities at 0% become the ordered fallback (at most 5). If no entity is at 0%, no fallback is created and the item says so; all rate-limit scopes; a new inference table named `<prefix>_ug_payload` when the legacy endpoint had one enabled (`<prefix>_ug` is the table name prefix) |
| Grants | Endpoint permissions | `CAN_QUERY` becomes `EXECUTE`, `CAN_MANAGE` becomes `EXECUTE` + `MANAGE`; `CAN_VIEW` alone grants nothing; workspace-local `admins`/`users` skipped |

It **doesn't** touch legacy endpoints, move callers or enable Enforce.

**Existing objects with the same name.** A model service is reused only if it carries the toolkit's mark and has the planned config. Anything else with that name is `manual` and gets no grants. A provider service is handled the same way; a toolkit-owned provider can get missing models added (`updated`). Other differences are `manual`.

**Guardrails.** An endpoint with legacy guardrails that aren't migrated is blocked until you set the service policies and pass `--ack-guardrails` (the app's guardrails checkbox). With the acknowledgement, the model service item lists the guardrails that were not migrated.

### Step by step

```bash
# 1. The target schema must exist
# 1. The target schema must exist, and the identity needs CREATE SERVICE on it
# 2. Dry run (default): shows what would be created, nothing changes
python ug_migration_apply.py --profile <p> apply --endpoints ep1,ep2 \
  --target-catalog ai_gateway --target-schema migrated \
  --allowed-secret-schemas ai_gateway.migrated \
  --uc-secret-map '{"llm/openai": "secrets/ai_gateway.migrated.openai_key"}'

# 3. Create, one wave at a time
python ug_migration_apply.py --profile <p> apply --endpoints ep1,ep2 \
  --target-catalog ai_gateway --target-schema migrated --allowed-secret-schemas ai_gateway.migrated \
  --uc-secret-map map.json --execute --log wave1_log.jsonl

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
| `--uc-secret-map` | JSON file or string: `"scope/key"` to `"secrets/catalog.schema.name"` (preferred). Needs `--allowed-secret-schemas` |
| `--allowed-secret-schemas` | Comma-separated `catalog.schema` names the secrets may live in. Required with `--uc-secret-map`; a secret outside them stops the run before any change |
| `--allow-secret-read` | Instead, read the workspace secret value at run time, only with `--execute` (a dry run never reads it); never printed or logged. Also needs `--allow-secret-read-enabled` (the CLI equivalent of the installer's setting) |
| `--ack-guardrails` | Accept that legacy guardrails are not carried over (see above) |
| `--smoke` | After `--execute`, read each created model service back (no inference calls) |
| `--no-grants` | Skip grants (the CLI copies grants by default) |
| `--execute` | Actually create (otherwise dry run) |
| `--log` | JSON-lines log of what was created, for rollback (default `apply_log.jsonl`) |

The rollback subcommand takes `--log`, `--execute` (otherwise a dry run) and `--force` (delete objects changed since apply; otherwise they are kept).

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
| `needs_attention` | The model service was created but its grants failed. The service stays in place; fix the grant and re-run |
| `smoke_ok`, `smoke_failed` | `--smoke` read-back result. The item's note says what was checked |
| `updated`, `would_update` | A toolkit-owned provider service got its missing models added |
| `would_delete`, `deleted`, `already_gone` | Rollback: what it would delete, what it deleted, objects already removed |
| `kept` | Rollback left the object: it changed since apply (`--force` deletes it), it lost the toolkit's mark, another run's apply still uses it, or another execute run reuses it. The reason is in the item |
| `would_revoke`, `revoked` | Rollback: grants that would be or were removed |
| `note`, `skipped_lines` | Rollback notices: a create was interrupted; unreadable log lines were skipped |

**Supported providers:** OpenAI, Azure OpenAI (API key) and Anthropic. Others are reported as `manual`.

**Checks before creating:** traffic percentages add up to 100; at most 10 primary and 5 fallback destinations; routes name real served entities; every rate limit translates (hourly limits stay hourly; unknown keys or periods stop that endpoint as `manual`). Toolkit safety caps: 20 rate limits per model service and 5 group-specific ones (these are the toolkit's caps, not Unity Gateway limits). An existing provider service with the same name must match the plan (provider, models, secret reference, base URL) or the endpoint is reported as `manual`. Provider service names are stable, built from the provider and the secret they use (`<provider>_<scope>_<key>`). Secrets: each UC secret is checked with a read that doesn't return its value, before the provider is created.

**Concurrency (command line).** The CLI refuses to start while another run for the same folder is unfinished: it looks for run start and end markers in the other logs in the same folder. A run without an end marker that started less than 12 hours ago blocks; remove a stale log to clear it. Keep the logs for one target in one folder. The app has its own check and refuses a second execute on the same target while one is running.

**Exit code:** 0 when everything succeeded or was skipped. 2 when anything ended as `error`, `manual`, `mismatch`, `needs_attention`, `smoke_failed` or `kept`, or when the run was refused (the CLI prints `Refused: ...`).

**Rollback** deletes only what this run's log shows it created (or was creating when interrupted), and only if the object's comment still carries the toolkit's mark for that run. A model service or provider changed since apply is kept unless `--force`. Provider services are kept while a model service in the schema still uses them, and shared objects are kept while another apply run still uses them. Each log can be rolled back once (a finished rollback is marked in the log). Run the dry run first and read it. Inference tables stay.

**Rollback after callers have moved** breaks their traffic, because the services they call are deleted. See section 4.

**Rollback after uninstall.** Uninstalling the toolkit keeps `<install folder>/apply_logs/<apply_id>.jsonl` but deletes the toolkit files. Download the same zip (or a newer one), unzip it, and run the command-line rollback with the log path. Dry run first:

```bash
python ug_migration_apply.py --profile <p> rollback --log "/Workspace/Users/<you>/unity-gateway-migration-toolkit/apply_logs/<apply_id>.jsonl"
python ug_migration_apply.py --profile <p> rollback --log "/Workspace/Users/<you>/unity-gateway-migration-toolkit/apply_logs/<apply_id>.jsonl" --execute
```

Use the workspace path of the log (copy it from the install folder, or export the file to your machine first). The profile needs the permissions to delete the services.

### Terraform instead of API calls

```bash
python ug_migration_apply.py --profile <p> terraform --endpoints ep1,ep2 \
  --target-catalog ai_gateway --target-schema migrated --out ug_migration.tf
terraform init && terraform plan
```

- **Resources written:** `databricks_ai_gateway_model_provider_service`, `databricks_ai_gateway_model_service` and `databricks_grants` (authoritative per new service). Provider requirement: `databricks/databricks >= 1.124.0`. The file is marked as a draft: validate it before use.
- **Guardrails:** endpoints with unmigrated legacy guardrails are skipped unless `--ack-guardrails`.
- **UC secret references:** `--uc-secret-map` needs `--allowed-secret-schemas`, as for apply.
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

### Charts and exports

The app's **Overview** charts every snapshot: legacy (v1 + v2) vs Unity Gateway requests, workspaces ready to enforce, and workspaces by wave, next to the latest workspaces and busiest legacy endpoints. Use **Export** on each page to download the data:

| Page | Export menu items |
|---|---|
| Overview | **Workspaces**, **All legacy endpoints** (not only the top 100 shown) and **Trend across snapshots** (CSV) |
| Scans (one scan) | **Readiness report**, **Code fixes** and **Summary** (Markdown); **Endpoint plan**, **Callers**, **All references** and **Provider services** (CSV) |
| Apply (one run) | **Results** (CSV): every object the run created, checked, skipped or kept |

Exports read the results tables as you, like the pages. They stop at 200,000 rows; the response carries `X-Truncated: true`, and the export menu states the limit.

A snapshot run writes its endpoint rows first and its workspace rows second, and each run is marked complete once its rows are written. The Overview reads only complete runs, so a run that failed halfway doesn't show as zero traffic.

---

## 10. Running in Databricks

### The app (recommended)

The installer (or the bundle) deploys **Unity Gateway Migration Toolkit**, a Databricks App that keeps the day-to-day process in one place: snapshots and charts, scans, readiness, code fixes, apply and exports. Account deep scans of other workspaces, Terraform output and scanning local folders stay command-line only.

| Tab | What you do there |
|---|---|
| **Overview** | See every workspace with legacy endpoints or Unity Gateway traffic, its wave, the share already on Unity Gateway and the trend across snapshots. Charts show the traffic and ready-to-enforce trends. **Refresh snapshot** starts the account snapshot job; **Export** downloads the data. |
| **Scans** | Start a workspace scan (traffic window, folders to scan, target catalog and schema). The folders you enter **replace** the defaults (`/Users`, `/Shared`, `/Repos`); leave the field blank for the defaults. It reads the workspace; results go to the results schema. Open a scan to see readiness (with the folders it scanned), endpoints, callers, code fixes (diffs) and all client references, plus copyable close and undo commands. |
| **Apply** | Pick a scan (scans older than 14 days need **apply anyway**), choose external model and PT endpoints, map API keys to UC secrets (or allow reading the existing secret where the installer enabled it), then **Dry run**. Grants are off unless you tick the box. **Execute** needs a successful dry run of the same selection and options, and the word `EXECUTE` typed in. Endpoints with legacy guardrails need the guardrails checkbox. Every run is kept in the history; **Roll back** an execute run by typing `ROLLBACK`. |
| **About** | Dates, the recommended order of work and the identity model. |

How it works:

- **Scans, snapshots and applies run as Lakeflow jobs** **under the identity that installed the app** (the person who ran the installer, or the identity that deployed the bundle). The installer names them `[<app name>] Unity Gateway migration snapshot`, `... workspace scan` and `... apply`. The bundle names them `Unity Gateway migration snapshot`, `... workspace scan` and `... apply` (resources `ug_migration_snapshot`, `ug_migration_scan`, `ug_migration_apply`); dev mode adds `[dev <user>]`. For a shared install, use a service principal so the jobs don't run with a person's rights. The app's service principal has `CAN_MANAGE_RUN` on these three jobs and `CAN USE` on the warehouse, nothing else. The apply job runs one at a time.
- **Job tags.** Each job carries `tool = ug-migration-toolkit`, `Project = unity-gateway-migration-toolkit`, `app` (the app name) and `role` (`snapshot`, `scan` or `apply`). The installer's checks use these tags to find existing installs.
- **Operators and viewers.** Only the users in **Operators** (installer widget, or the bundle variable `operators`; comma-separated emails; default: the person who installed) can start snapshots, scans and apply runs. Everyone else who can open the app sees results only. Because jobs act with the deployer's rights, keep the operators list short. Job messages and links are shown to operators and to the person who started a run; other viewers see the status and times only.
- **Results go to Delta tables** in the results schema (installer: **Results catalog** and **Results schema**; bundle: `<snapshot_catalog>.<snapshot_schema>`): `ug_migration_scans`, `ug_migration_scan_items`, `ug_migration_applies`, `ug_migration_apply_items`, plus the snapshot tables `ug_migration_workspaces` and `ug_migration_endpoints`.
- **Pages read those tables as the signed-in user** (user authorization with the `sql` scope) through the SQL warehouse, so Unity Catalog permissions on the results schema decide who sees what. Each app user needs `CAN USE` on the app, `CAN USE` on the warehouse, and `USE CATALOG`, `USE SCHEMA` and `SELECT` on the results schema.
- **Scans store code excerpts.** Matched code lines from every scanned folder are stored in the results schema (credential-looking values are replaced with `<hidden>`). Keep the schema limited to the migration team.
- Scan and apply runs record **who asked for them** (`requested_by`); snapshot runs show up in the job's run history. Secret values never go to the results tables or logs; apply results are masked. With "read the workspace secret values" (`--allow-secret-read`), apply copies the key value into the Unity Gateway provider service itself; prefer Unity Catalog secret references. Endpoints that use a plaintext API key stop as `manual`: store the key as a Unity Catalog secret first.
- **Rollback** rebuilds the undo list from the stored execute results (or, if the execute run was interrupted, from the log it wrote as it went, in `apply_logs/` next to the toolkit files). Each execute run can be rolled back once. Rollback keeps objects that another execute run created, and provider services that another run's new model services use. Re-running the same selection doesn't take ownership: roll back the run that created the services.

Install it with the installer notebook (section 3) or the bundle (next section), then open the app from **Compute, Apps** (`unity-gateway-migration` by default for the installer, `ug-migration-bundle` for the bundle; with the bundle, start it with `databricks bundle run ug_migration_app -t dev --var ...`). Use one install method per workspace, or set **Allow a second install** on the installer. The jobs' identity needs the permissions in section 2 (system table access, workspace admin or read access to what you scan, `CREATE SERVICE` on the target schema for apply) plus `USE CATALOG`, `USE SCHEMA`, `CREATE TABLE` and `MODIFY` on the results schema.

### Notebooks

| Notebook | Widgets | Writes |
|---|---|---|
| `notebook/run_planner` | `out_dir` (workspace or volume path; default next to the notebook), `days`, `scan_root` | Output files only |
| `notebook/run_account` | `days`, `out_dir`, `snapshot_table` (blank = none), `deep_scan` (N), `deep_wave` (blank = off; `0` = wave 0 candidates), `deep_warehouse_id` (SQL warehouse in the deep-scanned workspaces; required when `deep_scan` or `deep_wave` is set), `requested_by` | Output files; snapshot tables if set |
| `notebook/run_scan` | Set by the app (`run_id`, `results_schema`, `days`, `scan_roots` (replace the defaults), target, `ack_guardrails`) | `ug_migration_scans`, `ug_migration_scan_items` |
| `notebook/run_apply` | Set by the app (`mode`, `endpoints`, target, `uc_secret_map`, `allow_secret_read`, `grants`, `ack_guardrails`, `smoke_test`, `force`, `rollback_of`). Set on the job by the installer: `secret_schemas`, `allow_secret_read_enabled` | Unity Gateway services and grants (execute only); `ug_migration_applies`, `ug_migration_apply_items` |

They run on serverless job compute (the bundle sets no cluster, so the workspace needs serverless jobs), install the SDK themselves and use the notebook's Spark session for system tables (no warehouse needed). Keep `ug_migration_*.py` in the notebook's folder or one level up.

### Bundle

`databricks.yml` deploys:
- The toolkit files and the notebooks.
- **`ug_migration_app`:** the app described above (name `ug-migration-bundle` by default).
- **`ug_migration_snapshot`:** a weekly job (Mondays 06:00 UTC), **deployed paused**, that runs the account view and appends to `<snapshot_catalog>.<snapshot_schema>.ug_migration_*`.
- **`ug_migration_scan`** and **`ug_migration_apply`:** the jobs the app starts (no schedule).

```bash
databricks bundle validate -t dev --var warehouse_id=<id> --var snapshot_catalog=<c> --var snapshot_schema=<s>
databricks bundle deploy   -t dev --var ...
databricks bundle run ug_migration_snapshot -t dev --var ...   # first snapshot now
databricks bundle run ug_migration_app -t dev --var ...        # start the app
# Unpause the job in the UI (or set pause_status: UNPAUSED) for weekly runs
databricks bundle destroy  -t dev --var ...                    # remove the app, jobs and files
```

| Variable | Meaning |
|---|---|
| `warehouse_id` | Warehouse the app reads results through |
| `snapshot_catalog`, `snapshot_schema` | Where snapshot tables go (must exist) |
| `days` | Traffic window (default 30) |
| `operators` | Emails of the users who can start jobs from the app (default: you) |
| `app_name` | App name (default `ug-migration-bundle`; must differ from an installer app in the same workspace) |
| `secret_schemas` | Allowed `catalog.schema` values for Unity Catalog secrets (default empty = UC secret mapping off) |
| `allow_secret_read_enabled` | `"true"` or `"false"`: allow reading workspace secret values (fixed on the apply job) |

**Shared install (`prod` target):** deploy while authenticated as a service principal (for example `DATABRICKS_CLIENT_ID` / `DATABRICKS_CLIENT_SECRET`) that has the permissions above. The jobs then run as that service principal, and the files live in its home folder, which other users can't edit. Pass `--var operators=a@x.com,b@x.com`.

**Update:** unzip the new version and run `databricks bundle plan` first, then `databricks bundle deploy` with the same variables; history in the results tables is kept. The app name changed in 0.9.0 (from `unity-gateway-migration` to `ug-migration-bundle`), so a plan over an earlier bundle deployment creates a new app: delete the old app by hand afterwards. A bundle redeploy sets the weekly snapshot back to paused; unpause it again if you use it. (An installer rerun keeps the snapshot's paused or unpaused state.) **Uninstall:** `bundle destroy` doesn't delete data. Drop the results tables (`ug_migration_scans`, `_scan_items`, `_applies`, `_apply_items`, `_workspaces`, `_endpoints`) and the `apply_logs` folder when you no longer need them. Unity Gateway services created by apply stay until you roll them back or delete them.

Use catalog and schema names made of letters, digits and underscores for the results schema.

---

## 11. Safety and data handling

| Topic | Behavior |
|---|---|
| **Read-only by default** | The planner, account view and code scan only make GET calls and run read-only SQL |
| **Writes** | Only `apply --execute`, `rollback --execute`, snapshots and the app's result tables write anything |
| **Legacy endpoints** | Never modified or deleted by the toolkit. The rate-limit-0 commands are printed for you to run |
| **Code** | Never edited. Fixes are proposals |
| **Secrets** | Reports show secret names (`scope/key`), never values. Literal keys found on legacy endpoints are replaced with `<redacted plaintext XXXXXXXX>`, where `XXXXXXXX` is the first 8 hex digits of the value's SHA-256 (so two identical keys can be matched without showing either). Apply reads a value only with `--allow-secret-read --execute` (or the app's option, when the installer enabled it), and never prints or logs it. Environment variables that reference secrets are skipped by the scan. Scan results and apply logs mask values under keys named like `secret`, `token`, `password` or `api_key` |
| **What's in the reports** | Endpoint names, user and service principal identifiers, workspace names and code lines that mention legacy endpoints. Treat outputs as internal to the organization |
| **Scope** | Only scan workspaces you're authorized to review |
| **Tag** | The toolkit's jobs (snapshot, scan and apply, from the installer or the bundle) carry the tags `tool = ug-migration-toolkit`, `Project = unity-gateway-migration-toolkit`, `app` and `role`, so the usage of this toolkit can be identified. They are only labels: they don't send data anywhere and don't change how the jobs run. Nothing else the toolkit creates is tagged (the app and the Unity Gateway services don't accept tags). To list the jobs: `SELECT job_id, name FROM system.lakeflow.jobs WHERE tags['Project'] = 'unity-gateway-migration-toolkit'` |

---

## 12. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "0 endpoints with traffic" but you know there's traffic | No access to `system.serving.*`, or the window is too short | Grant `SELECT`, run as an account admin, or raise `--days`. The tool reads the workspace ID from the API response header; override with `--workspace-id` if needed |
| INCOMPLETE with `traffic` under "Incomplete scan" | No warehouse locally, no access to the system tables, or no rows for this workspace | Pass `--warehouse-id` (or run the notebook), grant `SELECT` on the system tables, and check the workspace ID in `readiness.json` |
| Scan stops at `--max-objects` | Large workspace | Raise `--max-objects`, or scan specific `--scan-root` folders |
| Apply: `Target schema ... doesn't exist` | Schema missing | Create it first; apply never creates schemas |
| Apply: `manual: secret ...` | Secret not mapped | Add it to `--uc-secret-map`, or pass `--allow-secret-read` |
| Apply: inference table already exists | The table `<prefix>_ug_payload` (the new service's inference table) is already there | Drop or rename that table, then re-run apply |
| Apply: `Refused` / secret schema not allowed | A UC secret in the map is in a schema that isn't in **Allowed secret schemas** (CLI: `--allowed-secret-schemas`), or the list is blank | Add the schema (rerun the installer with the widget updated), or fix the secret reference. Nothing was changed |
| Apply: `needs_attention` | The model service was created, but its grants failed | Fix the grant (the service stays in place), then re-run; existing objects are skipped |
| Apply: `kept` on rollback | The object changed since apply, lost the toolkit's mark, or another run still uses it | Read the reason in the item. Use `--force` only if you know the change is safe to undo |
| App: "Run a dry run with this selection first" | Execute needs a successful dry run of the same scan, selection and options | Run the dry run again; any change to the selection needs a new dry run |
| App: "This scan is N days old" (409) | Scans older than 14 days need confirmation | Scan again, or tick **apply anyway** after you've checked the callers |
| App: guardrails error (400) | An endpoint has legacy guardrails that aren't migrated | Set the service policies, then tick the guardrails checkbox |
| Readiness still isn't `READY` after callers moved | READY needs zero legacy requests in the whole window, so recent callers still show | Wait for the window to pass with no requests, or scan with `--days 7` to see progress |
| Apply: `manual: PT endpoint serves ..., which no longer exists` | The PT endpoint's model was deleted | Retire or redeploy the PT endpoint |
| Readiness is `INCOMPLETE` | A scan surface failed, was cut off or was skipped | See "Incomplete scan" in `READINESS.md`; fix access or raise `--max-objects`, then run again |
| Apply exits with code 2 | Something ended as `error`, `manual`, `mismatch`, `needs_attention`, `smoke_failed` or `kept`, or the run was refused | Read the JSON lines with those actions; fix and re-run (existing objects are skipped) |
| Apply: `already exists with a different configuration` | A provider service with that name exists but differs | Rename the target schema, or reconcile the provider by hand |
| Account summary shows "Query errors" | A system table query failed | No snapshot is written for that run; fix access and run again |
| Deep scan: `can't authenticate` | No credentials for that workspace | Use a service principal assigned to it, or `databricks auth login --host <url>` |
| Code fix points to `ai_gateway.migrated.*` but you created services elsewhere | Planner run with default target | Re-run the planner with the same `--target-catalog`/`--target-schema` as apply |
| Overview shows "No snapshot yet" | No snapshot in the results schema | Click **Refresh snapshot** (operators), or run the snapshot job once |
| Numbers differ from other Databricks dashboards | Different sources and windows | Base decisions on the toolkit's numbers (from your own system tables) and expect differences from other dashboards |
| Installer: `Results catalog ... doesn't exist` | Catalog missing or not visible to you | Pick an existing catalog you can create a schema in |
| App shows "No user token" (401) | User authorization isn't enabled for the app | Re-run the installer (it sets the `sql` scope), or add `user_api_scopes: [sql]` to the bundle app |
| App: "Only the app's operators can start ..." (403) | You aren't in Operators | Re-run the installer with your email added to **Operators** (bundle: `--var operators=...`) |
| App: "A scan is already running" / "Another apply run is in progress" (409) | One run of each job at a time | Wait for it to finish (see the job run link) |
| App pages are empty after a scan | No `SELECT` on the results schema, or a different results schema | Grant `USE CATALOG`, `USE SCHEMA` and `SELECT`; check **Results schema** |
| Installer stops and names another toolkit install | A toolkit install (for example a 0.7.0 `ug-migration` app, or a bundle deploy) already runs in the workspace | Set **App name** to that name to update it, or uninstall it first, or set **Allow a second install** (it still needs its own results schema and folder) |
| Installer: "downgrade" | The app or marker shows a newer version than the one you're installing | Install the newer version, or set **Allow downgrade** = `yes` |
| Installer: "Adopt existing app" | An app with the name exists but its description isn't a toolkit app | Choose another App name, or set **Adopt existing app** = `yes` if the app can be replaced |
| Installer: an apply run is active (uninstall refused) | An apply job is running | Wait for it to finish, or cancel it in Jobs, then uninstall |

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
- **Command line only:** the smoke test (`--smoke`), `rollback --force` and Terraform output aren't in the app.
- **Legacy settings:** rate limits, guardrails and inference tables on `databricks-*` endpoints are reported, not copied. Guardrails and budget or usage policies on external and PT endpoints need a person.

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
`READINESS.md` says `READY`. That needs zero legacy requests in the whole window (30 days by default), so the busiest-endpoints table is empty for that workspace and its wave is `0: no legacy traffic` (which alone isn't ready). Then a workspace admin enables *Enforce Unity Gateway*.

**Can I scan only the folders I care about?**
Yes, but the folders you enter replace the defaults (`/Users`, `/Shared`, `/Repos`). A narrowed scan is incomplete, and the readiness report says which folders were scanned.

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
| `ug_migration_store.py` | Delta tables for the app's scan and apply runs |
| `notebook/run_planner.py`, `notebook/run_account.py` | Notebook entry points (one workspace, account view and snapshots) |
| `notebook/run_scan.py`, `notebook/run_apply.py` | Job notebooks the app starts (scan; dry run, execute and rollback) |
| `app/` | The Unity Gateway Migration Toolkit app (FastAPI backend, React frontend build in `app/frontend/static`) |
| `INSTALL_unity_gateway_migration_toolkit_<version>.py` | Installer notebook: installs, updates or removes everything inside a workspace |
| `databricks.yml` | Bundle: app, snapshot, scan and apply jobs |
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
  [--uc-secret-map MAP --allowed-secret-schemas C.S | --allow-secret-read --allow-secret-read-enabled] \
  [--ack-guardrails] [--no-grants] [--smoke] [--execute] [--log FILE]
python ug_migration_apply.py --profile P terraform (--endpoints a,b | --all) --target-catalog C --target-schema S \
  [--uc-secret-map MAP --allowed-secret-schemas C.S] [--ack-guardrails] [--no-grants] [--out FILE.tf]
python ug_migration_apply.py --profile P rollback --log FILE [--execute] [--force]
```
