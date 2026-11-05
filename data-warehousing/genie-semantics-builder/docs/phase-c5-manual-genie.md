# Phase c5: Manual paths, Unity Catalog links, Genie check

Status: approved 2026-11-05, after phase c4. Date: 2026-11-05.

## Goal

1. **Manual first, AI as help.** Every step works without the model. The AI proposes, explains and fixes when the
   user asks or when something fails.
2. **Open in Unity Catalog** wherever the app shows a table, a view or a pipeline.
3. **Ask Genie:** check that Genie answers the business questions with the metric view as expected.

## 1. Manual paths

Audit (2026-11-05): sources, YAML editing, stress test and materialization choice are already manual. These are
AI only today:

| Step | Today | Manual path |
|---|---|---|
| Intent & Context | Brief comes from the chat or the form, through the model | **Edit brief** form for every field (goal, audience, questions, measures, dimensions, grains, glossary, assumptions). Saved as a new brief version, origin "edited". Confirm works the same. |
| Metric Designer | "Generate design" only | **Start from a template**: a YAML skeleton built from the sources (fact table, joins on declared or suggested keys, one COUNT measure), with no model call. Then edit. |
| Tests | Model writes them | **Test editor**: add, edit or remove a test (name, dimensions, measures) from the view's fields. |
| Measures and dimensions | Only in YAML or from the model | **Metric builder**: add or edit a measure or dimension in a form (name, display name, description, synonyms, expression from column pickers with SUM/COUNT/COUNT DISTINCT/AVG/MIN/MAX/ratio, format, filter). The YAML updates and is validated as you go. |
| Readiness fixes | Model writes comment text | **Edit the text** of a proposed comment before apply. The server still builds the SQL, so the user edits text, not SQL. Also "Write a comment" for any column, without a proposal. |

**AI as help**, where it is not already:

- YAML errors: "Explain and fix with AI" next to the error list.
- Validation failures: "Fix with AI" with the failed test details (today this needs a typed instruction).
- Empty brief sections: "Suggest with AI" per section.

A per-user setting "Start with AI" (on by default) only changes which button is primary; both paths stay
visible.

## 2. Open in Unity Catalog

- Links to Catalog Explorer (`<workspace>/explore/data/<catalog>/<schema>/<table>`) on source tables, the lineage
  cards, the sandbox views of validation and stress tests, and the published view later (phase f). The pipeline
  link of a materialization try exists already.
- The workspace URL comes from the app environment (`DATABRICKS_HOST`), served by a small config endpoint. Not
  hardcoded.

## 3. Ask Genie

A tab "Ask Genie" in Optimize, for a validated design:

1. **Space:** the app creates one Genie space per sub-project, as the user, on the sandbox metric view, with the
   brief title, description and glossary as instructions. It is updated when the design version changes.
2. **Questions:** the brief's key questions, the sample questions of applied patterns, and questions the user
   types.
3. **Expected answer:** for each question the user can attach the measures and dimensions it should use; the app
   builds the MEASURE() query from them (the same builder as the stress test).
4. **Run:** the app asks Genie each question through the Genie Conversation API, then shows Genie's text answer,
   its SQL and its result next to the expected result. Verdict per question: **matches**, **different result**,
   **no answer**, or **needs review** (no expected answer attached).
5. **Improve:** misses become suggestions: a synonym, a better comment, a sample question, or a measure that is
   missing. Applying one creates a new design version.

Facts to check in a spike before building:

- The app scope for Genie (`dashboards.genie`) and that a space can use a **metric view** as its data source.
- Space create and update through the API with a serialized space, as the user (OBO).
- **Genie One** (OneChat): the CLI calls `POST /api/2.0/data-rooms/tools/onechat/responses`, which streams SSE
  events with the answer, the SQL it ran and its results (Confluence: "OneChat in Databricks CLI", 2026-03,
  experimental). The installed CLI (v1.21) has no `onechat` command, so the spike calls the endpoint directly with
  the app's OBO token and checks which scope it needs. The tab offers both: a Genie space on the sandbox view, and
  Genie One when the endpoint works for apps.
- Cost: Genie questions run SQL on the space warehouse; they count against the Optimize budget.

## Order

c5.2 (links, small) first, then c5.1 (manual paths), then c5.3 (Genie, after the spike). Phase c4 (dictionary)
can go before or after c5; see the questions.

## Decisions (2026-11-05)

- Order: c4 (dictionary) first, then c5 in the order above.
- Ask Genie: Genie spaces and Genie One (OneChat), whichever the spike shows works for apps.
- Manual paths include building measures and dimensions by hand.
