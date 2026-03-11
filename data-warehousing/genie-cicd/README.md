# Genie Space CI/CD

Automated CI/CD pipeline for Databricks AI/BI Genie spaces. Export from Dev, version control in Git, and deploy to Prod with automatic catalog/schema replacement.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [File Structure](#file-structure)
- [Quick Start](#quick-start)
- [Jobs Available](#jobs-available)
- [Catalog/Schema Replacement](#catalogschema-replacement)
- [Parameters Reference](#parameters-reference)
- [Prerequisites](#prerequisites)
- [Troubleshooting](#troubleshooting)
- [API Reference](#api-reference)
- [Additional Documentation](#additional-documentation)

---

## Overview

This project provides a complete CI/CD solution for managing Databricks AI/BI Genie spaces across environments. It enables teams to:

- **Export** Genie space configurations from Development workspaces
- **Version control** configurations in Git for audit trails and collaboration
- **Deploy** to Production with automatic Unity Catalog reference replacement
- **Maintain** consistency between Dev and Prod environments

### Key Features

- **Serverless compute by default** - Jobs run on serverless for faster startup and no cluster management
- Automatic catalog/schema replacement during deployment
- Support for both backtick-quoted and plain Unity Catalog identifiers
- Create new or update existing Genie spaces
- Configurable via Databricks Asset Bundles (DABs)
- CI/CD ready for integration with GitHub Actions, Azure DevOps, etc.

---

## Architecture

```
┌────────────────────────┐      ┌────────────────────────┐      ┌────────────────────────┐
│  Dev Workspace         │      │   Git / CI/CD          │      │  Prod Workspace        │
│                        │      │                        │      │                        │
│  Genie Space ──Task1   ┼──►───│  genie_space_dev.json. │──►───┼  Task2─► Genie Space   │
│  (source catalog)      │      │                        │      │  (target catalog)      │
└────────────────────────┘      └────────────────────────┘      └────────────────────────┘
```

### Pipeline Flow

**Job: `promote_genie_to_prod`**

| Task | Description | Input | Output |
|------|-------------|-------|--------|
| **Task 1** (Export) | Export Genie space from Dev | Dev Space ID | `genie_definition/genie_space.json` |
| **Task 2** (Deploy) | Deploy to Prod with replacements | JSON file | New/Updated Prod Genie Space |

---

## File Structure

```
genie-cicd/
├── databricks.yml                              # DAB configuration (customize this!)
├── SETUP.md                                    # Step-by-step setup guide
├── README.md                                   # This file
├── .gitignore                                  # Git ignore patterns
├── src/
│   ├── export_genie_definition.py              # Task 1: Export from Dev
│   ├── deploy_genie_space.py                   # Task 2: Deploy to Prod
│   └── DOCUMENTATION.md                        # Detailed source code documentation
└── genie_definition/
    ├── genie_space.json                        # Exported from Dev (version controlled)
    └── genie_space_prod.json                   # Generated for Prod (auto-created)
```

### Key Files

| File | Purpose |
|------|---------|
| `databricks.yml` | Main configuration file - define variables, jobs, and targets |
| `src/export_genie_definition.py` | Databricks notebook to export Genie space definitions |
| `src/deploy_genie_space.py` | Databricks notebook to deploy with catalog/schema replacement |
| `genie_definition/*.json` | Exported space definitions (keep in version control) |

---

## Quick Start

> **Detailed instructions**: See [SETUP.md](./SETUP.md) for comprehensive step-by-step guide.

### 1. Install Prerequisites

```bash
# Install Databricks CLI
pip install databricks-cli

# Configure authentication
databricks configure --token
```

### 2. Configure `databricks.yml`

Find and update all `# <-- TODO` comments:

```bash
grep -n "TODO" databricks.yml
```

**Required variables:**

| Variable | Description | Example |
|----------|-------------|---------|
| `dev_space_id` | Your Dev Genie Space ID (source to export) | `01f0fd2cfa1c16c185ec2ee3b4ea29d7` |
| `prod_space_id` | Your Prod Space ID (empty for first run) | `""` or Space ID |
| `prod_warehouse_id` | Prod SQL Warehouse ID | `81b975e2ee32b916` |
| `source_catalog` | Dev catalog name | `main_th` |
| `source_schema` | Dev schema name | `schema_dev` |
| `target_catalog` | Prod catalog name | `main_prod` |
| `target_schema` | Prod schema name | `schema_prod` |
| Workspace URLs | Dev and Prod workspace URLs | `https://xxx.cloud.databricks.com` |

### 3. Deploy

```bash
# Validate configuration
databricks bundle validate --target prod

# Deploy bundle (first time)
databricks bundle deploy --target prod

# Run the pipeline
databricks bundle run promote_genie_to_prod --target prod

# ⚠️ IMPORTANT: Save the prod space_id from output, add to databricks.yml

# Subsequent runs (updates existing Prod space)
databricks bundle run promote_genie_to_prod --target prod
```

---

## Jobs Available

| Job | Description | Use Case |
|-----|-------------|----------|
| `promote_genie_to_prod` | Full pipeline: Export from Dev → Deploy to Prod | Regular deployments |
| `deploy_genie_only` | Deploy only: Uses existing `genie_space.json` (skip export) | Quick deploys without re-export |

### Run Commands

```bash
# Full pipeline (export + deploy)
databricks bundle run promote_genie_to_prod --target prod

# Deploy only (if you already have the JSON) # it is availbale on the the databricks.yml file
databricks bundle run deploy_genie_only --target prod
```

---

## Catalog/Schema Replacement

The pipeline automatically replaces Unity Catalog references when deploying to Prod, ensuring your Dev configurations work seamlessly in Production.

### How It Works

The deployment script scans the Genie space JSON and replaces all occurrences of your source catalog/schema with the target values.

### Supported Formats

| Format | Example | Replaced With |
|--------|---------|---------------|
| Plain | `main_th.schema_dev.table_example` | `main_prod.schema_prod.table_example` |
| Backtick-quoted | `` `main_th`.`schema_dev`.`table_example` `` | `` `main_prod`.`schema_prod`.`table_example` `` |

### What Gets Replaced

The following JSON paths are scanned and updated:

| JSON Path | Description |
|-----------|-------------|
| `data_sources.tables[].identifier` | Table references |
| `data_sources.metric_views[].identifier` | Metric view references |
| `instructions.example_question_sqls[].sql[]` | Example SQL queries |
| `benchmarks.questions[].answer[].content[]` | Benchmark answer SQL |

---

## Parameters Reference

### Export Task (`export_genie_definition.py`)

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `space_id` | **Yes** | - | Dev Genie Space ID to export |
| `output_file` | Yes | `../genie_definition/genie_space.json` | Path to save the exported JSON |

### Deploy Task (`deploy_genie_space.py`)

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `space_id` | No | `""` (empty) | Prod Space ID. Empty = create new, filled = update existing |
| `input_file` | **Yes** | `./genie_definition/genie_space.json` | Path to the Dev JSON file |
| `output_file` | No | Auto-generated `_prod` suffix | Path for Prod JSON backup |
| `warehouse_id` | **Yes*** | - | SQL Warehouse ID (*required for create) |
| `title` | **Yes*** | - | Space title (*required for create) |
| `source_catalog` | No | - | Dev catalog to replace (enables replacement) |
| `target_catalog` | No | - | Prod catalog |
| `source_schema` | No | - | Dev schema to replace |
| `target_schema` | No | - | Prod schema |

---

## Compute Options

By default, jobs run on **serverless compute** which provides:
- Faster startup times (no cluster provisioning)
- No cluster management overhead
- Cost-effective for short-running tasks
- Automatic scaling

### Alternative Compute Options

If serverless is not available or you need specific configurations, you can use:

| Option | Use Case | Configuration |
|--------|----------|---------------|
| **Serverless** (default) | Recommended for most use cases | No cluster config needed |
| **Existing Cluster** | Reuse an all-purpose cluster | `existing_cluster_id: "<YOUR_CLUSTER_ID>"` |
| **New Job Cluster** | Dedicated compute per job | `new_cluster: { ... }` |

To switch from serverless, uncomment the appropriate section in `databricks.yml`.

---

## Prerequisites

### Software Requirements

- **Databricks CLI** v0.200+ installed and configured
- **Python 3.8+** (for local development/testing)

### Permissions

| Operation | Required Permission | Scope |
|-----------|---------------------|-------|
| Export | `CAN EDIT` | Dev Genie space |
| Create Space | `CAN MANAGE` | Prod workspace |
| Update Space | `CAN EDIT` | Prod Genie space |

### Infrastructure

- **Serverless compute** enabled in the workspace (for default configuration)
- **SQL Warehouse** running in Prod workspace
- **Unity Catalog** configured in both workspaces
- **Network connectivity** between workspaces (if different)

---

## Troubleshooting

| Error | Cause | Solution |
|-------|-------|----------|
| `space_id parameter is required` | Export task missing space ID | Set `dev_space_id` in `databricks.yml` |
| `warehouse_id is required` | Creating new space without warehouse | Set `prod_warehouse_id` in `databricks.yml` |
| `Permission denied` | Insufficient access | Check permissions (see Prerequisites) |
| `Space not found` | Invalid space ID | Verify space ID exists and is accessible |

### Debugging Commands

```bash
# Validate configuration
databricks bundle validate --target prod

# Check job status
databricks bundle run promote_genie_to_prod --target prod
# Watch the job in Databricks UI for detailed logs

# List available jobs
databricks bundle summary --target prod
```

---

## API Reference

This project uses the Databricks Genie Space REST APIs:

| Operation | API | Documentation |
|-----------|-----|---------------|
| Export | GET `/api/2.0/genie/spaces/{space_id}` | [Get Space API](https://docs.databricks.com/api/workspace/genie/getspace) |
| Create | POST `/api/2.0/genie/spaces` | [Create Space API](https://docs.databricks.com/api/workspace/genie/createspace) |
| Update | PATCH `/api/2.0/genie/spaces/{space_id}` | [Update Space API](https://docs.databricks.com/api/workspace/genie/updatespace) |

---

## Additional Documentation

| Document | Description |
|----------|-------------|
| [SETUP.md](./SETUP.md) | Detailed step-by-step setup guide |
| [src/DOCUMENTATION.md](./src/DOCUMENTATION.md) | Source code documentation and API details |
| [CONTRIBUTING.md](./CONTRIBUTING.md) | Guidelines for contributing to this project |

---

## License

This project is provided as-is for educational and internal use purposes.
