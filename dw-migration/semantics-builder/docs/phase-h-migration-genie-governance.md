# Phase h: migration import, Genie in the app, trust and governance

Status: approved 2026-11-10.

Decisions (2026-11-10):
- Tests and reconcile store only pass or fail and the difference in percent. Actual values show live, never stored.
- Approvals: the author shares one sub-project read-only with a named reviewer, by email. No group reviewers
  (the app cannot check group membership with its scopes).
- Genie chat: a Genie button in the header opens a side panel on every page, scoped to the current sub-project.
- Legacy uploads: the app keeps only the parsed model and deletes the file after the parse.

## Goal

Make the app the place where a team moves a legacy semantic model to Unity Catalog metric views, proves the
numbers, and gets the views to the users (Genie and dashboards) under governance.

## Research summary (2026-11-10)

Sources: docs.databricks.com, format research, and the "BI Migration MCP Connection Setup Guide" (Google Doc).
Items marked "verify" were not confirmed in the docs and are checked live before the build of that item.

- **Genie One has a documented API** (Beta, workspace preview toggle): `/api/2.0/genie/one/responses` (SSE),
  plus conversation list, items and delete. Scope `genie`. The app now calls an undocumented endpoint
  (`/api/2.0/data-rooms/tools/onechat/responses`). It must move to the documented one.
- **Genie Conversation API** is GA. Paths use `space_id`. Scope: `genie` (verify). Poll with backoff.
- **Genie space config** goes in `serialized_space` version 2: `data_sources.metric_views`,
  `instructions.text_instructions`, `example_question_sqls`, `sql_snippets` (measures, filters),
  `config.sample_questions`, and `benchmarks.questions`. A run-benchmark API: verify.
- **AI/BI dashboards:** `POST /api/2.0/lakeview/dashboards` with `serialized_dashboard`, then
  `.../published`. Datasets can read a metric view directly. Which app scope the API accepts: verify
  (no `dashboards` scope exists; `sql` is the candidate).
- **Lineage:** `system.access.table_lineage` and `column_lineage`. Entity types NOTEBOOK, JOB, PIPELINE,
  DASHBOARD_V3, DBSQL_QUERY; Genie Agents and alerts are captured. A metric view shows as
  `source_type = METRIC_VIEW`. The user needs SELECT on the system tables.
- **Metric view YAML 1.1:** window measures (`cumulative`, `trailing N day`, `offset: -1 year` from Runtime
  18.1), semi-additive (`semiadditive: last`), synonyms, display names, `cardinality`.
- **Certification:** governed tag `system.certification_status` = `certified` or `deprecated`, set with
  `SET TAG ON VIEW`.
- **Legacy import:** Genie Code `/importBI` already converts Tableau (`.twb/.twbx/.tds/.tdsx`) and Power BI
  (`.pbit/.tmdl`) to metric views, with an LLM. Lakebridge has no BI converter. Nothing covers dbt, LookML,
  SSAS, Cognos or MicroStrategy.
- **Migration MCPs:** the guide covers 2 live read-only sources for Genie Code: a self-hosted Tableau MCP app
  (one shared PAT, no per-user isolation) and the Microsoft Fabric Power BI MCP (preview, per-user OAuth via a
  UC HTTP connection). Use from an app server is not documented.

## Items

### h1. Genie in the app

1. Move Ask Genie One to `/api/2.0/genie/one/responses`. Keep the parser for the SSE events
   (`response.output_item.*`, `response.completed`). Show a clear message when the preview is off.
2. **Genie chat panel.** A chat on the sub-project and on the Metric views page:
   - **Genie Agent** (the space on the promoted view, or on the sandbox view): Conversation API, follow-ups,
     the SQL and a small result table for each answer.
   - **Genie One:** the documented API, streamed to the browser through the server (SSE proxy, as the user).
   - The answer shows what Genie read (the existing "read" check), and a "Use as a test" action that turns a
     question into a measure test (h3).
   - Conversations stay in Databricks. The app stores only the conversation id, never the answer text.
   - Status (2026-11-11): built. The panel opens on sub-project pages (the Metric views page has no single view
     to scope it to). The conversation id stays in the browser only. Genie One stays on the current endpoint and
     answers each question alone, without the SSE proxy, until the documented API is on (h1.1).

### h2. Genie space setup from the design (#12)

