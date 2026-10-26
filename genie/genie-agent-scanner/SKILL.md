---
name: genie-space-scan-optimize
description: >-
  Audit and improve a single Databricks Genie space / Genie agent's
  configuration quality. Runs a deterministic 12-check "IQ scan" (data sources,
  table/column description coverage, instructions, joins, example SQL,
  benchmarks, entity matching) with RLS / column-mask safety guidance, scores it
  0-12 with a maturity tier, and then guides approval-gated context fixes
  applied through the Genie REST API. Use whenever someone asks to scan, audit,
  score, health-check, review, or optimize a Genie space or Genie agent, or
  wants a lightweight "mini Genie Workbench" without installing the Workbench
  app. Portable across Genie Code, Claude Code, and Cursor.
---

# Genie Space Scan & Optimize

A condensed, deterministic port of Databricks Genie Workbench's "IQ Scan +
guided optimize" for ONE Genie space / agent at a time. It measures
configuration readiness against an explicit rubric, then helps you apply safe,
approved context fixes. It does not require the Workbench app.

## Usage (say it simply)
You do NOT need a long prompt, and you do NOT need the space id. Name the space
(or just say "this space" when you are already in it) and say what you want:
- "Scan the Meridian Customer Operations space."
- "Help me scan this Genie space and tell me what to fix first."
- "@genie-space-scan-optimize audit this agent's setup (read-only)."

On any such request the skill resolves the space, runs the deterministic scorer,
and reports the score, tier, and ranked fixes. Everything below is the agent's
playbook, not something you type.

Asking for fixes is always safe: if you say "suggest fixes" or "optimize this
space", the skill previews the exact changes and writes NOTHING until you
explicitly approve that diff. You never have to add "do not apply".

## How to run this skill (READ FIRST: run the scorer, never emulate it)
The 12-check IQ score is produced ONLY by the deterministic scorer in
`scripts/` (`scan.py`, or the pure `scan_space` function it wraps). It is
deterministic on purpose so its numbers match Genie Workbench and are
reproducible. NEVER hand-compute the checks or eyeball coverage. Hand-analysis
produces different, non-reproducible numbers that will not match the scorer or
Workbench.

The scorer reads TWO inputs, and you must keep them straight:
1. The space config (`serialized_space`): data sources, instructions, joins,
   example SQL, snippets, benchmarks, and any per-column config.
2. Unity Catalog (UC) metadata per table: its `comment`, its `table_type` (used
   to tell a metric view from a table), and its columns. Workbench uses this
   too. Without it, the table-description and metric-view checks fall back to
   config-only and the report marks `uc_status` as `partial` or `unavailable`.

Per-check source of truth (do not cross these wires):
- Metric view vs table: a data source is a metric view ONLY when its UC
  `table_type == "METRIC_VIEW"`. Everything else is a table.
- Table descriptions (check 2): a table counts as described if it has a
  space-level description OR a UC table comment. The denominator is TABLES ONLY.
- Column descriptions (check 3): counts ONLY columns explicitly configured in
  the space. It NEVER counts UC columns. If the space configures 0 columns, the
  check FAILS 0/0; it does not pass. (Counting UC columns here is the single
  biggest fidelity bug. Do not do it.)

Pick the runtime that matches where you are:
- Running LOCALLY (Claude Code, Cursor, a notebook, or a terminal with a
  Databricks profile): run the script directly. It fetches the config and
  auto-enriches from UC.
  ```
  python scripts/scan.py --space-id <SPACE_ID> --json-out scan.json --md-out scan.md
  ```
- Running INSIDE Genie Code (the chat agent): the chat sandbox does NOT allow a
  skill script to spawn a subprocess, use the Databricks SDK/CLI, or read a
  token. Those attempts are blocked, so do not try them. Instead:
  1. Identify the target space. The user will usually NAME it ("the Meridian
     space") or mean the current one -- you do NOT need them to supply an id.
     Resolve the name with your native tools (match the space title; if two
     titles match, ask which). Then read its config and, for each table, its UC
     comment, `table_type`, and columns.
  2. Write those to two JSON files: the `serialized_space`, and a `uc_metadata`
     map (schema below). Copy every field VERBATIM and COMPLETE -- especially
     the full text of each `text_instruction`, and the full lists of example
     SQL, snippets, joins, and benchmarks. Do NOT summarize, truncate, or
     sample: the scorer's counts (e.g. instruction char length) are only as
     accurate as what you serialize, and a partial capture silently changes
     check results.
  3. Run the PURE scorer offline on those files (no network, no auth, no
     subprocess needed):
     ```
     python scripts/scan.py --serialized-space-file space.json --uc-metadata-file uc.json --md-out scan.md
     ```
     If your runtime cannot execute even this in-process, apply the rubric in
     `references/scan-checks.md` MANUALLY as a last resort, but source every
     check exactly as pinned above (never count UC columns for check 3).

`space.json` (the `serialized_space`) skeleton -- build it in THIS shape so the
scorer accepts it first try (it also accepts a raw API export or an
`{"serialized_space": {...}}` envelope):
```
{ "version": 2,
  "data_sources": {
    "tables": [ { "identifier": "cat.sch.tbl",
                 "column_configs": [ { "column_name": "col" } ] } ],
    "metric_views": [ { "identifier": "cat.sch.mv" } ] },
  "instructions": {
    "text_instructions": [ { "content": [ "..." ] } ],
    "example_question_sqls": [ { "question": [ "..." ], "sql": [ "..." ] } ],
    "join_specs": [],
    "sql_snippets": { "filters": [], "measures": [], "expressions": [], "functions": [] } },
  "benchmarks": {
    "questions": [ { "question": [ "..." ],
                    "answer": [ { "format": "SQL", "content": [ "..." ] } ] } ] } }
```

`uc_metadata` schema (full table name maps to its UC metadata):
```
{ "catalog.schema.table": { "comment": "str|null",
                            "table_type": "MANAGED|METRIC_VIEW|VIEW|...",
                            "columns": [ { "name": "str", "comment": "str|null" } ] } }
```

Whichever runtime you use, report the scorer's `scan.md` VERBATIM (score, tier,
every per-check row, `uc_status`, and the ranked next steps), then add your
interpretation AFTER, clearly separated.

