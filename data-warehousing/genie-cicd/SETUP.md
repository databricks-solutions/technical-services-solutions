# Setup Guide

Complete step-by-step instructions to configure and run your Genie Space CI/CD pipeline.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Step 1: Configure databricks.yml](#step-1-configure-databricksyml)
- [Step 2: First Deployment](#step-2-first-deployment)
- [Step 3: Subsequent Deployments](#step-3-subsequent-deployments)
- [Available Jobs](#available-jobs)
- [Configuration Examples](#configuration-examples)
- [Troubleshooting](#troubleshooting)
- [Quick Reference](#quick-reference)

---

## Prerequisites

### 1. Install Databricks CLI

Choose your preferred installation method:

```bash
# Option 1: Install using pip (recommended)
pip install databricks-cli

# Option 2: Install using Homebrew (macOS)
brew install databricks-cli

# Option 3: Install using curl (Linux/macOS)
curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh
```

### 2. Verify Installation

```bash
databricks --version
# Expected output: Databricks CLI v0.200.0 or higher
```

### 3. Configure Authentication

You can authenticate using one of these methods:

**Option A: Personal Access Token (PAT)**
```bash
# Interactive configuration
databricks configure --token

# When prompted:
#   Databricks Host: https://your-workspace.cloud.databricks.com
#   Personal Access Token: dapi...your-token...
```

**Option B: Using Environment Variables**
```bash
export DATABRICKS_HOST="https://your-workspace.cloud.databricks.com"
export DATABRICKS_TOKEN="dapi...your-token..."
```

**Option C: Using Databricks CLI Profiles**
```bash
# Configure a named profile
databricks configure --token --profile prod

# Use the profile
databricks bundle deploy --target prod --profile prod
```

### 4. Verify Connection

```bash
databricks workspace list /
# Should list your workspace root directories
```

---

## Step 1: Configure databricks.yml

Open `databricks.yml` and update all values marked with `# <-- TODO`.

### Quick Find: All TODOs

```bash
grep -n "TODO" databricks.yml
```

### Required Configuration Items

Below is a checklist of all items you need to configure:

---

#### 1.1 Dev Space ID (Source)

**What it is**: The ID of your Genie space in the Development workspace that you want to export.

```yaml
variables:
  dev_space_id:
    default: "your-dev-genie-space-id"  # <-- TODO: Add your Dev Space ID
```

**How to find it**:
1. Open your Databricks Dev workspace
2. Navigate to your Genie space
3. Copy the ID from the URL: `https://your-workspace.cloud.databricks.com/genie/spaces/{THIS_IS_YOUR_SPACE_ID}`

---

#### 1.2 Prod Warehouse ID

**What it is**: The SQL Warehouse ID in your Production workspace where queries will run.

```yaml
variables:
  prod_warehouse_id:
    default: "your-warehouse-id"  # <-- TODO: Add your Prod Warehouse ID
```

**How to find it**:
1. Open your Databricks Prod workspace
2. Go to **SQL** → **SQL Warehouses**
3. Click on your warehouse
4. Copy the ID from the URL: `https://your-workspace.cloud.databricks.com/sql/warehouses/{THIS_IS_YOUR_WAREHOUSE_ID}`

---

#### 1.3 Catalog/Schema Mapping

**What it is**: The mapping from your Dev Unity Catalog references to Prod.

```yaml
variables:
  # Source (Dev) - what to find and replace
  source_catalog:
    default: "main_th"        # <-- TODO: Your Dev catalog name
  source_schema:
    default: "schema_dev"     # <-- TODO: Your Dev schema name
  
  # Target (Prod) - replacement values
  target_catalog:
    default: "prod_catalog"   # <-- TODO: Your Prod catalog name
  target_schema:
    default: "schema_prod"    # <-- TODO: Your Prod schema name
```

**Example**:
| Environment | Catalog | Schema | Full Reference |
|-------------|---------|--------|----------------|
| Dev | `main_th` | `schema_dev` | `main_th.schema_dev.customers` |
| Prod | `main_prod` | `schema_prod` | `main_prod.schema_prod.customers` |

---

#### 1.4 Workspace URLs

**What it is**: The URLs for your Dev and Prod Databricks workspaces.

```yaml
targets:
  dev:
    workspace:
      host: https://your-dev-workspace.cloud.databricks.com   # <-- TODO: Dev URL
  prod:
    workspace:
      host: https://your-prod-workspace.cloud.databricks.com  # <-- TODO: Prod URL
```

**Note**: If Dev and Prod are on the same workspace, use the same URL for both.

---

#### 1.5 Compute Configuration

**What it is**: The compute resources used to run the export and deploy tasks.

**Default: Serverless** (recommended)

By default, jobs run on **serverless compute**. No configuration needed - just leave the cluster settings commented out.

Benefits of serverless:
- Instant startup (no cluster provisioning wait)
- No cluster management overhead
- Automatic scaling and resource optimization
- Cost-effective for short-running tasks

**Alternative Options**:

If serverless is not available in your workspace, choose one of the following:

**Option A: Existing Cluster** (shared resources, requires cluster to be running)
```yaml
existing_cluster_id: "your-cluster-id"  # Uncomment and set
```

**How to find cluster ID**: 
- Go to **Compute** → Select your cluster → Copy ID from URL

**Option B: New Job Cluster** (isolated, auto-terminates after job)
```yaml
new_cluster:
  spark_version: "14.3.x-scala2.12"
  num_workers: 0
  node_type_id: "i3.xlarge"  # Adjust for your cloud provider
  spark_conf:
    "spark.databricks.cluster.profile": "singleNode"
    "spark.master": "local[*]"
  custom_tags:
    "ResourceClass": "SingleNode"
```

**Node types by cloud**:
| Cloud | Recommended Node Type |
|-------|----------------------|
| AWS | `i3.xlarge`, `m5.xlarge` |
| Azure | `Standard_DS3_v2`, `Standard_D4s_v3` |
| GCP | `n1-standard-4` |

---

## Step 2: First Deployment

### 2.1 Validate Configuration

Before deploying, validate your configuration:

```bash
databricks bundle validate --target prod
```

**Expected output**: No errors, shows bundle summary.

### 2.2 Deploy Bundle

Deploy the bundle to your workspace:

```bash
databricks bundle deploy --target prod
```

This uploads the notebooks and creates the job definitions.

### 2.3 Run the Pipeline

Execute the full pipeline:

```bash
databricks bundle run promote_genie_to_prod --target prod
```

**What happens**:
1. **Task 1 (Export)**: Exports your Dev Genie space → `genie_definition/genie_space.json`
2. **Task 2 (Deploy)**: Creates a new Prod Genie space with catalog/schema replaced

### 2.4 Save the Prod Space ID

After the job completes successfully, check the output for:

```
⚠️  IMPORTANT: Save this Space ID for future updates:
   space_id = "01f0e034e6cb118695218a38adc4176d"
```

**Critical**: Add this ID to your `databricks.yml`:

```yaml
variables:
  prod_space_id:
    default: "01f0e034e6cb118695218a38adc4176d"  # <-- Paste your new Prod Space ID here
```

---

## Step 3: Subsequent Deployments

After you've saved the `prod_space_id`, subsequent deployments are simple:

```bash
# Deploy any bundle changes first (if you modified databricks.yml)
databricks bundle deploy --target prod

# Run the pipeline to sync changes from Dev to Prod
databricks bundle run promote_genie_to_prod --target prod
```

**What happens**:
1. **Export**: Fresh definition exported from Dev
2. **Update**: Existing Prod space is updated (not recreated)

---

## Available Jobs

| Job | Description | When to Use |
|-----|-------------|-------------|
| `promote_genie_to_prod` | Full pipeline: Export from Dev + Deploy to Prod | Regular sync/deployment |
| `deploy_genie_only` | Deploy only: Use existing `genie_space.json` | Quick deploy without re-export |

### Run Commands

```bash
# Full pipeline (recommended for most cases)
databricks bundle run promote_genie_to_prod --target prod

# Deploy only (skip export step)
databricks bundle run deploy_genie_only --target prod
```

---

## Configuration Examples

### Example 1: Same Workspace (Different Catalogs)

When Dev and Prod are in the same Databricks workspace but use different Unity Catalog schemas:

```yaml
variables:
  source_catalog:
    default: "main"
  source_schema:
    default: "dev"
  target_catalog:
    default: "main"
  target_schema:
    default: "prod"

targets:
  dev:
    workspace:
      host: https://mycompany.cloud.databricks.com
  prod:
    workspace:
      host: https://mycompany.cloud.databricks.com  # Same workspace
```

### Example 2: Different Workspaces

When Dev and Prod are separate Databricks workspaces:

```yaml
variables:
  source_catalog:
    default: "catalog_dev"
  source_schema:
    default: "analytics"
  target_catalog:
    default: "catalog_prod"
  target_schema:
    default: "analytics"

targets:
  dev:
    workspace:
      host: https://mycompany-dev.cloud.databricks.com
  prod:
    workspace:
      host: https://mycompany-prod.cloud.databricks.com  # Different workspace
```

### Example 3: Using Serverless (Default)

Serverless is the default - simply leave cluster configuration commented out:

```yaml
tasks:
  - task_key: export_from_dev
    notebook_task:
      notebook_path: ./src/export_genie_definition.ipynb
      base_parameters:
        space_id: ${var.dev_space_id}
        output_file: "../genie_definition/genie_space.json"
    # No cluster config = serverless compute
```

### Example 4: Using Job Clusters

If serverless is not available, use job clusters:

```yaml
tasks:
  - task_key: export_from_dev
    notebook_task:
      notebook_path: ./src/export_genie_definition.ipynb
      base_parameters:
        space_id: ${var.dev_space_id}
        output_file: "../genie_definition/genie_space.json"
    
    new_cluster:
      spark_version: "14.3.x-scala2.12"
      num_workers: 0
      node_type_id: "i3.xlarge"
      spark_conf:
        "spark.databricks.cluster.profile": "singleNode"
        "spark.master": "local[*]"
      custom_tags:
        "ResourceClass": "SingleNode"
```

---

## Troubleshooting

### Common Errors

| Error Message | Cause | Solution |
|---------------|-------|----------|
| `space_id parameter is required` | Export task missing space ID | Set `dev_space_id` in databricks.yml |
| `warehouse_id is required` | Creating new space without warehouse | Set `prod_warehouse_id` in databricks.yml |
| `title is required` | Creating new space without title | Set `genie_space_title` in databricks.yml |
| `Permission denied` | Insufficient workspace access | See [Permissions](#permissions) section below |
| `Space not found` | Invalid or inaccessible space ID | Verify the space ID exists and you have access |
| `Cluster not found` | Invalid existing cluster ID | Verify cluster exists or use job cluster instead |
| `Serverless compute not available` | Serverless not enabled | Enable serverless in workspace settings or configure `existing_cluster_id` or `new_cluster` |

### Permissions

Ensure you have the correct permissions:

| Operation | Required Permission | Where |
|-----------|---------------------|-------|
| Export | `CAN EDIT` | Dev Genie Space |
| Create Space | `CAN MANAGE` | Prod Workspace |
| Update Space | `CAN EDIT` | Prod Genie Space |
| Run Jobs | `CAN MANAGE RUN` | Job in Prod Workspace |

### Debugging Commands

```bash
# Validate bundle configuration
databricks bundle validate --target prod

# Show bundle summary
databricks bundle summary --target prod

# View job runs
databricks jobs list --output JSON

# Check workspace connectivity
databricks workspace list /
```

### Logs and Monitoring

1. Run the job and note the run ID
2. In Databricks UI: **Workflows** → **Job Runs** → Select your run
3. Click on each task to view detailed logs and output

---

## Quick Reference

### Where to Find Things

| Item | Location |
|------|----------|
| Dev Space ID | Dev Genie Space URL: `/genie/spaces/{SPACE_ID}` |
| Prod Warehouse ID | SQL Warehouses page URL: `/sql/warehouses/{WAREHOUSE_ID}` |
| Prod Space ID | Job output after first successful run |
| Cluster ID (optional) | Compute page URL: `/compute/clusters/{CLUSTER_ID}` |
| Workspace URL | Browser URL when logged in |

**Note**: Cluster ID is only needed if you're not using serverless (the default).

### Command Cheat Sheet

```bash
# Setup
databricks configure --token        # Configure authentication
databricks workspace list /          # Verify connection

# Bundle operations
databricks bundle validate --target prod   # Validate config
databricks bundle deploy --target prod     # Deploy to workspace
databricks bundle summary --target prod    # Show bundle info

# Run jobs
databricks bundle run promote_genie_to_prod --target prod  # Full pipeline
databricks bundle run deploy_genie_only --target prod      # Deploy only
```

### Configuration File Locations

| File | Purpose |
|------|---------|
| `databricks.yml` | Main bundle configuration |
| `~/.databrickscfg` | CLI authentication profiles |
| `.env` | Environment variables (optional) |