Build `serialized_space` from what the app knows: the metric view as data source, text instructions from the
brief (goal, audience, rules), sample questions from the key questions, synonyms from the dictionary, example
SQL from the tests, and benchmark questions with the expected values from h3. Show the JSON before it runs.
Update the space when the design changes.

Status (2026-11-11): built, on the sandbox space. Notes from the live test:
- The SDK request drops the body of a PATCH, so the app sends the update with `fetch` and SDK-signed headers.
- Genie joins `text_instructions.content` items with no separator. The app sends one string with line breaks.
- `data_sources.metric_views` is stored as `tables`. The app uses `tables`.
- A space on the promoted view, and benchmark eval runs, are not built yet.

### h3. Measure tests with expected values (#2)

A new test kind: a measure, optional filters and a group, an expected value and a tolerance (for example
"Net revenue, year 2024 = 12,300,000 +/- 0.5%"). Runs in the sandbox on Validate, and again as a gate before
Promote. See question 2 about stored values.

### h4. Impact analysis (#6)

Before Promote, compare the new version with the promoted one (removed or renamed fields) and list who uses
the view: dashboards, Genie Agents, queries, jobs, notebooks from `table_lineage`, and the fields they query
from `column_lineage` (Query History text is redacted in many workspaces, so it is not used). The Promote modal shows "3 dashboards use `Customer region`, which this version removes".
Without SELECT on the system tables, the modal says so and shows the field changes only.

### h5. Approval workflow (#7)

Promote can need approval. The author requests it and names a reviewer (a user or a group). The reviewer opens
a read-only review page: the diff, the tests, the impact, and the SQL. Approve or reject, with a comment.
Self-approval is blocked. Every step goes to the audit log. Projects are private to their creator today, so
this needs a share model (question 3).

### h6. Starter AI/BI dashboard (#13)

Status: done 2026-11-12. Publish, Dashboard. The dataset is the metric view (`asset_name`), with MEASURE() in each
widget: KPI counters (with a monthly sparkline), a monthly line and a bar by the first text dimension. Window
measures are left out. The dashboards API refused the app token's scope, so the app shows the JSON and the
`databricks lakeview create` command, and the user runs it (like the Pages script and the Genie agent access).
Live: the command made the draft "Net revenue - starter (app check)" (01f1deaa13c61f338fc7fa90fc6c54f8) on the
promoted view; the SQL of each widget ran on that view first. The render in the browser was not checked: the
browser was not signed in to the workspace. The app now logs the API text of a missing-scope error.

From the promoted view: KPI counters for the main measures, a trend by the time dimension, and a breakdown by
the top dimension. Created as a draft dashboard, as the user, in a folder the user picks. The user reviews and
publishes it in Databricks. Show the dashboard JSON before it runs.

### h7. Import legacy semantic models (#16)

Status 2026-11-12: 1 of 7 formats done, dbt MetricFlow (rules only, no AI). Live: a dbt YAML on the TPC-H copies
made the sub-project "dbt import check" in Order fulfilment, with a join, 4 dimensions and 4 metrics converted (one
with a Jinja filter, one ratio) and a cumulative metric left for a person; the draft validated and its 3 tests
passed. The dbt status of each field is in its note (the explanations).

LookML done 2026-11-12 (2 of 7), with its own small parser (no new dependency). Live: a view file and a model file
on the TPC-H copies made the sub-project "LookML import check": a join, a dimension group, a filtered measure and
a number measure, 11 fields converted; the draft validated and its 3 tests passed. After that test, primary keys
are no longer added as dimensions.

Power BI (.pbit) and SSAS Tabular (.bim) done 2026-11-12 (3 of 7). A small zip reader (in memory, size limits)
reads DataModelSchema from a .pbit. DAX converts by rules first (dax.ts, a tokenizer and a small translator); the
AI gets only the DAX that has no rule, with the column and measure names, and its SQL is always "Check it". The
preview returns the AI SQL and create sends it back, so the AI runs once. Live: a .bim on the TPC-H copies made
"Power BI import check": 7 fields by rules, SUMX by the AI (`SUM(o_totalprice * 0.9)`), TOTALYTD left for a person;
the draft validated and its 3 tests passed. Not yet: TMDL (the folder text format).

