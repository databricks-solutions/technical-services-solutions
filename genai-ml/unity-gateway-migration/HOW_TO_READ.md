# How to read the migration results

This guide is for the team that runs the Unity Gateway migration toolkit in its own Databricks account. The toolkit is a prototype from Databricks Shared Technical Services, provided as is. Scans only read your workspace. Results (including matched code lines) are stored in the results schema; apply and rollback create or delete Unity Gateway services; snapshots append rows to tables, and the dashboard step creates a dashboard. Nothing else is changed.

**Why this matters:** Legacy v2 workspace endpoints stop serving first (on **November 30, 2026**) and v1 endpoints stop serving on **March 30, 2027**. These dates come from Databricks migration communications as of October 30, 2026; confirm them with your account team. Nothing moves automatically, and settings on legacy endpoints (rate limits, guardrails, inference tables, permissions) don't carry over to Unity Gateway.

**Using the app?** The Unity Gateway Migration app shows the same results: the Scans tab has Readiness (READINESS.md), Endpoints (migration_plan.csv), Callers (callers.csv) and Code fixes (CODE_FIXES.md). Everything below applies to both.

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

- **READY**: no legacy traffic and nothing depends on legacy endpoints. A workspace admin can turn on *Settings > Advanced > Enforce Unity Gateway*.
- **INCOMPLETE**: nothing is blocking, but part of the scan failed or was skipped, or traffic couldn't be confirmed from the system tables (listed under "Incomplete scan"). Fix access and run again before deciding.
- **READY_WITH_WARNINGS**: nothing breaks when you enforce, but there is still work: code that references legacy endpoints, or traffic on external model / PT endpoints (`legacy_traffic_kept_after_enforce`), which keep working after Enforce but retire with v1. That code will break if it runs after enforcement: fix it first, or confirm it's no longer used.
- **BLOCKED**: something will break. The blockers section lists each item.

| Blocker | What it means | What to do |
|---|---|---|
| `legacy_traffic` | Something called a legacy `databricks-*` endpoint during the window (these stop working under Enforce) | Find the caller in "Who calls legacy endpoints" (SUMMARY.md) and move it to the listed model service |
| `vector_search` | An AI Search (formerly Vector Search) index embeds with a legacy endpoint | Re-create the index on a `system.ai` embedding service once AI Search supports it (expected around mid-November 2026), or switch it to self-managed embeddings. Don't enforce this workspace until then |
| `agent_bricks_vector_search` | A Knowledge Assistant (or a Supervisor Agent using one) reads from an AI Search index | Switch the source to files or a volume, or wait for AI Search support |
| `app_resource` | A Databricks App (or a bundle) uses a legacy serving endpoint resource | Replace the resource, grant the app's service principal `EXECUTE` on the model service, update the app code |
| `ai_query_custom` | `ai_query` calls a custom legacy endpoint | `ai_query` can't call custom model services yet; keep the legacy endpoint for now |
| `agent` | An agent is deployed on a serving endpoint | Redeploy it on Databricks Apps |

**"Can be closed now"** lists external model endpoints with no traffic, no dependents and no code references, and only when traffic was confirmed and the scan was complete. Provisioned Throughput endpoints are never listed, because their Unity Gateway services route through them. The close command sets the endpoint's rate limit to 0, which stops calls without deleting anything. It keeps the endpoint's other rate limits and settings, and the undo command next to it restores the current configuration. The traffic window may miss rare callers: confirm with the owner first.

---

## SUMMARY.md

- **Endpoints by kind:**
  - `system_ppt`: Databricks-hosted `databricks-*` models. Their replacements (`system.ai.*`) already exist, so you only change callers.
  - `external_model`: OpenAI, Anthropic and other providers.
  - `provisioned_throughput`: dedicated capacity.
  - `custom_model`: your own ML models. These aren't affected.
- **Who calls legacy endpoints:** each user or service principal that called a legacy endpoint, with the code the toolkit found in their folders. "Not found" means no matching code was found in that caller's folders: check jobs, external apps, Git repos and laptops.
- **Provider services to create:** for external models, one shared connection per provider and key.
- **Needs a human:** decisions the toolkit won't make for you, such as guardrails, retired models and endpoints open to all users.

---

## When you enforce

Turning on *Enforce Unity Gateway* makes calls to legacy `databricks-*` pay-per-token endpoints fail with `PERMISSION_DENIED`, and new external model or PT endpoints can only be created through Unity Gateway. Existing external model and PT endpoints stay queryable until they retire, so move their callers too. Callers need `EXECUTE` on the model service plus `USE CATALOG` and `USE SCHEMA` on its catalog and schema (all account users have `EXECUTE` on `system.ai` services by default).

---

## CODE_FIXES.md

Each change shows the old line (`-`) and the proposed line (`+`):

- **auto**: a mechanical rewrite, for example `ai_query('databricks-gpt-5-5', ...)` to `ai_query('system.ai.gpt-5-5', ...)`. Note that `ai_query` on Unity Gateway only gets usage tracking: rate limits, fallbacks, inference tables and service policies don't apply to it.
- **review**: probably right, but check it. This covers URLs, model names, LangChain clients, and values in YAML or Terraform.

The toolkit doesn't change your code. Apply fixes in the source (and its Git repo), then run the toolkit again. Also move tokens from `all-apis` to the `ai-gateway` scope when you change a URL.

---

## ACCOUNT_SUMMARY.md and the dashboard

- **Waves:**
  - `v2 first`: has v2 traffic, which stops serving on November 30, 2026.
  - `0: enforce candidate`: no legacy traffic and no external model or PT endpoints. Run the per-workspace readiness check, then enforce.
  - `1: cleanup`: external model or PT endpoints with no traffic. Retire them or migrate them.
  - `1: small`: low traffic.
  - `2: high volume`: plan these with the owners.
- **Share on UG:** Unity Gateway requests divided by all model requests (legacy v1 + legacy v2 + Unity Gateway). Requests are distinct request IDs.
- **Name collisions:** custom endpoint names used in several workspaces. Give each workspace its own target schema.
- **Dashboard:** fills in from snapshots (Refresh account snapshot in the app, or the weekly snapshot job once you unpause it). The trend lines should show legacy traffic going down and ready workspaces going up.

---

## Things to know

- Usage data can lag by up to a few hours.
- The scan only sees what's in the workspace: notebooks, files, jobs, SQL queries and functions, views, dashboards, apps, Genie Agents (formerly Genie spaces), pipelines, serving endpoint settings, AI Search and Agent Bricks. Scan Git repos with `--local-path`.
- AI Search didn't accept `system.ai` embedding endpoints when this version was tested (October 30, 2026); as of that date Databricks indicated support around mid-November 2026 (not confirmed). Until then, indexes on legacy `databricks-*` embeddings block enforcement. If you must enforce sooner, one option is to switch those indexes to self-managed embeddings computed with `ai_query('system.ai.<embedding model>', ...)` and query them with `query_vector` (not tested by the toolkit; validate it first).
- Questions: contact your Databricks account team.
