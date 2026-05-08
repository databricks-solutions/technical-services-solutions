# This folder is for helper notebooks for different purposes


# Manage Genie Space Permissions.ipynb 

This notebook manages permissions for a Databricks Genie space via the **REST API**.

**Workflow:**
1. **Review** current permissions on the Genie space (GET)
2. **Conditionally add** a user group with `CAN_MANAGE` rights if not already granted (PATCH)

> **Note:** Genie spaces use the `genie` object type in the Permissions API endpoint (`/api/2.0/permissions/genie/{id}`).



# Genie Feedback Extraction.ipynb

This notebook **incrementally** extracts user feedback (POSITIVE / NEGATIVE / no rating) from the Genie space using the Databricks **Genie Conversation REST API**.

**How it works:**
1. Reads the **Lookback Days** widget to determine the time window (default: 7 days)
2. Lists conversations and filters to only those created within the lookback window
3. Fetches messages within each filtered conversation, skipping any outside the window
4. Extracts `feedback.rating`, user question, Genie response, and generated SQL
5. **MERGE**s results into the target Delta table — inserts new rows, updates changed ratings (idempotent)

# UC Governance Explorer — Tags, Comments & Lineage
This notebook demonstrates how to query Unity Catalog **system tables** (`system.information_schema`, `system.access`) to:
- List column tags and comments across any catalog/schema - to be prepared for Genie usage
- Filter for columns tagged as **PII** or **critical** (configurable tag names)
- Trace upstream/downstream lineage for Gold tables
- Build a **"What breaks if we change X?"** impact analysis report

# Auto-Generate Column Comments with LLM

This notebook scans all tables in a Unity Catalog schema, identifies columns **without** comments, generates descriptive comments using an LLM via `ai_query`, and applies them via `ALTER TABLE` or `ALTER VIEW`.

**Existing comments are never overwritten.** Streaming tables and materialized views are detected and skipped — their comments should be managed in the pipeline definition.

# Genie Space Conversation Duration Logger.ipynb

This notebook **incrementally** captures Genie space conversations and logs per-message latency with a three-stage breakdown so timing data is preserved beyond `system.query.history` retention (1 year).

**Stage breakdown** (`total_duration = pre_execution + query_execution + post_execution`):
- **pre_execution** — AI generation, intent classification, SQL planning (before SQL hits the warehouse)
- **query_execution** — actual SQL execution time on the warehouse (from `system.query.history`)
- **post_execution** — result processing + LLM summarization after SQL completes

**How it works:**
1. Fetches all conversations & messages from the Genie REST API (parallelized, 8 workers)
2. Joins `system.query.history` for SQL timing breakdown
3. Joins `system.access.audit` to determine `conversation_mode` (`chat` / `agent`); NULLs default to `'chat'` since Deep Research always routes through the logged `createConversation` action
4. **MERGE**s results into a Delta table keyed on `(space_id, conversation_id, message_id)` — idempotent upsert

> **Scheduling recommendation:** run regularly (e.g. daily) so timing data is captured before `system.query.history` retention expires.