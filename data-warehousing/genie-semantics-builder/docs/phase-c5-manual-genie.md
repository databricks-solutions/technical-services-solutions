# Phase c5: Manual paths, Unity Catalog links, Genie check

Status: plan, not approved. Date: 2026-11-05.

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
- **Genie One** (the workspace-wide Genie in Databricks One): whether an app can call it. If not, the tab uses a
  Genie space, and Genie One is noted as future work.
- Cost: Genie questions run SQL on the space warehouse; they count against the Optimize budget.

## Order

c5.2 (links, small) first, then c5.1 (manual paths), then c5.3 (Genie, after the spike). Phase c4 (dictionary)
can go before or after c5; see the questions.

## Questions to decide

1. Order: c4 dictionary first, or c5 first?
2. Ask Genie: a Genie space per sub-project in the sandbox, as described, until we know whether Genie One can be
   called?
3. Manual paths: is the list above complete, or is there a step you also want by hand?
