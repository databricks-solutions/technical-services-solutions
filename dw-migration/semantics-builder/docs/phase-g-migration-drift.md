# Phase g: Migration and Drift

From the original brief, module 5 "Migration & Custodian Utility": discover existing metrics, consolidate duplicate
KPIs, adopt views, monitor drift, and show a health page per view. Adopt is done (phase e: import, versions,
promote, restore). This phase adds drift, health, and discovery, in four steps.

## g1. Drift checks on demand, as the user

A "Check drift" action per promoted view, on the Unity Catalog tab and in the Metric views library. It runs as the
user (OBO), like every other read. Each finding has a kind, a severity, and a suggested fix.

| Kind       | What the app compares                                                                              | How                                              |
| ---------- | -------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| Schema     | Source columns and keys now, with the view YAML: dropped, renamed or retyped columns, broken joins | UC tables API, the designer validator            |
| Definition | The YAML in UC with the promoted version; other metric views with the same KPI names               | `view_definition`, `sameYaml`                    |
| Governance | Owner and grants with the last check; a new row filter or mask that blocks materialization         | `tables.get`, `SHOW GRANTS`                      |
| Usage      | Materialization refresh status and age; measures that no query used                                | `DESCRIBE EXTENDED`, Query History (`sql` scope) |
| Data       | Row count and measure totals of the test queries with a baseline                                   | See question 2                                   |

Fixes link to the existing paths: restore and promote, a readiness fix, a dictionary change, or a materialization
change. Nothing changes without a review, as today.

## g2. Health page and history

- A table `gsb.drift_check` (view, time, user, findings jsonb). A "Health" column in the library: OK, Warning or
  Error, from the last check, with its age.
- A health page per view: findings of the last check, history, and the fix action of each finding.

## g3. Schedule

A Lakeflow job that runs the same checks daily and writes findings to Lakebase. See question 3 for its identity.

## g4. Discover and consolidate

- **Discover:** scan schemas that the user picks for metric views and SQL views with aggregations (`GROUP BY` and
  `SUM`, `COUNT` and others in `view_definition`).
- **Consolidate:** group KPIs with the same or a similar name, or the same expression after normalization. Show the
  conflicts (same name, different formula). Propose one canonical definition. Optional: write it to the project
  dictionary as certified.
- **Map:** import the canonical view (phase e import), and list the old views that it replaces.
- Later: AI/BI dashboard datasets and Genie space instructions (more app scopes), dbt, LookML, Power BI files
  (through the dictionary import formats).

## Questions

1. Order: g1, g2, g3, g4 (recommended), or g4 (discover and consolidate) first?
2. Data drift needs a baseline: row counts and measure totals of the test queries, stored in Lakebase. Today the app
   stores no result values. Store totals only, opt-in per view (recommended), or skip data drift?
3. The scheduled job reads customer metadata and data. Run it as the user who turns on the schedule (recommended,
   same identity as the checks), or as the app service principal with grants on each view?
4. Discover in v1: metric views and SQL views only (recommended), or also dashboards and Genie spaces?