Every number and per-check row in your report MUST be copied from the scorer's
output, never from your own reading of the config. Do NOT round, paraphrase, or
re-narrate: an approximate value (e.g. "~2000 chars", "about 50 examples") or a
row reworded in your own words means you did NOT actually run the scorer. Run it
and paste the literal `scan.md`.

## When to use this
- "Scan / audit / score / health-check this Genie space (or agent)."
- "How good is my Genie space's setup, and what should I fix first?"
- "Improve this space's context without installing Genie Workbench."

## When NOT to use this (delegate instead)
This skill is a deterministic QUALITY GATE, not an AI curator. For open-ended,
LLM-reasoned remediation — diagnosing one specific failed message, mining a
benchmark run for failure themes, capturing new business semantics from a
conversation — defer to the host agent's native curation. In Genie Code that is
the built-in Genie Code curation authoring skills. The clean division of labor:

- **This skill:** measure readiness, enforce explicit thresholds, rank fixes,
  apply approved patches, and track the score over time.
- **Native curation / the host agent:** reason about nuanced, one-off fixes.

Run this to know WHAT is wrong and to gate promotion; use the agent's reasoning
to draft the hard fixes.

## Prerequisites
- Authenticated Databricks access to the workspace that hosts the space. LOCAL
  runs use the Databricks SDK default auth chain (a CLI profile or env vars).
  Inside Genie Code you instead gather the config plus UC metadata with the
  agent's native tools, because the chat sandbox blocks skill-script auth (see
  "How to run this skill").
- The target space, referred to by NAME (the agent resolves it with its native
  tools) or -- for local runs -- its id (from the URL `.../genie/rooms/<id>`).
- Read access to each table's Unity Catalog metadata (comment, type, columns).
  Live scans call `WorkspaceClient.tables.get` per table (read-only, no SQL
  warehouse). If some tables are not readable, the scan degrades to config-only
  for those and reports `uc_status: partial`.
- Python 3.10+ and the dependencies in `scripts/requirements.txt`. The SDK is
  imported lazily, so fully offline scans (`--serialized-space-file`) need no
  SDK at all.
- Permissions: `CAN VIEW` to scan; `CAN EDIT` or `CAN MANAGE` to apply fixes.

## Workflow

### 1. Scan (read-only)
Score the space deterministically with the scorer. Never emulate the checks by
hand, and follow "How to run this skill" for your runtime.

Live (fetches the config and auto-enriches from UC):
```
python scripts/scan.py --space-id <SPACE_ID> --json-out scan.json --md-out scan.md
```
Offline or inside Genie Code (feed the config plus the UC metadata you gathered):
```
python scripts/scan.py --serialized-space-file space.json --uc-metadata-file uc.json --md-out scan.md
```
Output: an IQ score of 0-12, a maturity tier (Not Ready / Ready to Optimize /
Trusted), per-check pass / warning / fail rows with evidence, a `uc_status`
(`full` / `partial` / `unavailable`) that tells you whether UC enrichment was
complete, and ranked next steps. If `uc_status` is not `full`, the
table-description and metric-view checks may be understated: gather the missing
UC metadata and re-run before trusting them. Checks 11-12 (optimization run and
accuracy) require an `optimization_run`; without one, a config-perfect space
tops out at "Ready to Optimize". See `references/scan-checks.md` for the rubric.

### 2. Report
Present `scan.md` to the user: the score, the tier, what failed and why, and the
ranked next steps (fix-order: data sources -> table/column descriptions ->
joins -> example SQL / benchmarks -> instructions). Do not change anything yet.

### 3. Guided optimize (approval-gated)
**Preview-only by default. This skill NEVER writes a fix unless the user, after
seeing that specific diff, explicitly approves applying it.** Treat every
"suggest fixes", "optimize", "fix check N", or "what should I change" request as
dry-run only: draft the fixes, show the diff, then STOP. The user does NOT need
to say "do not apply" -- not applying is the default, and writing is something
they must explicitly opt into. A prior general "yes, go ahead" is NOT approval
to write; approval must come after the diff and must clearly mean "apply this".
If you are unsure whether the user approved, do NOT apply.