Tableau done 2026-11-12 (4 of 7), with a small strict XML reader (no DOCTYPE, no entities, no new dependency) and a
calculation translator (tableauCalc.ts). The AI prompt is now shared by DAX and Tableau (legacyCalc.ts). The
server body limit is 12 MB, so a packaged workbook fits. Live: a .twb on the TPC-H copies made "Tableau import
check": 9 fields by rules (IF inside SUM, COUNTD, a measure reference, DATETRUNC, IIF), TOTAL() left for a person
(the AI said it has no SQL form); the draft validated and its 3 tests passed.

Cognos Framework Manager done 2026-11-12 (5 of 7), reusing the XML reader, with an expression translator in
cognos.ts and the shared AI prompt. Live: a model.xml with a database and a business layer on the TPC-H copies made
"Cognos import check": 7 business fields by rules (if then else inside total, a business measure reference),
running-total left for a person; the draft validated and its 3 tests passed. Next: MicroStrategy (REST JSON export).

One pipeline for all formats: a parser per format, then one intermediate model (tables, joins, dimensions,
measures, filters), then a draft metric view in a new sub-project.

- Each converted field keeps its **source expression** and a **status**: converted, converted with AI (review),
  or not converted (manual). The Designer shows them, and Validate plus tests (h3) check them.
- Deterministic rules first. The model translates only the hard expressions (DAX, MDX, Tableau calcs, Cognos,
  MicroStrategy), and always shows the source next to the result.
- Order (easiest and most value first):
  1. dbt MetricFlow (`semantic_models` YAML or `semantic_manifest.json`)
  2. LookML (`.lkml` views and explores)
  3. Power BI (`.pbit`, TMDL) and SSAS Tabular (`.bim`): one TMSL/TMDL model for both
  4. Tableau (`.twb/.tds`, and `.twbx/.tdsx` zips)
  5. Cognos Framework Manager (`model.xml`)
  6. MicroStrategy (REST API JSON export; `.mmp` packages are not readable)
  7. SSAS Multidimensional (`.cube/.dim/.dsv`, MDX): last, best effort
- **Tableau and Power BI overlap with `/importBI`.** The app also lets the user adopt the metric views that
  `/importBI` made (the existing Adopt tab), then test and reconcile them. The README says when to use which.
- **Migration MCPs (later, h7b):** live read of Tableau or Power BI models through the MCPs in the guide, to
  check a parsed file against the live source. Only after we confirm that an app server can call them as the
  user. The Tableau MCP uses one shared PAT, so it is not safe for multi-user apps as is.
- Parsers: only permissive licenses (MIT, Apache-2.0, BSD), each added to `LICENSE-THIRD-PARTY.md`. Uploaded
  files are untrusted: size limits, zip limits (no path traversal, no zip bombs), XML without external entities.

### h8. Reconcile with the source system (#17)

The user gives the legacy totals: typed in, or a CSV export of a legacy report (dimension columns and measure
columns). The app runs the same grouping on the metric view and shows each row with the difference and a
pass or fail per tolerance. A passing reconcile can become a set of h3 tests.

### h9. UI polish

A UX review pass with screenshots of every page, light and dark, wide and narrow. Then fixes. Candidates:
one page-header pattern, empty and loading states, long-name truncation, success toasts instead of inline
alerts, Designer density, Metric views page layout, keyboard focus.

## Order

1. h1.1 (the undocumented endpoint is a risk now)
2. h3 (tests are the base for h2, h5, h7 and h8)
3. h4, then h5
4. h1.2 and h2
   Then phase i (the golden project, `docs/phase-i-golden-project.md`), before h6 and h7.
5. h6
6. h7 (dbt, LookML, then TMSL/TMDL, Tableau, Cognos, MicroStrategy, SSAS MD), then h8
7. h9 runs after each step, and as one full pass at the end

Each item gets its own commit, unit tests, a deploy, an e2e test where it fits, and a README update.

## Scopes and permissions

- App scopes stay `sql`, `genie`, catalog reads. The Lakeview scope is checked in h6 before the build.
- Users need SELECT on `system.access.table_lineage` and `column_lineage` for h4.
- Certification (optional, with h5): APPLY TAG or ASSIGN on `system.certification_status`.

## Risks

- Genie One API is Beta and needs a preview toggle per workspace.
- LLM translation of DAX, MDX and Tableau calcs can be wrong. Mitigation: source next to result, review status,
  tests and reconcile.
- Lineage is a subset of events, so impact analysis can miss a consumer. The modal says so.
- `/importBI` will improve, so Tableau and Power BI conversion in the app can lose value. Mitigation: build
  those formats after dbt and LookML, and keep the adopt path.
