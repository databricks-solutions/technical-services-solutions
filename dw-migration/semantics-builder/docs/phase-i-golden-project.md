# Phase i: the golden project

Status: approved 2026-11-11. Phase i runs before h6 (dashboard) and h7 (legacy import).

## Goal

One sub-project goes from data to a trusted Genie agent, with a check and a review at each step:

1. Silver or gold tables, checked and certified.
2. A metric view on the certified tables, validated, approved and promoted.
3. A Genie agent on the promoted view, measured with benchmarks and improved until it meets a target.

A sub-project that passes all the gates is a golden project.

## Decisions (2026-11-11)

- The app sets the Unity Catalog governed tag `system.certification_status = certified` on tables and on the
  promoted view, as the user. The user needs APPLY TAG (or ownership) on the object.
- Genie optimization: the AI suggests one change at a time. A person approves each change. The app keeps the
  change only if the benchmark accuracy goes up. There is no automatic loop and no job.
- The Genie eval-run API was tested live on the sandbox space before the build (see below).
- Genie Workbench (databricks-solutions/databricks-genie-workbench) is a reference for ideas and APIs only. Its
  license is not open source, so the app copies no code from it.

## Research (2026-11-11)

- Genie Workbench: a Python app that creates, scores (IQ scan, 12 checks) and optimizes Genie spaces with the
  benchmark eval-run API and a hill-climbing loop (accept a change only if accuracy goes up). It has no data
  certification flow.
- Eval-run API (Beta), checked live with `databricks genie genie-*-eval-*`:
  - `POST /api/2.0/genie/spaces/{space_id}/eval-runs` with `{}` runs all benchmarks of the space. The response
    has `eval_run_id`, `eval_run_status` (RUNNING, DONE), `num_questions`, `num_done`, `num_correct`,
    `num_needs_review`.
  - `GET .../eval-runs/{eval_run_id}` gives the status.
  - `GET .../eval-runs/{eval_run_id}/results` lists one result per question.
  - `GET .../results/{result_id}` gives `assessment` (GOOD, BAD, NEEDS_REVIEW), the expected and the actual
    SQL, and the result manifests.
  - One question took about 10 seconds.

## Items

### i1. Certify the data

Status: done 2026-11-11. Live on Net revenue: the checks ran on the 5 tables (the largest has 29,999,795 rows) and
found a constant column (`o_shippriority`). A request to a placeholder reviewer, the reviewer page and cancel
worked. Self-review and apply before approval are stopped. The tag SQL has not run yet: it needs a second person
to approve. Notes: the tables were made with CLONE, so CLONE counts as a data change; the review is a `kind` of
the h5 review (`gsb.review.kind = 'data'`, with a snapshot).

On the tables of the sub-project (Sources & Readiness):

- Data checks, read-only, as the user: row count, freshness (last change from the table history), and for each
  column the share of nulls and empty strings, and constant columns. The app keeps only the check results,
  never the values.
- Ask for certification: the h5 review flow, with a named reviewer, for the tables of the sub-project. The
  reviewer sees the readiness, the data checks and the descriptions read-only.
- On approval, the author applies the tag with SQL that they examine first:
  `ALTER TABLE ... SET TAGS ('system.certification_status' = 'certified')`.
- Readiness shows the certification status of each table.

### i2. Score the Genie agent

A checklist on the space settings, with a fix for each failed check where the app can make one: view and field
descriptions, instructions, sample questions, at least 10 benchmarks, example SQL, and entity matching on text
dimensions.

### i3. Optimize the Genie agent

1. Run the benchmarks (eval run) and show the accuracy and the result of each question.
2. For a BAD question, the AI suggests one change: an instruction line, an example SQL, a synonym, or a field
   description. It never sees result values.
3. The user approves the change. The app updates the space and runs the benchmarks again.
4. The app keeps the change if the accuracy goes up. Else it restores the settings from before.
5. Each run keeps only the counts and the assessment of each question.

### i4. Production Genie agent

A second Genie space on the promoted view, with the settings of the optimized sandbox space. The author gives
CAN RUN to the audience. Promote updates it.

### i5. Golden project

The Overview shows the path and the status of each gate: certified tables, a validated and approved view,
a promoted view, and Genie accuracy at or above the target (default 85%). The sub-project gets a "Golden" tag
when all gates pass.

Each item gets its own commit, unit tests, a deploy, a live test, and a README and wiki update.
