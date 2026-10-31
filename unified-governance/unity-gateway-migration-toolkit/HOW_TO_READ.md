# How to read the migration results

This guide is for the team that runs the Unity Gateway Migration Toolkit in its own Databricks account. The toolkit is a prototype from Databricks Shared Technical Services, provided as is. Scans only read your workspace. Results (including matched code lines) are stored in the results schema; apply and rollback create or delete Unity Gateway services; snapshots append rows to tables. Nothing else is changed.

**Why this matters:** Legacy v2 workspace endpoints stop serving first (on **November 30, 2026**) and v1 endpoints stop serving on **March 30, 2027**. These dates come from Databricks migration communications as of October 30, 2026; confirm them with your account team. Nothing moves automatically, and settings on legacy endpoints (rate limits, guardrails, inference tables, permissions) don't all carry over. Apply re-creates rate limits, routing, inference tables and grants for external model and PT endpoints; guardrails and budget or usage policies need a person.

**Using the app?** The Unity Gateway Migration Toolkit app shows the same results. Each scan's **Export** menu on the Scans tab has these files: **Readiness report** (READINESS.md), **Code fixes** (CODE_FIXES.md), **Summary** (SUMMARY.md), **Endpoint plan** (migration_plan.csv), **Callers** (callers.csv), **All references** (client_references.csv) and **Provider services** (provider_services.csv). The Overview's **Export** menu has **Workspaces**, **All legacy endpoints** and **Trend across snapshots** (CSV). Everything below applies to both.

---

## Start with these three files

| File | Question it answers |
|---|---|
| `READINESS.md` | Can we turn on *Enforce Unity Gateway* in this workspace? If not, what's in the way? |
| `SUMMARY.md` | What legacy endpoints do we have, who calls them, and where is that code? |
| `CODE_FIXES.md` | Exactly which lines to change, old and new |

For the whole account, start with `ACCOUNT_SUMMARY.md` (from the account notebook).

---

## READINESS.md

The status is one of:

- **READY**: no legacy requests in the whole traffic window (default 30 days), and nothing depends on legacy endpoints. A workspace admin turns on *Enforce Unity Gateway* in the workspace admin settings (confirm the exact location in current Databricks docs).
- **INCOMPLETE**: nothing is blocking, but part of the scan failed or was skipped, or traffic couldn't be confirmed from the system tables (listed under "Incomplete scan"). Fix access and run again before deciding.
- **READY_WITH_WARNINGS**: nothing breaks when you enforce, but there is still work: code that references legacy endpoints, or traffic on external model / PT endpoints (`legacy_traffic_kept_after_enforce`), which keep working after Enforce but retire with v1. That code will break if it runs after enforcement: fix it first, or confirm it's no longer used.
- **BLOCKED**: something will break. The blockers section lists each item.

The report also lists the workspace folders that were scanned. A narrowed folder list is an incomplete scan.

| Blocker | What it means | What to do |
|---|---|---|
| `legacy_traffic` | Something called a legacy `databricks-*` endpoint during the window (these stop working under Enforce) | Find the caller in "Who calls legacy endpoints" (SUMMARY.md) and move it to the listed model service |
| `pay_per_token_call` | Code references a `databricks-*` endpoint, with or without traffic in the window | Move the code to the `system.ai` service in `CODE_FIXES.md`; Enforce turns these calls off |
| `vector_search` | An AI Search (formerly Vector Search) index embeds with a legacy endpoint | Re-create the index on a `system.ai` embedding service once AI Search supports it (expected around mid-November 2026), or switch it to self-managed embeddings. Don't enforce this workspace until then |
| `agent_bricks_vector_search` | A Knowledge Assistant (or a Supervisor Agent using one) reads from an AI Search index | Switch the source to files or a volume, or wait for AI Search support |
| `app_resource` | A Databricks App (or a bundle) uses a legacy serving endpoint resource | Replace the resource, grant the app's service principal `EXECUTE` on the model service, update the app code |
| `ai_query_custom` | `ai_query` calls a custom legacy endpoint | `ai_query` can't call custom model services yet; keep the legacy endpoint for now |
| `agent` | An agent is deployed on a serving endpoint | Redeploy it on Databricks Apps |

Warnings (code that will break if it still runs) include `pt_wrapper_on_legacy_endpoint` (a PT Unity Gateway service routes to a legacy v1 endpoint, which retires on March 30, 2027), `no_traffic_in_window` (endpoints with no requests in the window and usage tracking off: confirm with the owners that no infrequent job calls them) and `serving_endpoint_route_url` (a route-optimized URL that goes away with the endpoint).

**"Can be closed now"** lists external model endpoints with no traffic, no dependents and no code references, and only when traffic was confirmed and the scan was complete. Provisioned Throughput endpoints are never listed, because their Unity Gateway services route through them. The close command sets the endpoint's rate limit to 0, which stops calls without deleting anything. It keeps the endpoint's other rate limits and settings, and the undo command next to it restores the current configuration. The traffic window may miss rare callers: confirm with the owner first.

---

