# Genie Helpers

A collection of standalone Databricks notebooks for operating, monitoring, and governing Genie spaces. Each notebook is self-contained and driven by widgets — no shared setup required.

## Contents

| Notebook | Purpose |
| --- | --- |
| [Manage Genie Space Permissions](#manage-genie-space-permissionsipynb) | Administer Genie space access via the Permissions API |
| [Genie Conversation History Ingestion](#genie-conversation-history-ingestionipynb) | Ingest conversations & messages to a Delta table (incremental) |
| [Genie Feedback Extraction](#genie-feedback-extractionipynb) | Extract POSITIVE/NEGATIVE feedback (incremental) |
| [Genie Reasoning Process Logger](#genie-reasoning-process-loggeripynb) | Log the full step-by-step Genie reasoning process |
| [Genie Space Conversation Duration Logger](#genie-space-conversation-duration-loggeripynb) | Capture per-message latency with a 3-stage breakdown |
| [UC Governance Explorer - Tags Comments Lineage](#uc-governance-explorer---tags-comments-lineageipynb) | Explore UC tags, comments & lineage (Genie prep) |
| [LLM Column Comment Generator](#llm-column-comment-generatoripynb) | Auto-generate missing column comments with an LLM |

## Notebooks

### Manage Genie Space Permissions.ipynb

Manages permissions for a Databricks Genie space via the **REST API**.
Pre-requisite: the developer executing it must have access to the `system.query.history` table.

**Workflow:**
1. **Review** current permissions on the Genie space (GET)
2. **Conditionally add** a user group with `CAN_MANAGE` rights if not already granted (PATCH)

> **Note:** Genie spaces use the `genie` object type in the Permissions API endpoint (`/api/2.0/permissions/genie/{id}`).

### Genie Conversation History Ingestion.ipynb

Fetches all conversations and messages from a Genie space via the Databricks REST API and writes them to a Unity Catalog Delta table. Supports **incremental updates** — each run only fetches conversations updated since the last run (watermark on `conversation_updated_at`).

**How it works:**
1. Reads `space_id`, `catalog`, `schema`, and `table` widgets
2. Determines the incremental watermark from the target table (or does a full load if empty)
3. Lists conversations and messages via the Genie REST API (paginated)
4. **MERGE**s results into the target Delta table keyed on `(space_id, conversation_id, message_id)`
5. Includes analytics SQL cells: **top 20 popular questions** and **AI-powered topic clustering** with `ai_gen()` to group differently-phrased questions by intent

### Genie Feedback Extraction.ipynb

**Incrementally** extracts user feedback (POSITIVE / NEGATIVE / no rating) from a Genie space using the Databricks **Genie Conversation REST API**.

**How it works:**
1. Reads the **Lookback Days** widget to determine the time window (default: 7 days)
2. Lists conversations and filters to only those created within the lookback window
3. Fetches messages within each filtered conversation, skipping any outside the window
4. Extracts `feedback.rating`, user question, Genie response, and generated SQL
5. **MERGE**s results into the target Delta table — inserts new rows, updates changed ratings (idempotent)

### Genie Reasoning Process Logger.ipynb

Captures the full reasoning process of Genie space conversations — each step logged as a separate row with timestamps and content, so you can inspect how Genie arrived at an answer.

| Step type | What it captures | Source |
| --- | --- | --- |
| **reasoning** | AI description, understanding, data sourcing, and planned steps | `attachments[].query.thoughts[]` |
| **function_call** | Generated SQL query | `attachments[].query.query` |
| **function_call_output** | Query result metadata (row count, statement ID) | `attachments[].query.query_result_metadata` |
| **message** | Final text answer / report | `attachments[].text.content` |

**How it works:**
1. Reads `space_id`, `catalog_name`, `schema_name`, and `table_name` (default: `genie_reasoning_steps`) widgets
2. Lists conversations and messages via the Genie REST API (parallelized)
3. Extracts each reasoning step into its own row, preserving step ordering and per-phase timing
4. **MERGE**s results into a Delta table keyed on `(space_id, conversation_id, message_id, step_type, step_index)`
5. Includes summary SQL cells: overall stats per space and a breakdown by step type/subtype

### Genie Space Conversation Duration Logger.ipynb

**Incrementally** captures Genie space conversations and logs per-message latency with a three-stage breakdown, so timing data is preserved beyond `system.query.history` retention (1 year).

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

### UC Governance Explorer - Tags Comments Lineage.ipynb

Demonstrates how to query Unity Catalog **system tables** (`system.information_schema`, `system.access`) to:
- List column tags and comments across any catalog/schema — to be prepared for Genie usage
- Filter for columns tagged as **PII** or **critical** (configurable tag names)
- Trace upstream/downstream lineage for Gold tables
- Build a **"What breaks if we change X?"** impact analysis report

### LLM Column Comment Generator.ipynb

Scans all tables in a Unity Catalog schema, identifies columns **without** comments, generates descriptive comments using an LLM via `ai_query`, and applies them via `ALTER TABLE` or `ALTER VIEW`.

**Existing comments are never overwritten.** Streaming tables and materialized views are detected and skipped — their comments should be managed in the pipeline definition.
