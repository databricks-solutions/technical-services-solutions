# Genie Space CI/CD

Automated CI/CD pipeline for Databricks AI/BI Genie spaces. Export from a source workspace, version control in Git, and deploy to a target workspace with automatic catalog/schema replacement.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [File Structure](#file-structure)
- [Quick Start](#quick-start)
- [Workflow Modes](#workflow-modes)
- [Catalog/Schema Replacement](#catalogschema-replacement)
- [Parameters Reference](#parameters-reference)
- [Prerequisites](#prerequisites)
- [Troubleshooting](#troubleshooting)
- [API Reference](#api-reference)
- [Additional Documentation](#additional-documentation)

---

## Overview

This project provides a complete CI/CD solution for managing Databricks AI/BI Genie spaces across environments. It enables teams to:

- **Export** Genie space configurations from a source workspace
- **Version control** configurations in Git for audit trails and collaboration
- **Deploy** to a target workspace with automatic Unity Catalog reference replacement
- **Maintain** consistency between Dev and Prod environments

### Key Features

- **Cross-workspace support** - Export from one workspace, deploy to another
- **Single job with conditional branching** - One `promote_genie` job controlled by `run_mode`
- **Profile-based authentication** - No hardcoded workspace URLs
- **Serverless compute by default** - Faster startup, no cluster management
- Automatic catalog/schema replacement during deployment
- Support for both backtick-quoted and plain Unity Catalog identifiers
- Create new or update existing Genie spaces
- Configurable via Databricks Asset Bundles (DABs)
- CI/CD ready for integration with GitHub Actions, Azure DevOps, etc.

---

## Architecture

```
┌────────────────────────┐      ┌────────────────────────┐      ┌────────────────────────┐
│  Source Workspace       │      │   Git / CI/CD          │      │  Target Workspace      │
│                        │      │                        │      │                        │
│  Genie Space           │      │  genie_space_dev.json  │      │  Genie Space           │
│  (source_catalog)      ├──►───┤  (version controlled)  ├──►───┤  (target_catalog)      │
│                        │      │                        │      │                        │
│  --target dev          │      │  bundle deploy syncs   │      │  --target prod         │
│  run_mode=export_only  │      │  the file to workspace │      │  run_mode=deploy_only  │
└────────────────────────┘      └────────────────────────┘      └────────────────────────┘
```

### Pipeline Flow

**Job: `promote_genie`**

The job uses `condition_task` gates to run the right tasks based on `run_mode`:

```
Export branch:  check_export ──(true)──> export_genie_space
Deploy branch:  check_deploy ──(true)──> deploy_genie_space
```

| run_mode | Export | Deploy | Use Case |
|----------|--------|--------|----------|
| `export_only` | Runs | Skipped | Export from source workspace |
| `deploy_only` | Skipped | Runs | Deploy to target workspace |
| `export_and_deploy` | Runs | Runs | Same-workspace round-trip |

---

## File Structure

```
genie-cicd/
├── databricks.yml.template                     # DAB template (copy and customize)
├── databricks.yml                              # Your local config (git-ignored)
├── README.md                                   # This file
├── src/
│   ├── export_genie_definition.ipynb           # Export notebook
│   └── deploy_genie_space.ipynb                # Deploy notebook
└── genie_definition/
    └── genie_space_dev.json                    # Exported from source (version controlled)
```

### Key Files

| File | Purpose |
|------|---------|
| `databricks.yml.template` | Template configuration - copy this to get started |
| `databricks.yml` | Your local configuration with real values (do not commit secrets) |
| `src/export_genie_definition.ipynb` | Databricks notebook to export Genie space definitions |
| `src/deploy_genie_space.ipynb` | Databricks notebook to deploy with catalog/schema replacement |
| `genie_definition/*.json` | Exported space definitions (keep in version control) |

---

## Quick Start

### 1. Install Prerequisites

```bash
# Install Databricks CLI (v0.200+)
curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh

# Set up CLI profiles for each workspace
databricks configure --profile dev-profile
# Enter: Dev workspace URL + authentication

databricks configure --profile prod-profile
# Enter: Prod workspace URL + authentication
```

### 2. Configure `databricks.yml`

```bash
cp databricks.yml.template databricks.yml
```

Edit `databricks.yml` and fill in the target-specific variables:

**Dev target** (source workspace):

| Variable | Description | Where to Find |
|----------|-------------|---------------|
| `source_space_id` | Genie Space ID to export | URL: `/genie/rooms/<SPACE_ID>` |
| `source_catalog` | Dev catalog name | Unity Catalog explorer |
| `source_schema` | Dev schema name | Unity Catalog explorer |

**Prod target** (target workspace):

| Variable | Description | Where to Find |
|----------|-------------|---------------|
| `target_space_id` | Prod Space ID (empty for first run) | Set after first deployment |
| `warehouse_id` | SQL Warehouse ID | URL: `/sql/warehouses/<ID>` |
| `genie_space_title` | Display name for the space | Your choice |
| `target_catalog` | Prod catalog name | Unity Catalog explorer |
| `target_schema` | Prod schema name | Unity Catalog explorer |

### 3. Export from Source Workspace

```bash
databricks bundle validate --target dev
databricks bundle deploy --target dev
databricks bundle run promote_genie --target dev
```

### 4. Sync Export to Local

```bash
databricks workspace export \
  "/Workspace/Users/<you>/.bundle/genie-space-cicd/dev/files/genie_definition/genie_space_dev.json" \
  --file genie_definition/genie_space_dev.json
```

### 5. Deploy to Target Workspace

```bash
databricks bundle validate --target prod
databricks bundle deploy --target prod
databricks bundle run promote_genie --target prod
```

### 6. Save the Prod Space ID

On first deployment, the job creates a new Genie space and outputs the `space_id`. Save it in your `databricks.yml` so future runs update instead of re-creating:

```yaml
  prod:
    variables:
      target_space_id: "<SPACE_ID_FROM_OUTPUT>"
```

### 7. Ongoing Workflow

```bash
# 1. Re-export after changes to dev Genie space
databricks bundle deploy --target dev
databricks bundle run promote_genie --target dev

# 2. Sync the exported file back to your local repo
databricks workspace export \
  "/Workspace/Users/<you>/.bundle/genie-space-cicd/dev/files/genie_definition/genie_space_dev.json" \
  --file genie_definition/genie_space_dev.json

# 3. Commit the updated export (creates audit trail in Git)
git add genie_definition/genie_space_dev.json
git commit -m "Update Genie space export"
git push

# 4. Redeploy to prod (picks up the new export)
databricks bundle deploy --target prod
databricks bundle run promote_genie --target prod
```

> **Note**: The export writes to the workspace filesystem. You must sync the file
> back to your local repo (step 2) before deploying to prod, otherwise prod
> deploys the old version. If using the GitHub Actions workflow, pushing
> `genie_space_dev.json` to main triggers the prod deploy automatically.

---

## Workflow Modes

The `run_mode` variable controls which tasks execute. Each target sets its own default, but you can override it at runtime with `-p run_mode=<value>`.

### All Available Run Options

| Command | run_mode | Export | Deploy | Use Case |
|---------|----------|--------|--------|----------|
| `databricks bundle run promote_genie --target dev` | `export_only` (default) | Runs | Skipped | Export Genie space from dev workspace |
| `databricks bundle run promote_genie --target dev -p run_mode=deploy_only` | `deploy_only` | Skipped | Runs | Deploy to dev workspace (testing) |
| `databricks bundle run promote_genie --target dev -p run_mode=export_and_deploy` | `export_and_deploy` | Runs | Runs | Full round-trip in dev workspace |
| `databricks bundle run promote_genie --target prod` | `deploy_only` (default) | Skipped | Runs | Deploy to prod workspace |
| `databricks bundle run promote_genie --target prod -p run_mode=export_only` | `export_only` | Runs | Skipped | Export from prod workspace (backup) |
| `databricks bundle run promote_genie --target prod -p run_mode=export_and_deploy` | `export_and_deploy` | Runs | Runs | Full round-trip in prod workspace |

### Typical Cross-Workspace Workflow

```bash
# Step 1: Export from dev
databricks bundle deploy --target dev
databricks bundle run promote_genie --target dev

# Step 2: Sync exported file from workspace to local repo
databricks workspace export \
  "/Workspace/Users/<you>/.bundle/genie-space-cicd/dev/files/genie_definition/genie_space_dev.json" \
  --file genie_definition/genie_space_dev.json

# Step 3: Deploy to prod
databricks bundle deploy --target prod
databricks bundle run promote_genie --target prod
```

### How Conditional Branching Works

The job uses Databricks `condition_task` to gate each branch:

- **check_export**: Evaluates `run_mode != "deploy_only"`. If true, `export_genie_space` runs.
- **check_deploy**: Evaluates `run_mode != "export_only"`. If true, `deploy_genie_space` runs.

Both branches are independent, so in `export_and_deploy` mode they run in parallel. The deploy task reads the file uploaded during `databricks bundle deploy`.

---

## Catalog/Schema Replacement

The pipeline automatically replaces Unity Catalog references when deploying, ensuring your source configurations work seamlessly in the target environment.

### Supported Formats

| Format | Example | Replaced With |
|--------|---------|---------------|
| Plain | `my_catalog.my_schema.table_example` | `prod_catalog.prod_schema.table_example` |
| Backtick-quoted | `` `my_catalog`.`my_schema`.`table_example` `` | `` `prod_catalog`.`prod_schema`.`table_example` `` |

### What Gets Replaced

| JSON Path | Description |
|-----------|-------------|
| `data_sources.tables[].identifier` | Table references |
| `data_sources.metric_views[].identifier` | Metric view references |
| `instructions.example_question_sqls[].sql[]` | Example SQL queries |
| `benchmarks.questions[].answer[].content[]` | Benchmark answer SQL |

---

## Parameters Reference

### Export Task (`export_genie_definition.ipynb`)

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `space_id` | Yes | - | Genie Space ID to export |
| `output_file` | Yes | `../genie_definition/genie_space_dev.json` | Path to save the exported JSON |

### Deploy Task (`deploy_genie_space.ipynb`)

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `space_id` | No | `""` | Target Space ID. Empty = create new, filled = update existing |
| `input_file` | Yes | `../genie_definition/genie_space_dev.json` | Path to the source JSON file |
| `output_file` | No | Auto-generated `_prod` suffix | Path for the transformed JSON backup |
| `warehouse_id` | Yes* | - | SQL Warehouse ID (*required for create) |
| `title` | Yes* | - | Space title (*required for create) |
| `source_catalog` | No | - | Source catalog to replace |
| `target_catalog` | No | - | Target catalog |
| `source_schema` | No | - | Source schema to replace |
| `target_schema` | No | - | Target schema |

---

## Compute Options

By default, jobs run on **serverless compute** which provides:
- Faster startup times (no cluster provisioning)
- No cluster management overhead
- Cost-effective for short-running tasks

### Alternative Compute Options

If serverless is not available, uncomment the appropriate section in `databricks.yml.template`:

| Option | Use Case | Configuration |
|--------|----------|---------------|
| **Serverless** (default) | Recommended for most use cases | No cluster config needed |
| **Existing Cluster** | Reuse an all-purpose cluster | `existing_cluster_id: "<ID>"` |
| **New Job Cluster** | Dedicated compute per job | `new_cluster: { ... }` |

---

## Prerequisites

### Software Requirements

- **Databricks CLI** v0.200+ installed and configured
- **Python 3.8+** (for local development/testing)

### Permissions

| Operation | Required Permission | Scope |
|-----------|---------------------|-------|
| Export | `CAN EDIT` | Source Genie Space |
| Create Space | `CAN MANAGE` | Target workspace |
| Update Space | `CAN EDIT` | Target Genie Space |

### Infrastructure

- **Serverless compute** enabled in the workspace (for default configuration)
- **SQL Warehouse** running in target workspace
- **Unity Catalog** configured in both workspaces
- **Network connectivity** between workspaces (if different)

---

## Troubleshooting

| Error | Cause | Solution |
|-------|-------|----------|
| `space_id parameter is required` | Export task missing space ID | Set `source_space_id` in `databricks.yml` |
| `warehouse_id is required` | Creating new space without warehouse | Set `warehouse_id` in `databricks.yml` |
| `title is required` | Creating new space without title | Set `genie_space_title` in `databricks.yml` |
| `Permission denied` | Insufficient access | Check permissions (see Prerequisites) |
| `Space not found` | Invalid space ID | Verify space ID exists and is accessible |
| `token refresh: invalid_request` | Expired authentication | Re-run `databricks auth login --host <URL>` |
| `EXCLUDED` tasks on prod | Old `run_if` syntax | Ensure you are using `condition_task` gates (see template) |

### Debugging Commands

```bash
# Validate configuration
databricks bundle validate --target dev
databricks bundle validate --target prod

# Check job status after a run
databricks jobs get-run <RUN_ID>

# Re-authenticate
databricks auth login --host https://your-workspace.cloud.databricks.com
```

---

## CI/CD with GitHub Actions

A workflow is included at `/.github/workflows/deploy-genie-to-prod.yml` that automatically deploys to prod when `genie_space_dev.json` changes on `main`.

### Setup

1. Go to your GitHub repo > **Settings** > **Secrets and variables** > **Actions**

2. Add one **Secret**:

   | Secret | Value |
   |--------|-------|
   | `DATABRICKS_TOKEN` | Prod workspace PAT or OAuth token |

3. Add these **Variables** (non-sensitive):

   | Variable | Value |
   |----------|-------|
   | `DATABRICKS_HOST` | Prod workspace URL |
   | `PROD_ROOT_PATH` | Bundle root path (e.g. `/Workspace/Users/you@company.com/.bundle/genie-space-cicd/prod`) |
   | `PROD_TARGET_SPACE_ID` | Prod Genie Space ID (empty string for first run) |
   | `PROD_WAREHOUSE_ID` | Prod SQL Warehouse ID |
   | `PROD_GENIE_TITLE` | Display title for the prod space |
   | `SOURCE_CATALOG` | Source catalog name (for replacement) |
   | `SOURCE_SCHEMA` | Source schema name (for replacement) |
   | `PROD_TARGET_CATALOG` | Prod catalog name |
   | `PROD_TARGET_SCHEMA` | Prod schema name |

### Automated Flow

```
Edit Dev Genie Space (UI)
       │
       ▼  export + sync locally
git push genie_space_dev.json to main
       │
       ▼  GitHub Actions triggers
Validate → Deploy → Run promote_genie --target prod
       │
       ▼
Prod Genie Space updated
```

After the first deployment, update the `PROD_TARGET_SPACE_ID` variable with the space ID from the workflow output.

The workflow can also be triggered manually from the **Actions** tab.

---

## API Reference

This project uses the Databricks Genie Space REST APIs:

| Operation | API | Documentation |
|-----------|-----|---------------|
| Export | GET `/api/2.0/genie/spaces/{space_id}` | [Get Space API](https://docs.databricks.com/api/workspace/genie/getspace) |
| Create | POST `/api/2.0/genie/spaces` | [Create Space API](https://docs.databricks.com/api/workspace/genie/createspace) |
| Update | PATCH `/api/2.0/genie/spaces/{space_id}` | [Update Space API](https://docs.databricks.com/api/workspace/genie/updatespace) |

---

## License

This project is provided as-is for educational and internal use purposes.