## SUMMARY.md

- **Endpoints by kind:**
  - `system_ppt`: Databricks-hosted `databricks-*` models. Their replacements (`system.ai.*`) already exist, so you only change callers.
  - `external_model`: OpenAI, Anthropic and other providers.
  - `provisioned_throughput`: dedicated capacity.
  - `custom_model`: your own ML models. These aren't affected.
- **Who calls legacy endpoints:** each user or service principal that called a legacy endpoint, with the code the toolkit found in their folders. "Not found" means no matching code was found in that caller's folders: check jobs, external apps, Git repos and laptops.
- **Provider services to create:** for external models, one shared connection per provider and key, with `provider_status` (`automated` ones are created by apply; the others need a person).
- **Needs a human:** decisions the toolkit won't make for you, such as guardrails, retired models, endpoints open to all users, and budget or usage policies that don't carry over.

---

## When you enforce

Turning on *Enforce Unity Gateway* (workspace admin settings; confirm the exact location in current Databricks docs) makes calls to legacy `databricks-*` pay-per-token endpoints fail with `PERMISSION_DENIED`, and new external model or PT endpoints can only be created through Unity Gateway. Existing external model and PT endpoints stay queryable until they retire, so move their callers too. Callers need `EXECUTE` on the model service plus `USE CATALOG` and `USE SCHEMA` on its catalog and schema (all account users have `EXECUTE` on `system.ai` services by default).

Turning Enforce back off in the same place lets legacy pay-per-token calls work again. Enforce only once the status is `READY`.

---

## CODE_FIXES.md

Each change shows the old line (`-`) and the proposed line (`+`):

- **auto**: a mechanical rewrite, for example `ai_query('databricks-gpt-5-5', ...)` to `ai_query('system.ai.gpt-5-5', ...)`. Note that `ai_query` on Unity Gateway only gets usage tracking: rate limits, fallbacks, inference tables and service policies don't apply to it.
- **review**: probably right, but check it. This covers URLs, model names, LangChain clients, and values in YAML or Terraform.

The toolkit doesn't change your code. Apply fixes in the source (and its Git repo), then run the toolkit again. Also move tokens from `all-apis` to the `ai-gateway` scope when you change a URL.

---

## Watching progress

- Scan again with a shorter window to watch callers move: `--days 7` on the command line, or the **Traffic window** field in the app's scan form. Traffic in the last 7 days should fall to zero as callers move.
- READY still needs zero legacy requests in the whole window (30 days by default). A caller that moved today still shows in the Callers table and keeps the status below READY until the window passes with no requests. The Callers export is empty for a window when no legacy caller made a request in it.
- Enforce only after the status is `READY`.

---

## ACCOUNT_SUMMARY.md and the Overview

- **Waves:**
  - `v2 first`: has v2 traffic, which stops serving on November 30, 2026.
  - `0: no legacy traffic`: no v1 requests in the window. This is not ready: run the workspace scan, and enforce only when it's `READY`. The app's Overview shows each workspace's readiness next to it ("Ready to enforce (scan passed)", "No recent traffic; scan required", and so on).
  - `0: traffic unknown`: live legacy endpoints with no usage rows in the last 365 days. Usage tracking may be off, so traffic can't be confirmed until a workspace scan.
  - `1: cleanup`: external model or PT endpoints with no traffic. Retire them or migrate them.
  - `1: small`: under 10,000 legacy requests in the window.
  - `2: high volume`: 10,000 or more; plan these with the owners.
  - `no endpoint data`, `not running`: not counted as wave 0. A workspace scan confirms the first.
- **Share on UG:** Unity Gateway requests divided by all model requests (legacy v1 + legacy v2 + Unity Gateway). Requests are distinct request IDs.
- **Config signals:** "Check: AI Search, Agent Bricks, Apps, AI Functions" under a workspace name come from billing activity. They are signals only; the workspace scan is the check.
- **Name collisions:** custom endpoint names used in several workspaces. Give each workspace its own target schema.
- **Overview charts:** fill in from snapshots (Refresh snapshot in the app, or the weekly snapshot job once you unpause it). Legacy traffic should go down and workspaces ready to enforce should go up. Each chart has a "View data" table, and the trend export is labeled as rolling windows: consecutive points overlap.

---

## Things to know

- Usage data can lag by up to a few hours.
- The scan only sees what's in the workspace: notebooks, files, jobs, SQL queries and functions, views, dashboards, apps, Genie Agents (formerly Genie spaces), pipelines, serving endpoint settings, AI Search and Agent Bricks. Scan Git repos with `--local-path`.
- AI Search didn't accept `system.ai` embedding endpoints when this version was tested (October 30, 2026); as of that date Databricks indicated support around mid-November 2026 (not confirmed). Until then, indexes on legacy `databricks-*` embeddings block enforcement. If you must enforce sooner, one option is to switch those indexes to self-managed embeddings computed with `ai_query('system.ai.<embedding model>', ...)` and query them with `query_vector` (not tested by the toolkit; validate it first).
- Questions: contact your Databricks account team.
