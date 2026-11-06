# Phase e: Metric view library, import, field table, promote and roll back

Requested 2026-11-05. Builds on the designer versions (phase b) and the Optimize module (phase d). Phase f (owner
transfer and grants) stays next, and runs before a materialization.

## 1. Import a metric view made outside the app

- **Pick:** a catalog, schema and metric view picker that lists only `METRIC_VIEW` objects the user can see (UC
  tables API, `catalog.tables:read`, as the user).
- **Read:** `tables.get` returns the full YAML in `view_definition` (checked on a sandbox view). The app parses it
  with the same validator as the designer.
- **Assign:** a new project and sub-project, or a new sub-project in an existing project. The user picks.
- **What the import creates:**
  - Sources: the view source and every join source that is a table.
  - Brief: a draft built from the view (title from the name and comment, measures, dimensions, sources). The user
    confirms it with one click, or edits it by hand.
  - Design version 1 with origin `imported`, the YAML as it is in UC, and the view as the **promotion target**.
- Then every module works as for an app-made design: readiness, dictionary, validation, Optimize, Ask Genie.

## 2. Metric views library

A "Metric views" page in the navigation, for all projects the user can see. One row per sub-project with a design:

| Column            | Value                                                               |
| ----------------- | ------------------------------------------------------------------- |
| Metric view       | The promotion target, or "Not promoted"                             |
| Project           | Project and sub-project, with a link to the designer                |
| Promoted version  | Version in UC, when, by whom                                        |
| Latest version    | Latest draft version and status (draft, validated)                  |
| Behind            | "Up to date" or "N versions newer than UC"                           |
| Actions           | Open in Unity Catalog, Open in designer, Import another             |

Sandbox views (validation and stress tests) are listed apart, so they are not mistaken for the real views.

## 3. Fields as a table, with an edit mode

- The Model tab shows **Measures** and **Dimensions** as two tables: name, display name, SQL, additivity or
  window, comment, dictionary tag. The cards go away.
- **Edit** turns the tables editable: change any cell, remove a row, **Add a measure** or **Add a dimension**
  (the current form, as a row editor with table, column and aggregation pickers). Joins stay in the YAML tab.
- **Save** creates one new version with origin `edited`. **Cancel** drops the changes.

## 4. Promote to Unity Catalog

- **Target:** set once per sub-project: catalog, schema and view name. Imported views default to their own name.
- **Rule:** only a **validated** version can be promoted.
- **Review:** the app shows the `CREATE OR REPLACE VIEW ... WITH METRICS LANGUAGE YAML` statement. It runs as the
  user after approval (the allowlist already permits it), with an audit entry.
- **Record:** a `promotion` row per run: version, target, who, when, outcome. The designer shows "Version N is in
  Unity Catalog" and an Open in Unity Catalog link.
- **Guard:** before it replaces a view, the app reads the view in UC. If its YAML differs from the last promoted
  version (someone changed it outside the app), it shows the difference and asks again.

## 5. Roll back

- In History, each version has **Restore**: it copies that version as a new version with origin `restored`. A copy
  of a validated YAML keeps the validated status, so it can be promoted at once.
- **Roll back in UC** = Restore an older version, then Promote it. History shows which versions were promoted.

## Questions

1. Brief of an imported view: a draft that the user confirms (recommended), or confirmed at once?
2. Promotion target: set per sub-project (recommended), or chosen each time?
3. Roll back: restore as a new version, then promote (recommended), or promote an old version directly?
4. Order: Ask Genie (approved) first, then this phase? Or this phase first?