Only the checks mapped in `SCAN_CHECK_TO_LEVERS` are fixable by config edits
(table/column descriptions, synonyms and entity matching, text instructions,
join specs, example SQL, and SQL snippets). Checks 1, 6, 10, 11, and 12 are not
config-fixable.

**Be wary of benchmarks.** You may add benchmark questions via
`add_benchmark_question` to seed a space, but adding rows does not "fix" check
10: a trustworthy benchmark is a curated, user-owned artifact — real questions
with verified answers, run through the benchmark / optimization workflow. Never
treat tool-added benchmark rows as satisfying check 10, and never tag a fix with
`check_id: 10` (the tool rejects it). Recommend proper benchmark curation as a
user next step instead.

For each fixable finding:

1. **Draft a fix yourself**, following `references/fix-contract.md` EXACTLY: use
   the documented `fixes.json` operations, and preserve every existing
   `## Section` header inside a text instruction.
2. **Classify each fix's risk** (LOW / MEDIUM per the fix contract). v1 does not
   perform HIGH-risk structural edits (add/remove table, TVF SQL, metric-view
   YAML) — propose those to the user to do manually.
3. **Preview the exact change** (dry run — writes nothing):
   ```
   python scripts/optimize.py --space-id <SPACE_ID> --fixes-file fixes.json --scan-file scan.json
   ```
   This prints a unified diff of `serialized_space` (before -> after) and
   validates the fixes against the schema.
4. **Show the diff to the user.** Apply ONLY with explicit approval:
   ```
   python scripts/optimize.py --space-id <SPACE_ID> --fixes-file fixes.json --apply
   ```
5. **Re-scan** to confirm the score moved.

## Safety rules
- Default to dry run. NEVER pass `--apply` / PATCH unless the user explicitly
  approved applying the SPECIFIC diff you just showed. Preview is the default;
  writing is opt-in. Do not infer approval from an earlier general go-ahead.
- `optimize.py` round-trips and PRESERVES every unknown / unrecognized field; it
  never drops config it did not touch.
- Entity matching and RLS: Genie silently disables entity matching on RLS /
  column-mask tainted tables. The v1 scan does NOT run the live RLS audit, so
  verify a table's RLS/mask status manually (or via native curation) before
  enabling entity matching on it.
- Respect budgets: 100 instruction slots, 200 SQL snippets, 25,000 chars per
  string. See the fix contract.
- This skill edits ONE space at a time.
- No external / network actions beyond the Genie REST API of the target
  workspace. Do not push, publish, or message anywhere else.

## Composition with native Genie Code curation
Native Genie Code curation is LLM-reasoned and has no fixed 0-12 score, no fixed
coverage thresholds, and no RLS audit, so this skill is additive rather than
redundant. In Genie Code: run this skill's scan as the deterministic gate, let
native curation handle nuanced fix-drafting, then re-run the scan to confirm the
score improved and to gate promotion.

## Install (Genie Code)
- **Workspace skill** (team-wide standard): place this folder at
  `Workspace/.assistant/skills/genie-space-scan-optimize/`.
- **User skill** (personal use / prototyping): place it at
  `/Users/<username>/.assistant/skills/genie-space-scan-optimize/`.
- In the Genie Code pane: **Settings -> Open skills folder**. Start a NEW chat
  after adding or editing the skill (edits do not affect an active chat). Invoke
  by relevance, or type `@genie-space-scan-optimize`.
- Back the folder with a Databricks Git folder to version, share, and roll back.

Footprint: this skill is deliberately small -- `SKILL.md`, three reference docs,
and a handful of Python files under `scripts/`. No app, no Lakebase, no running
service, nothing to deploy, and no grants beyond Genie/UC read (plus write only
when you approve a fix). The developer test-suite is NOT shipped in the
installed skill, to keep the review surface small.

Portability: this is a standard Agent Skill, so the same folder also runs in
Claude Code and Cursor against the Genie REST API.

## References
- `references/scan-checks.md` — the 12 checks, thresholds, severities, maturity
  tiers, the RLS / column-mask audit, and the SQL-in-prose detector.
- `references/fix-contract.md` — the `fixes.json` operations, risk tiers, valid
  field paths, GSL section preservation, sanitization guardrails, and budgets.
- `references/best-practices.md` — fix-order, instruction placement, and
  anti-patterns.

## Out of scope (v1)
The heavyweight benchmark-driven Auto-Optimize (Workbench's GSO closed loop: a
full-benchmark, multi-iteration hill-climbing search over the six optimization
levers) is intentionally excluded, as is the live RLS/mask audit and structural
(HIGH-risk) edits. If the space has >= 10 benchmarks, a lightweight "prove it
improved" pass (ask Genie -> compare results -> arbiter) can be added later; the
deep loop stays in Genie Workbench.
