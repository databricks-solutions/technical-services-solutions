# dabs-migrator Skill Test Harness — Design

**Date:** 2026-08-05
**Status:** Approved (design), pending implementation plan.

## Goal

Validate the `dabs-migrator` skill against as many resource types as practical. We
generate a **seed** Databricks Asset Bundle that deploys ~15 resource types into a
Databricks workspace, run the `dabs-migrator` skill against those deployed resources
(in Genie Code and in a local Claude instance), and evaluate the output.

- **Success:** `databricks bundle validate` exits clean (or the UI validation process
  passes) on the skill-generated bundle. This proves the YAML syntax/schema for every
  migrated resource is correct.
- **Failure:** `bundle validate` reports an error — a problem in the generated resource
  YAML.

Because `bundle validate` only checks schema/syntax and variable resolution, we add a
secondary, **informational** fidelity check (diff of generated YAML vs. seed YAML) so
silently dropped or wrong fields are still visible. The fidelity diff does **not** move
the pass/fail bar.

## Overall flow

```
Phase 0  Bootstrap helper objects (schema + a seed Delta table) via CLI/SQL.
Phase 1  Deploy the "seed" DABs bundle to DEV → creates ~15 resource types.
Phase 2  Run the dabs-migrator skill (Genie Code + local Claude) against the
         deployed resources → produces the "migrated" bundle.
Phase 3  Evaluate:
           - PASS/FAIL: `databricks bundle validate` on the migrated bundle.
           - Informational: fidelity diff of migrated/resources/**.yml vs
             seed/resources/**.yml.
```

Two separate bundles in two separate folders so they never collide: a **seed** bundle
(we author) and the **migrated** bundle (the skill authors).

## Environment

- Databricks CLI `v1.5.0` (matches the skill's schema reference).
- Profile: **DEV**.
- Unity Catalog location for the seed's UC resources: **`classic_stable_aiy0te.dabs_test`**.
- Migrator CI/CD tool: **GitHub Actions** (the skill default).
- Testbed lives OUTSIDE the skill's git repo, in a sibling folder `../dabs-migrator-testbed/`,
  to keep the skill repo clean.

## Seed bundle — resource coverage (practical broad set)

One resource per file under `resources/`, unique names prefixed `dm_`. Target
`classic_stable_aiy0te.dabs_test` on the `DEV` profile.

| # | Type | Notes / dependency |
|---|---|---|
| 1 | `clusters` | small single-node cluster def (not started) |
| 2 | `sql_warehouses` | 2X-Small, auto-stop; needed by dashboard/alert/genie |
| 3 | `jobs` | notebook task → real notebook in `src/` (tests verbatim source clone) |
| 4 | `pipelines` | SDP pipeline, one `.py` transform writing to the schema |
| 5 | `schemas` | a managed schema created by the bundle |
| 6 | `volumes` | managed volume |
| 7 | `registered_models` | UC registered model |
| 8 | `experiments` | MLflow experiment |
| 9 | `secret_scopes` | Databricks-backed scope |
| 10 | `quality_monitors` | needs the seed Delta table (Phase 0) |
| 11 | `alerts` | needs a query + the warehouse |
| 12 | `dashboards` | Lakeview; serialized JSON over the seed table + warehouse |
| 13 | `genie_spaces` | warehouse + seed table |
| 14 | `models` | legacy MLflow model registry — **best-effort** (may be disabled in UC-only workspaces) |
| 15 | `catalogs` | **best-effort** — creating a new catalog needs metastore privilege; if denied, drop it |

**Deliberately not covered** (documented explicitly in the report so results are honest):
`apps`, `external_locations`, `model_serving_endpoints`, `vector_search_endpoints`,
`vector_search_indexes`, and the Lakebase/Postgres family (`database_instances`,
`database_catalogs`, `postgres_branches`, `postgres_catalogs`, `postgres_databases`,
`postgres_endpoints`, `postgres_projects`, `postgres_roles`, `postgres_synced_tables`,
`synced_database_tables`). Reason: cost, slow provisioning, or external prerequisites.

## Helper objects (Phase 0)

One small managed Delta table in `classic_stable_aiy0te.dabs_test` (created and populated
via a SQL statement before the bundle deploy). The quality monitor, alert, dashboard, and
genie space all reference this table, so it must exist at deploy time.

## Deploy strategy — name prefixing

The seed target sets `presets.name_prefix: ""` so dev-mode does **not** prepend
`[dev <user>]` to resource names. This gives the migrator clean, stable names to reference
and keeps the fidelity diff meaningful. The seed bundle is a throwaway we control; this is
not the migrator's own output and does not violate the skill's "never deploy prod from a
dev machine" rule.

## Migrator invocation + test prompt file

A local file `TEST_PROMPT.md` in the testbed root, containing:

1. **Environment preamble** — tells a *local* Claude to use the `DEV` databricks CLI
   profile to read resource attributes; Genie Code reads natively. The same file works in
   both contexts.
2. **Combined prompt** — "Migrate the following resources to DABs using GitHub Actions:
   `job:dm_job` `pipeline:dm_pipeline` … (all deployed types)." The realistic end-to-end run.
3. **Per-resource prompts** — one prompt per resource type, so if the combined run breaks
   we can bisect which type the skill mishandles.

## Evaluation

- **Pass/fail:** `databricks bundle validate` on the migrated bundle exits 0 (or UI
  validation passes).
- **Fidelity (informational):** a small script diffs `migrated/resources/**/*.yml` against
  `seed/resources/**/*.yml`, flagging dropped/renamed/changed fields, reported per resource.
  It will not be byte-identical (the migrator reads resolved server state, e.g., IDs); it is
  a field-presence/value check, not an exact match.

## Directory layout

```
../dabs-migrator-testbed/
├── seed/                    # the seed bundle we author + deploy
│   ├── databricks.yml
│   ├── resources/*.yml
│   ├── src/…
│   └── bootstrap.sql        # Phase 0 seed table
├── migrated/                # empty; the skill fills this in Phase 2
├── TEST_PROMPT.md           # copy-paste prompt (preamble + combined + per-resource)
└── EVAL.md                  # results template + fidelity diff script
```

## Risks / open items

- `catalogs` and legacy `models` are best-effort; may fail on privilege / UC-only
  workspace. Flagged, not blocking.
- `quality_monitors` and `dashboards` deploy can be slower but are fine.
- Fidelity diff is a field-level check, not an exact match, by design.
- Genie Code vs. local Claude read resources differently; the prompt preamble bridges this.
