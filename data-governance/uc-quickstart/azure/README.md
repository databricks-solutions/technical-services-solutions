# Azure Unity Catalog Deployment

This directory contains Azure-specific Terraform configurations for deploying Unity Catalog across multiple environments (dev, prod) using a reusable module architecture.

## Quick Start

```bash
# 1. Set up credentials
cp env_variables.sh.example env_variables.sh
# Edit env_variables.sh with your credentials
source env_variables.sh

# 2. Configure Terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your Azure/Databricks configuration

# 3. Deploy
terraform init
terraform plan
terraform apply
```

## Architecture Overview

The configuration uses a modular structure:
- **`environment/`**: Reusable module for creating UC catalogs, storage, and grants
- **`dev_env.tf`**: Development environment configuration
- **`prod_env.tf`**: Production environment configuration

Each environment module creates:
- Storage account with access connector and RBAC assignments
- Unity Catalog storage credentials (account-level)
- Unity Catalog catalogs and external locations (workspace-level)
- Grants for user groups/service principals

## Prerequisites

### Required Permissions
- **Azure Service Principal:**
  - Contributor or Owner role on Resource Group (for storage and access connector)

- **Databricks Service Principal:**
  - Account Admin (for storage credentials and user groups)
  - Workspace Admin on each workspace (for catalogs, external locations, and grants)

### Existing Resources Required
- Azure Databricks Workspaces (one for dev, one for prod)
- Resource Groups for deploying storage accounts and access connectors
- Databricks Account Console access

## Authentication

Authentication requires both Azure and Databricks credentials. Use the provided template to set environment variables.

### Setup Environment Variables

1. **Copy the template:**
   ```bash
   cp env_variables.sh.example env_variables.sh
   ```

2. **Edit `env_variables.sh` with your credentials:**
   ```bash
   # Azure Service Principal (for resource deployment)
   export ARM_CLIENT_ID="your-azure-sp-client-id"
   export ARM_CLIENT_SECRET="your-azure-sp-secret"
   export ARM_TENANT_ID="your-azure-tenant-id"
   export ARM_SUBSCRIPTION_ID="your-azure-subscription-id"

   # Databricks Service Principal (for Unity Catalog resources)
   export DATABRICKS_CLIENT_ID="your-databricks-sp-client-id"
   export DATABRICKS_CLIENT_SECRET="your-databricks-sp-secret"
   ```

3. **Source the variables:**
   ```bash
   source env_variables.sh
   ```

### Alternative: Azure CLI + Databricks CLI
```bash
# Azure authentication
az login
az account set --subscription "your-subscription-id"

# Databricks authentication via environment variables
export DATABRICKS_CLIENT_ID="your-databricks-sp-client-id"
export DATABRICKS_CLIENT_SECRET="your-databricks-sp-secret"
```

## Configuration

### 1. Create `terraform.tfvars`

Create a `terraform.tfvars` file with the following variables:

```hcl
# Azure configuration
azure_tenant_id = "your-azure-tenant-id"

# Databricks configuration
databricks_account_id = "your-databricks-account-id"

# Workspace hosts
dev_workspace_host  = "https://adb-xxxxx.azuredatabricks.net"
prod_workspace_host = "https://adb-yyyyy.azuredatabricks.net"
```

### 2. Configure Environments

Edit `dev_env.tf` and `prod_env.tf` to customize each environment:

**Example `dev_env.tf`:**
```hcl
module "dev_environment" {
  source = "./environment"
  providers = {
    databricks.workspace = databricks.dev_workspace
    databricks.account   = databricks.account
  }
  storage_account_resource_group = "dev-rg"
  storage_account_name = "devucstorageacct"
  location = "westeurope"
  catalogs = {
    dev-data-catalog = {
      name  = "dev_data"
      owner = "uc-governance-admins-group"
      permissions = [
        {
          principal = "uc-data-engineers-group"
          privileges = [
            "USE CATALOG", "USE SCHEMA",
            "SELECT", "EXECUTE", "READ VOLUME",
            "MODIFY", "REFRESH", "WRITE VOLUME",
            "CREATE SCHEMA", "CREATE TABLE", "CREATE VIEW",
            "CREATE FUNCTION", "CREATE MATERIALIZED VIEW",
            "CREATE MODEL", "MANAGE", "BROWSE"
          ]
        },
        {
          principal = "uc-data-analysts-group"
          privileges = [
            "USE CATALOG", "USE SCHEMA",
            "SELECT", "EXECUTE", "READ VOLUME", "BROWSE"
          ]
        }
      ]
    }
  }
  tags = {
    environment = "dev"
  }
}
```

