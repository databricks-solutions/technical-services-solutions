---
name: dabs-migrator
description: Use to scaffold a Databricks Asset Bundle (DABs) project from existing workspace assets. Trigger when the user says "migrate to DABs", "generate a DAB", "convert my job/pipeline to a bundle", or names Databricks resources (jobs, pipelines, dashboards, etc.) and asks for project code. Produces a complete repo — databricks.yml, resources/*.yml per asset, src/ stubs, tests/, requirements.txt, and CI/CD pipeline files for the user's chosen tool (GitHub Actions by default; Azure DevOps, GitLab CI, Bitbucket, Jenkins, CircleCI also supported).
---

# DABs Migrator

Generates a Databricks Asset Bundle project from a list of Databricks resource names. Outputs a ready-to-deploy repo following the conventions in the canonical DABs example projects ([sts-dabs-demo](https://github.com/databricks-solutions/databricks-dab-examples/tree/main/sts-dabs-demo), [flights-simple](https://github.com/databricks-solutions/databricks-dab-examples/tree/main/flights/flights-simple), [flights-advanced](https://github.com/databricks-solutions/databricks-dab-examples/tree/main/flights/flights-advanced)).

## When to invoke this skill

The user wants to bootstrap a DABs project. They will typically:
- name one or more existing Databricks assets (e.g. `@my_job_1`, `@my_pipeline_1`)
- optionally name a CI/CD tool (GitHub Actions, Azure DevOps, GitLab CI, Bitbucket Pipelines, Jenkins, CircleCI)
- optionally name target environments (dev/staging/prod)

If any of these are missing, ask once before generating; default to GitHub Actions and `dev`/`staging`/`prod` if the user is happy with defaults.

## Inputs

| Input | Required | Default | Notes |
|---|---|---|---|
| Project name | yes | — | becomes `bundle.name` and the root folder |
| List of resources | yes | — | each item is `<resource_type>:<resource_name>` e.g. `job:my_job_1`. Supported types listed in `resources/` — see the [official supported-resources table](https://docs.databricks.com/aws/en/dev-tools/bundles/resources#supported-resources) |
| CI/CD tool | no | `github-actions` | one of: `github-actions`, `azure-devops`, `gitlab-ci`, `bitbucket`, `jenkins`, `circleci`. See `cicd/` |
| Targets | no | `dev`, `staging`, `prod` | bundle deployment environments |
| Workspace host(s) | no | `${var.workspace_host}` placeholder | one per target, can be filled in later |

## Output: project layout

```
<project_name>/
├── .github/workflows/                  # or .azure-pipelines/, .gitlab-ci.yml, etc.
│   ├── deploy_to_staging.yml
│   ├── deploy_to_prod.yml
│   └── pr_validate.yml
├── resources/
│   ├── jobs/<job_name>.yml             # one file per job resource
│   ├── pipelines/<pipeline_name>.yml   # one file per pipeline resource
│   └── <other_type>/<name>.yml         # see resources/ reference
├── src/
│   ├── <job_name>/                     # stubs matching the resource key
│   │   └── notebook.py
│   └── <pipeline_name>/
│       ├── bronze.py
│       ├── silver.py
│       └── gold.py
├── tests/
│   └── test_unity_catalog.py           # single pytest file for Unity Catalog validation
├── databricks.yml                      # bundle entrypoint
├── requirements.txt                    # local dev deps
├── .gitignore
└── README.md
```

## Workflow

1. **Parse inputs.** Extract project name, the `<type>:<name>` resource list, and CI/CD tool. Confirm any missing required fields before proceeding.
2. **Detect mode — fresh start vs. incremental.** Check whether `databricks.yml` already exists in the target project folder.
   - **Fresh start** (file absent): proceed through all steps below.
   - **Incremental** (file present): the project already exists. Skip steps 3, 5, and 6. Go directly to step 4 for the new resources only. Never overwrite existing files — if a resource file for the named asset already exists, report a conflict and stop for that asset.
3. **Create root folder** named after the project and **generate `databricks.yml`** from `templates/databricks.yml.tmpl` — fills in `bundle.name`, `include:` globs, and `targets` (dev/staging/prod with `${var.workspace_host}` placeholder per target). *(Fresh start only.)*
4. **For each resource** in the input list, open `resources/<type>.md` and use its `## Complete schema reference` as the authoritative field catalogue. Build `resources/<type_plural>/<name>.yml` by mapping the asset's **actual existing attributes** onto the schema — include only the fields the asset uses, using the correct field names and types from the schema. Do not copy the complete schema verbatim and do not invent placeholder values for fields the asset does not have. If the resource type owns source code (jobs, pipelines, apps, dashboards), also populate `src/<name>/`:
   - **If migrating an existing asset** (the default case — the user named a real workspace asset): pull the original notebook(s) / script(s) and copy their content **verbatim** into `src/<name>/`. Preserve filenames, structure, comments, and logic exactly. Do **not** add headers like `# Originally sourced from: <path>` or replace any block with `# TODO: Replace with actual ingestion logic`. See the corresponding hard rule below.
   - **If starting from scratch** (only when the user explicitly says so): create minimal stub files and populate only the required fields (marked `REQUIRED` in the schema reference).
5. **Generate CI/CD files** from the user's chosen tool's reference under `cicd/<tool>.md`. Always emit at least: PR validation pipeline, staging deploy pipeline, prod deploy pipeline. All pipelines must follow the **CI/CD action contract** below. *(Fresh start only.)*
6. **Write supporting files**: `requirements.txt` (databricks-cli, pytest, ruff baseline), `.gitignore` (Python + DABs `.databricks/`), `tests/test_unity_catalog.py` (copied from `templates/test_unity_catalog.py`), and a minimal `README.md` documenting how to deploy. *(Fresh start only.)*
7. **Report** what was generated: tree of created/modified files. In incremental mode, explicitly list which files were added and confirm that no existing files were touched.

## CI/CD action contract

Every generated CI/CD pipeline (regardless of tool) must:

1. **Install the Databricks CLI** — use the official installer/action for the tool (see `cicd/<tool>.md`).
2. **Run `databricks bundle validate --output json`** — fail the pipeline on non-zero exit. The JSON output should be uploaded as a build artifact when the tool supports it.
3. **Run `databricks bundle deploy`** — only on the deploy pipelines, not on PR validation. The target is inferred from the `DATABRICKS_BUNDLE_ENV` environment variable (never use `-t`).

Every step must also set `BUNDLE_VAR_catalog` and `BUNDLE_VAR_schema` (sourced from CI/CD variables named `catalog` and `schema`) so the CLI resolves the bundle variables defined in `databricks.yml`.

PR validation runs steps 1–2 only with `DATABRICKS_BUNDLE_ENV=staging`. Staging deploys run 1–3 with `DATABRICKS_BUNDLE_ENV=staging`. Prod deploys run 1–3 with `DATABRICKS_BUNDLE_ENV=prod` and require manual approval / protected environment gating.

Reference: [Databricks bundle jobs tutorial](https://docs.databricks.com/aws/en/dev-tools/bundles/jobs-tutorial).

## Hard rules — never do

- **Never** generate, recommend, or run any `databricks repos` command. Bundle deploys do not need or use the Repos API; mixing them creates dual sources of truth. If the user asks for Git sync via Repos, refuse and point them at bundle deploys instead.
- **Never** commit secrets, workspace tokens, or service principal credentials into generated YAML or workflow files. Use the CI tool's secret store (`${{ secrets.* }}` for GitHub, variable groups for Azure DevOps, etc.) and Databricks secret scopes (`{{secrets/scope/key}}`) for runtime.
- **Never** hardcode workspace hosts, cluster IDs, warehouse IDs, or catalog names in resource YAML. Use bundle variables (`${var.catalog}`, `${var.schema}`, etc.) and override per target.
- **Never** put more than one resource definition per YAML file in `resources/`. One asset, one file.
- **Never** deploy to `prod` from a dev machine. Prod deploys go through CI only.
- **Never** use `../src/...` in resource YAML paths. Resource files live at `resources/<type>/<name>.yml` (two levels under the bundle root), so paths to `src/` must be `../../src/<name>/...`. Using a single `..` resolves to `resources/src/...` and the deploy fails.
- **Never** mismatch the library entry kind to the source extension in a `pipelines` resource's `libraries:` block. Spark Declarative Pipelines (SDP) require `notebook:` for `.py` sources and `file:` for `.sql` sources. Mismatch produces `Error: expected a file for "resources.pipelines.<name>.libraries[0].file.path"` (or the symmetric notebook variant).
- **Never** use `target:` on new pipelines. SDP uses `schema:` — `target` is the legacy DLT field and is deprecated.
- **Never** replace migrated source files with placeholder, stub, sample, or "blueprint" code. When migrating an existing Databricks asset (job, pipeline, app, dashboard, or any resource that owns code), clone the original notebook/script/file content **verbatim** into `src/<name>/`. Do not insert `# TODO: Replace with actual ingestion logic...`, `# Originally sourced from: <path>` headers, or simplified example code. The user's working logic must survive the migration intact — anything else silently breaks production behavior. Only generate stub files when the user explicitly states they are starting from scratch (no original asset to migrate).

## Supported resource types

One reference doc per resource type lives under `resources/`. Read the relevant file when generating the YAML for that resource. Full list (from the [Databricks supported-resources table](https://docs.databricks.com/aws/en/dev-tools/bundles/resources#supported-resources)):

| YAML key | Reference file |
|---|---|
| `alerts` | [resources/alerts.md](resources/alerts.md) |
| `apps` | [resources/apps.md](resources/apps.md) |
| `catalogs` | [resources/catalogs.md](resources/catalogs.md) |
| `clusters` | [resources/clusters.md](resources/clusters.md) |
| `dashboards` | [resources/dashboards.md](resources/dashboards.md) |
| `database_catalogs` | [resources/database_catalogs.md](resources/database_catalogs.md) |
| `database_instances` | [resources/database_instances.md](resources/database_instances.md) |
| `experiments` | [resources/experiments.md](resources/experiments.md) |
| `external_locations` | [resources/external_locations.md](resources/external_locations.md) |
| `jobs` | [resources/jobs.md](resources/jobs.md) |
| `models` | [resources/models.md](resources/models.md) |
| `model_serving_endpoints` | [resources/model_serving_endpoints.md](resources/model_serving_endpoints.md) |
| `pipelines` | [resources/pipelines.md](resources/pipelines.md) |
| `postgres_branches` | [resources/postgres_branches.md](resources/postgres_branches.md) |
| `postgres_endpoints` | [resources/postgres_endpoints.md](resources/postgres_endpoints.md) |
| `postgres_projects` | [resources/postgres_projects.md](resources/postgres_projects.md) |
| `quality_monitors` | [resources/quality_monitors.md](resources/quality_monitors.md) |
| `registered_models` | [resources/registered_models.md](resources/registered_models.md) |
| `schemas` | [resources/schemas.md](resources/schemas.md) |
| `secret_scopes` | [resources/secret_scopes.md](resources/secret_scopes.md) |
| `sql_warehouses` | [resources/sql_warehouses.md](resources/sql_warehouses.md) |
| `synced_database_tables` | [resources/synced_database_tables.md](resources/synced_database_tables.md) |
| `volumes` | [resources/volumes.md](resources/volumes.md) |

## CI/CD tools

| Tool | Reference |
|---|---|
| GitHub Actions (default) | [cicd/github-actions.md](cicd/github-actions.md) |
| Azure DevOps Pipelines | [cicd/azure-devops.md](cicd/azure-devops.md) |
| GitLab CI | [cicd/gitlab-ci.md](cicd/gitlab-ci.md) |
| Bitbucket Pipelines | [cicd/bitbucket.md](cicd/bitbucket.md) |
| Jenkins | [cicd/jenkins.md](cicd/jenkins.md) |
| CircleCI | [cicd/circleci.md](cicd/circleci.md) |

## Templates

- [templates/databricks.yml.tmpl](templates/databricks.yml.tmpl) — bundle root entrypoint
- [templates/gitignore.tmpl](templates/gitignore.tmpl) — `.gitignore`
- [templates/requirements.txt.tmpl](templates/requirements.txt.tmpl) — local dev dependencies
- [templates/README.md.tmpl](templates/README.md.tmpl) — generated project README

## Example interactions

### Fresh start

**User:** "I want to migrate @my_job_1 and @my_pipeline_1 to DABs, generate the project and for the CI/CD tool use GitHub Actions."

**Output:** create the tree at the top of this file, with:
- `resources/jobs/my_job_1.yml` from `resources/jobs.md` following the complete schema available fields.
- `resources/pipelines/my_pipeline_1.yml` from `resources/pipelines.md` following the complete schema available fields.
- `src/my_job_1/notebook.py` and `src/my_pipeline_1/{bronze,silver,gold}.py` stubs
- `.github/workflows/{deploy_to_staging,deploy_to_prod,pr_validate}.yml` from `cicd/github-actions.md`
- `databricks.yml`, `requirements.txt`, `.gitignore`, `README.md`, `tests/test_unity_catalog.py`

Report the tree back and list TODOs (workspace host, CI auth secrets, fill in actual notebook logic).

### Incremental (project already exists)

**User:** "Add @my_alert_1 to the project."

**Output:** detect that `databricks.yml` already exists, enter incremental mode, and only create:
- `resources/alerts/my_alert_1.yml` (using the asset's actual attributes mapped against `resources/alerts.md`)

All existing files — `databricks.yml`, CI/CD workflows, other resource YAMLs, `src/` directories, `tests/` — are left untouched. Report only the newly added files.
