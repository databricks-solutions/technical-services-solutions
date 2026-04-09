# Azure Hybrid Databricks Workspace — Pulumi

## Overview

Deploys an Azure Databricks workspace with **Hybrid compute mode** and **No Public IP** (NPIP) using Pulumi and Python. Hybrid compute mode enables serverless compute alongside classic clusters, giving you the flexibility to use both.

## Architecture

This scenario creates:

- **Resource Group** with Environment and ManagedBy tags
- **Azure Databricks Workspace** (Premium tier) with:
  - Hybrid compute mode (serverless + classic)
  - No Public IP enabled (Secure Cluster Connectivity)
  - Managed resource group for Databricks-managed resources

## Prerequisites

- Python 3.7+
- Azure CLI (`brew install azure-cli`)
- Pulumi CLI
- Azure subscription with permissions to create Databricks workspaces

### Installing Pulumi

**macOS:**
```bash
brew install pulumi/tap/pulumi
```

**Linux / WSL:**
```bash
curl -fsSL https://get.pulumi.com | sh
```

**Windows:**
```bash
choco install pulumi
```

Verify:
```bash
pulumi version
```

## Configuration

| Config Key | Description | Default |
|------------|-------------|---------|
| `location` | Azure region | `eastus` |
| `resourceGroupName` | Resource group name | `rg-databricks` |
| `workspaceName` | Databricks workspace name | `databricks-workspace` |
| `pricingTier` | Pricing tier (`standard`, `premium`, `trial`) | `premium` |

## Deployment Steps

### 1. Install Python dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Authenticate with Azure

```bash
az login
az account set --subscription "<subscription-id>"
```

### 3. Initialize Pulumi

```bash
pulumi login --local   # or `pulumi login` for Pulumi Cloud
pulumi stack init dev
```

### 4. Configure

```bash
pulumi config set location eastus
pulumi config set resourceGroupName my-resource-group
pulumi config set workspaceName my-databricks-workspace
pulumi config set pricingTier premium
```

Or copy the example config:
```bash
cp Pulumi.dev.yaml.example Pulumi.dev.yaml
```

### 5. Deploy

```bash
pulumi up
```

Review the plan and confirm with "yes".

## Validation

After deployment, verify the workspace:

```bash
pulumi stack output workspace_url
```

Open the URL in a browser to confirm the workspace is accessible.

## Outputs

| Output | Description |
|--------|-------------|
| `resource_group_name` | Name of the created resource group |
| `workspace_id` | Azure resource ID of the workspace |
| `workspace_url` | URL to access the Databricks workspace |
| `workspace_name` | Name of the workspace |
| `location` | Azure region |

## Clean-up

```bash
pulumi destroy
pulumi stack rm dev
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Authentication error | Run `az account show` to verify login |
| Resource already exists | Use `pulumi import` to adopt existing resources |
| State issues | Export/import state: `pulumi stack export > stack.json` |

## Project Support

Please note that this project is provided for your exploration only and is not formally supported by Databricks with Service Level Agreements (SLAs). They are provided AS-IS, and we do not make any guarantees. Please do not submit a support ticket relating to any issues arising from the use of this project.