### 3. Finding Required Values

| Variable | How to Find |
|----------|-------------|
| `azure_tenant_id` | Azure Portal → Azure AD → Overview → Tenant ID |
| `databricks_account_id` | Databricks Account Console → Settings → Account ID |
| `dev_workspace_host` | Databricks workspace URL (e.g., `https://adb-xxxxx.azuredatabricks.net`) |
| `prod_workspace_host` | Databricks workspace URL (e.g., `https://adb-yyyyy.azuredatabricks.net`) |
| `storage_account_resource_group` | Existing Azure resource group name |
| `storage_account_name` | Globally unique name (3-24 lowercase alphanumeric characters) |

## Deployment

### Step-by-Step Deployment

1. **Set up authentication:**
   ```bash
   source env_variables.sh
   ```

2. **Initialize Terraform:**
   ```bash
   terraform init
   ```

3. **Validate configuration:**
   ```bash
   terraform validate
   ```

4. **Preview changes:**
   ```bash
   terraform plan
   ```

5. **Apply configuration:**
   ```bash
   terraform apply
   ```

### Deploy Specific Environment

To deploy only dev or prod environment:

```bash
# Deploy only dev environment
terraform apply -target=module.dev_environment

# Deploy only prod environment
terraform apply -target=module.prod_environment
```

## Resources Created

### Per Environment

Each environment module creates:

**Azure Resources:**
- Storage account (one per environment)
- Storage containers (one per catalog)
- Databricks Access Connector with system-assigned managed identity
- RBAC role assignments:
  - Storage Blob Data Contributor
  - Storage Account Contributor (for file events)
  - Storage Queue Data Contributor (for file events)
  - EventGrid EventSubscription Contributor (for file events)
  - EventGrid Data Contributor (for file events)

**Databricks Resources (Account-level):**
- Storage credential using access connector managed identity

**Databricks Resources (Workspace-level):**
- External locations (one per catalog)
- Unity Catalog catalogs
- Grants for principals (multiple per catalog based on permissions configuration)

## Module Structure

```
azure/
├── provider.tf              # Provider configurations (azurerm, databricks)
├── variables.tf             # Root-level variables
├── dev_env.tf              # Dev environment configuration
├── prod_env.tf             # Prod environment configuration
├── env_variables.sh        # Authentication credentials (not in git)
└── environment/            # Reusable environment module
    ├── main.tf             # Module logic
    ├── variables.tf        # Module variables
    ├── versions.tf         # Provider requirements
    ├── connect_storage/    # Storage + credentials submodule
    └── create_catalog/     # Catalog + external location submodule
```

## Troubleshooting

### Authentication Issues

**Azure CLI not authenticated:**
```bash
az account show  # Should display your subscription
az login         # If not authenticated
```

**Databricks SP authentication failing:**
- Verify `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` are set
- Check service principal has Account Admin role
- Ensure service principal is added to each workspace as admin

### Permission Errors

**Azure deployment failures:**
- Service principal needs Contributor role on resource group
- Check: `az role assignment list --assignee $ARM_CLIENT_ID`

**Storage credential creation fails:**
- Databricks SP needs Account Admin role
- Check in Databricks Account Console → User Management → Service Principals

**Grant creation fails:**
- Databricks SP needs Workspace Admin on the target workspace
- User groups must exist before applying grants
- Verify group names match exactly (case-sensitive)

### Resource Conflicts

**Storage account name already taken:**
- Storage account names must be globally unique across all Azure
- Use lowercase alphanumeric only (3-24 characters)
- Try adding random suffix: `${var.storage_account_name}${random_string.suffix.result}`

**Access connector already exists:**
- Check if previous deployment left resources
- Delete manually in Azure Portal or use: `az databricks access-connector delete`

**Provider configuration errors:**
- Ensure `dev_workspace_host` and `prod_workspace_host` are valid URLs
- Format: `https://adb-<workspace-id>.<region>.azuredatabricks.net`
- Do not include trailing slash

### Common Errors

**Error: "configuration_aliases" in versions.tf**
```
Solution: Updated to Terraform 0.15+
Run: terraform init -upgrade
```

**Error: depends_on with dynamic reference**
```
Solution: Already fixed in environment/main.tf (line 53)
Uses: depends_on = [module.catalog]
```

**Error: Grant resource references wrong catalog**
```
Solution: Ensure catalog map key matches catalog name
In catalogs variable, use: catalogs = { "catalog-name" = { name = "catalog-name" ... } }
```