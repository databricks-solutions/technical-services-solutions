# Azure Hybrid Databricks Workspace — Pulumi

## What is Pulumi?

[Pulumi](https://www.pulumi.com/) is an infrastructure-as-code tool — like Terraform, but instead of HCL you write real Python (or TypeScript, Go, etc.). You define your cloud resources in code, run `pulumi up`, and Pulumi creates them for you.

## What does this project do?

It deploys an Azure Databricks workspace configured with:

- **Hybrid compute mode** — enables both serverless and classic compute
- **No Public IP** — secure cluster connectivity (NPIP)
- **Premium tier** by default

That's it — one resource group, one workspace, ready to use.

## Quick Start

### 1. Install tools

- [Pulumi CLI](https://www.pulumi.com/docs/get-started/install/) (`brew install pulumi/tap/pulumi` on macOS)
- [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) (`brew install azure-cli` on macOS)
- Python 3.7+

### 2. Set up and deploy

```bash
# Install Python dependencies
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Log in to Azure
az login
az account set --subscription "<your-subscription-id>"

# Initialize Pulumi
pulumi login --local
pulumi stack init dev

# Configure (or copy Pulumi.dev.yaml.example → Pulumi.dev.yaml)
pulumi config set location eastus
pulumi config set resourceGroupName my-resource-group
pulumi config set workspaceName my-databricks-workspace

# Deploy
pulumi up
```

### 3. Verify

```bash
pulumi stack output workspace_url
```

Open the URL in a browser — your workspace is ready.

## Configuration

| Key | Description | Default |
|-----|-------------|---------|
| `location` | Azure region | `eastus` |
| `resourceGroupName` | Resource group name | `rg-databricks` |
| `workspaceName` | Workspace name | `databricks-workspace` |
| `pricingTier` | `standard`, `premium`, or `trial` | `premium` |

## Clean-up

```bash
pulumi destroy
pulumi stack rm dev
```

## Project Support

These examples are provided AS-IS for exploration and are not formally supported by Databricks with SLAs. Do not submit support tickets for issues arising from their use.
