# dabs-migrator

A [Genie Code](https://docs.databricks.com/aws/en/genie-code/skills) skill for Databricks that converts existing workspace assets (jobs, pipelines, dashboards, apps, and more) into a production-ready [Databricks Asset Bundles (DABs)](https://docs.databricks.com/aws/en/dev-tools/bundles/index.html) repository — complete with per-resource YAML, source code, tests, and a CI/CD pipeline for your preferred tool.

## What this skill does

When you invoke it from Genie Code, `dabs-migrator` reads the assets you name from your Databricks workspace and scaffolds a complete DABs project that you can push to Git and deploy through CI/CD. No more copy-pasting YAML or guessing at field names — every resource is generated from the authoritative bundle schema so `databricks bundle validate` passes on the first try.

### Supported assets (30 resource types)

| Asset | CLI version |
|---|---|
| Alerts | v1.5.0 |
| Apps | v1.5.0 |
| Catalogs | v1.5.0 |
| Clusters | v1.5.0 |
| Dashboards (Lakeview) | v1.5.0 |
| Database Catalogs | v1.5.0 |
| Database Instances | v1.5.0 |
| External Locations | v1.5.0 |
| Genie Spaces | v1.5.0 |
| Jobs | v1.5.0 |
| MLflow Experiments | v1.5.0 |
| MLflow Models (legacy) | v1.5.0 |
| Model Serving Endpoints | v1.5.0 |
| Pipelines (SDP/DLT) | v1.5.0 |
| Postgres Branches | v1.5.0 |
| Postgres Catalogs | v1.5.0 |
| Postgres Databases | v1.5.0 |
| Postgres Endpoints | v1.5.0 |
| Postgres Projects | v1.5.0 |
| Postgres Roles | v1.5.0 |
| Postgres Synced Tables | v1.5.0 |
| Quality Monitors | v1.5.0 |
| Registered Models (Unity Catalog) | v1.5.0 |
| Schemas | v1.5.0 |
| Secret Scopes | v1.5.0 |
| SQL Warehouses | v1.5.0 |
| Synced Database Tables | v1.5.0 |
| Vector Search Endpoints | v1.5.0 |
| Vector Search Indexes | v1.5.0 |
| Volumes | v1.5.0 |

### Supported CI/CD tools

| Tool | Default |
|---|---|
| GitHub Actions | Yes |
| Azure DevOps Pipelines | |
| GitLab CI | |
| Bitbucket Pipelines | |
| Jenkins | |
| CircleCI | |

## Two modes of operation

### Start fresh

You have assets in the Databricks UI and want to migrate them into a brand-new DABs repository. Genie will:

1. Create the project folder structure.
2. Generate `databricks.yml` with dev/staging/prod targets.
3. Write one YAML file per resource under `resources/<type>/<name>.yml`.
4. Clone the original source code (notebooks, SQL scripts) verbatim into `src/<name>/`.
5. Emit CI/CD pipeline files for your chosen tool.
6. Add `requirements.txt`, `.gitignore`, test stubs, and a `README.md`.

### Add to an existing project (incremental)

Your DABs repository already exists and you want to bring in one or more additional assets without touching what's already there. Genie detects that `databricks.yml` is present and switches to incremental mode:

- Only the new resource YAML and source files are created.
- `databricks.yml`, CI/CD pipelines, and all existing files are left untouched.
- If a resource file for the requested asset already exists, the skill reports a conflict and stops — it will never overwrite.

Example: you migrated `job_1` and `warehouse_1` last week. Today you want to add `alert_1`. Just name the new asset and Genie adds `resources/alerts/alert_1.yml` and `tests/test_alert_1.py` — nothing else changes.

## How to invoke

From Genie Code in your Databricks workspace, describe what you want to migrate:

```
Migrate @my_job and @my_pipeline to DABs using GitHub Actions
```

```
Add @my_alert to the project
```

Genie will ask for anything missing (project name, CI/CD tool, target environments) and then generate the full project or the incremental addition.

## Key design decisions

- **Schema-accurate YAML** — every resource file is built from the live `databricks bundle schema` output, not hand-written examples. All field names, types, and required/optional flags are correct.
- **Verbatim source migration** — original notebooks and scripts are cloned as-is. No `# TODO` placeholders or stub logic that would silently break production.
- **No hardcoded values** — workspace hosts, cluster IDs, warehouse IDs, and catalog names are always bundle variables (`${var.*}`), overridden per target.
- **One resource per file** — `resources/<type>/<name>.yml` contains exactly one asset definition.
- **CI-only prod deploys** — the generated pipelines enforce that production deployments go through CI, never from a dev machine.

## Changelog summary

| Date | Change |
|---|---|
| 2026-06-30 | Upgraded schema reference to Databricks CLI v1.5.0; added 7 new resource types (Genie Spaces, Postgres Catalogs/Databases/Roles/Synced Tables, Vector Search Endpoints/Indexes) and refreshed all 23 existing resource schemas |
| 2026-05-06 | Incremental mode added — safely add resources to an existing project without regenerating the whole repo |
| 2026-05-06 | Old hand-written skeletons removed; workflow now maps actual asset attributes against the live schema reference |
| 2026-05-06 | Complete schema reference added to all 23 resource files (derived from `databricks bundle schema`) |
| 2026-05-03 | Pipeline library entry kind rule: `.py` → `notebook:`, `.sql` → `file:` |
| 2026-05-03 | Clone-verbatim rule enforced for migrated source files — stubs banned unless starting from scratch |
| 2026-05-03 | Pipeline `target:` field deprecated in favour of `schema:` (SDP nomenclature) |
| 2026-05-03 | Path fix: resource YAMLs use `../../src/` (two levels up), not `../src/` |
| 2026-04-29 | Initial skill scaffold |

Full history in [CHANGELOG.md](CHANGELOG.md).
