# Phase (c3): Sources first, AI discovery, and memory

Goal: a customer who has tables but no clear metrics can still start. The sub-project begins with the data, the app
fixes what blocks a good model, and the AI proposes what can be built before the user writes the brief.

## New order of a sub-project

1. **Sources.** A new sub-project opens on a table selector: catalogs and schemas the user can read, with check
   boxes for tables, like Catalog Explorer. The selection shows a relationship check before it is added: tables
   that join to the others (declared keys or key names) and tables that do not. For tables that do not join, the
   app suggests a separate sub-project. "Bring related tables" stays.
2. **Readiness and fixes.** The assessment runs without a brief. The score uses documentation, keys, types and
   naming; brief coverage is added once the brief exists. Fixes run after approval, as today.
3. **Intent & Context with discovery.** The AI reads the table metadata (names, types, comments, keys, never
   rows) and opens with a short list of metric views it can build from these tables, each with its measures and
   dimensions, and the question it answers. The user picks one, edits it, or describes their own goal. The
   interview then continues as today and fills the brief. Candidate sources default to the selected tables.
4. **Modeling patterns** and **Metric Designer**, unchanged.

Stage of a sub-project: no sources -> Sources; sources but no confirmed brief -> Intent; confirmed brief -> Design;
validated draft -> Validated. Existing sub-projects keep their data; their stage is computed with the new rule.

## Memory (from the stateful agents page)

The Databricks agent memory store (Lakebase-backed sessions and long-term memory with semantic search) is meant
for agents built on an agent framework. This app is not an agent: the server makes single tool calls to a model
endpoint, and the page does not say that a direct-endpoint app can use the store. Its value here is small: a
project has a few briefs, not thousands of facts to search.

Proposal, in the existing Lakebase schema:

- **Sessions:** save the intake chat per sub-project, so a reload or a second visit continues the conversation.
- **Project memory:** when a brief is confirmed, its glossary, assumptions and decisions become memory of the
  parent project. A new sub-project in the same project starts with them, so "Net Revenue" means the same thing in
  Revenue and in Returns. The user sees and can remove each memory item.

Revisit the managed memory store if a sub-project needs memory across many projects, or when the store has a
documented REST API for apps.

## Risks

- Discovery adds one model call per sub-project. It sends metadata only and is traced.
- The relationship check uses key names; it can miss joins on other names. The AI review still proposes keys.
- Readiness without a brief cannot judge fit to the goal; coverage appears after the brief is confirmed.

## Decisions (2026-11-04)

- Order approved: Sources, Readiness, Intent & Context, Modeling patterns, Metric Designer.
- Memory: Lakebase sessions and project memory, not the managed agent memory store.
- The relationship check adds an AI explanation of why tables do or do not belong together, besides the key-name rules.
