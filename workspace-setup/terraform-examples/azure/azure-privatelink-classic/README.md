# Azure Private Link (Classic) Workspace Setup Guide

This example deploys a Databricks workspace on Azure with **Private Link (classic)** for backend and DBFS. Control plane and DBFS use private endpoints in your VNet; **public network access is always enabled** for the workspace (no front-end Private Link), so you can reach the UI from the internet.

**When to use this scenario:** Choose this when you want backend and DBFS over Private Link with workspace UI reachable from the public internet (no front-end Private Link), NAT gateway for outbound from cluster subnets, and the classic (non–secure cluster connectivity) architecture.

## Requirements

- Terraform is installed on your local machine: [link](https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli#install-terraform)
- Azure CLI is installed on your local machine: [Mac](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-macos?view=azure-cli-latest#install-with-homebrew) or [Windows](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows?view=azure-cli-latest&pivots=winget)
- Azure CLI configured with appropriate credentials
- Databricks account created
- Databricks account admin access (required if you enable serverless NCC)
- Contributor rights to your Azure subscription (Contributor rights on the resource group level are not sufficient, as Databricks provisioning creates resources in a separate managed resource group, which requires subscription-level access.)

## Before you begin

Configuration values (subscription ID, CIDR, location, resource group behavior, and network options) are defined as variables. Copy `tf/terraform.tfvars.example` to `tf/terraform.tfvars` and set your values there. Terraform loads `terraform.tfvars` automatically. You can also use a file ending in `.auto.tfvars` or pass variables via the command line.

## Authenticate the Azure CLI

### Option 1: Interactive user login (for users)

```sh
az login
```

This command opens a browser for user authentication (U2M). It is sufficient for all operations in this document.

### Option 2: Service principal login (for automation, CI/CD)

Use this for non-interactive environments (pipelines, scripts).

1. Log in to Azure via Azure CLI:

```sh
az login
```

2. (Optional) Set the target subscription:

```sh
az account set --subscription "<subscription-id>"
```

Find your subscription ID with:

```sh
az account show
```

3. Create the Service Principal:

```sh
az ad sp create-for-rbac --name "<sp-name>" --role <role> --scopes /subscriptions/<subscription-id>
```

- `<sp-name>`: Desired service principal name.
- `<role>`: e.g. Contributor, Reader, Owner.
- `<subscription-id>`: Your Azure Subscription ID.

Save the password (client secret) from the output; it cannot be retrieved later.

4. Authenticate with the service principal:

```sh
az login --service-principal -u <appId> -p <password> --tenant <tenant>
```

For more information, see [Create an Azure service principal with the Azure CLI](https://learn.microsoft.com/en-us/cli/azure/azure-cli-sp-tutorial-1?view=azure-cli-latest&tabs=bash).

## What this Terraform code does

### Overview

The code provisions:

1. **Data plane resource group** – Either creates a new resource group or uses an existing one for all data plane resources.
2. **Data plane VNet** – A virtual network with three subnets:
   - **Public subnet (host)** – Host IPs for cluster nodes. Each node gets one IP from this subnet and one from the private subnet. Delegation to `Microsoft.Databricks/workspaces`; optional service endpoints via `subnets_service_endpoints`.
   - **Private subnet (container)** – Container IPs for cluster nodes. Each node uses one host IP (public subnet) and one container IP (this subnet). Delegation to `Microsoft.Databricks/workspaces`; optional service endpoints via `subnets_service_endpoints`.
   - **Private Link subnet** – Dedicated subnet for private endpoints (no delegation); used for control plane and DBFS private endpoints.
3. **Network security group (NSG)** – Attached to both public and private subnets, with outbound rules for Azure Active Directory (port 443) and Azure Front Door (port 443).
4. **Databricks workspace** – Premium SKU, VNet-injected into the public/private subnets, with public network access always enabled (no front-end Private Link) and customer-managed keys. Root storage (DBFS) uses a uniquely named storage account.
5. **Private DNS zones** – For control plane (`privatelink.azuredatabricks.net`) and for DBFS (`privatelink.dfs.core.windows.net`, `privatelink.blob.core.windows.net`), linked to the data plane VNet.
6. **Private endpoints**:
   - **Control plane** – One private endpoint for the Databricks UI/API (`databricks_ui_api`), in the Private Link subnet, with DNS in `privatelink.azuredatabricks.net`.
   - **DBFS** – Two private endpoints for the workspace root storage account: one for `dfs` and one for `blob`, each with the corresponding private DNS zone.
7. **Network Connectivity Config (NCC)** – Creates an account-level NCC, attaches it to the workspace, and adds private endpoint rules for the same DBFS storage (blob + dfs). Databricks creates private endpoint requests for serverless compute; Terraform **auto-approves** them on the storage account so serverless (SQL warehouses, serverless jobs, etc.) can reach DBFS over Private Link without manual approval in the portal.

Backend and DBFS traffic from classic compute use the private endpoints in your VNet; serverless compute uses the NCC private endpoints (auto-approved). Workspace UI remains reachable via public network.

### Variables

Copy `terraform.tfvars.example` to `terraform.tfvars` in the `tf/` directory and set your values. Do not commit `terraform.tfvars` (it may contain sensitive data). Terraform automatically loads `terraform.tfvars`; for other file names use `-var-file`.

#### List of variables

| Variable | Description |
|----------|-------------|
| `prefix` | **(Optional)** Prefix for the Databricks workspace name (display). Default: `databricks-workspace`. |
| `resource_prefix` | **(Optional)** Prefix for Azure resource names (VNet, NSG, subnets, resource group). Also used to derive the DBFS root storage account name (alphanumeric only). Must be 1–40 characters: a-z, 0-9, `-`, `.`. Default: `databricks-workspace`. |
| `az_subscription` | **(Required)** Azure subscription ID where resources are deployed. |
| `location` | **(Required)** Azure region for the resource group and all resources (e.g. `eastus2`). See [supported regions](https://learn.microsoft.com/en-us/azure/databricks/resources/supported-regions). |
| `create_data_plane_resource_group` | Set to `true` to create a new resource group (name: `rg-<resource_prefix>-dp` per [Azure CAF abbreviations](https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ready/azure-best-practices/resource-abbreviations)). Set to `false` to use `existing_data_plane_resource_group_name`. |
| `existing_data_plane_resource_group_name` | Name of the existing resource group when `create_data_plane_resource_group` is `false`. Must be non-empty in that case. |
| `cidr_dp` | **(Required)** CIDR for the data plane VNet (e.g. `10.139.0.0/16`). Public, private, and Private Link subnets are derived from this. |
| `subnets_service_endpoints` | **(Optional)** List of Azure service endpoints for the public and private subnets (e.g. `["Microsoft.Storage"]`). Default: `[]`. |
| `databricks_account_id` | **(Required)** Databricks account ID for serverless NCC. Find it in the account console URL: `https://accounts.azuredatabricks.net/accounts/<account_id>`. NCC is always created so serverless compute can reach DBFS over Private Link; private endpoint connections are auto-approved. |
| `tags` | **(Optional)** Map of tags to apply to all Azure resources. Merged with default `Project` (from prefix) and `Owner` (from Azure CLI); values in `tags` override those. Default: `{}`. |

## Deploy

```bash
cd tf

# Copy the example variables file and set your values
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your subscription ID, CIDR, location, etc.

# Initialize Terraform
terraform init

# Review the execution plan
terraform plan

# Apply the configuration
terraform apply
```

Type `yes` when prompted. Deployment typically takes several minutes. When it finishes, workspace and network outputs are available. NCC private endpoint connections on the DBFS storage account are **auto-approved** by Terraform so serverless compute can use Private Link immediately.

## Access your workspace

After a successful deploy:

```bash
# Workspace URL and ID (for login and automation)
terraform output workspace_url
terraform output workspace_id

# Resource group and network (for peering or other modules)
terraform output resource_group_name
terraform output resource_group_id
terraform output vnet_name
terraform output vnet_id
terraform output subnet_public_id
terraform output subnet_private_id
terraform output subnet_privatelink_id
```

Open the workspace URL and sign in with your Databricks credentials. Public network access is always enabled, so the workspace is reachable from the internet.

**Important:** To confirm the setup works end-to-end, create and start a **classic (non–high-concurrency) cluster**. A classic cluster uses the VNet-injected subnets, NAT gateway, and private endpoints; if it reaches "Running" state, the deployment is validated.

## Validation

To verify the deployment succeeded:

1. **Terraform outputs** – From the `tf/` directory, run `terraform output` and confirm `workspace_url`, `workspace_id`, `resource_group_name`, and `vnet_id` are present and non-empty.
2. **Azure portal** – In your subscription, check that the resource group, VNet, subnets, NAT gateway, private endpoints, and the Databricks workspace exist and are in "Succeeded" or "Ready" state.
3. **Workspace access** – Open `terraform output -raw workspace_url` in a browser and sign in (public access is always enabled).
4. **Classic cluster** – Create and start a **classic cluster** (Compute → Create cluster; use the default "Standard” cluster type, not high-concurrency/shared). Once the cluster is in "Running" state, the setup is proven: the cluster has obtained IPs from the VNet subnets and can reach the control plane and DBFS over the private endpoints.

### Gathering test evidence

A script is provided to capture automated checks and produce a verification report (useful for audits or proof of a working setup):

```bash
# From the scenario root (azure-privatelink-classic/) or with path to tf/
./scripts/verify-deployment.sh
```

Requires Azure CLI to be logged in (`az login`). The report is written to `VERIFICATION_REPORT.md` in the scenario root and includes: Terraform outputs, resource group and VNet checks, private endpoint and private DNS zone listing, and workspace URL reachability (HTTP). For full evidence, open the workspace URL in a browser, sign in, **create and start a classic cluster** until it reaches "Running", and optionally capture a screenshot of the cluster or a simple job run.

## Clean-up

To destroy all resources created by this scenario:

```bash
cd tf
terraform destroy
```

Type `yes` when prompted. Destruction can take several minutes. Ensure no other workloads depend on the resource group, VNet, or workspace before running `terraform destroy`.

## Troubleshooting

| Issue | Possible cause | Solution |
|-------|----------------|----------|
| `az login` or provider auth fails | Azure CLI not installed or not logged in | Install Azure CLI, run `az login`, or set `ARM_CLIENT_ID`, `ARM_CLIENT_SECRET`, `ARM_TENANT_ID`, `ARM_SUBSCRIPTION_ID` for service principal. |
| `terraform plan` fails on subscription or permission | Wrong subscription or insufficient rights | Run `az account set --subscription "<id>"` and ensure the identity has Contributor at subscription scope. |
| Workspace URL does not load (Private Link only) | Client not on the VNet or DNS not resolving privately | Use a machine/VPN that can reach the data plane VNet; ensure private DNS zones are linked and private endpoints are approved. |
| Subnet or delegation errors | CIDR too small or delegation conflict | Use a VNet CIDR of at least /24 (e.g. `10.139.0.0/16`). Do not use the Private Link subnet for non–private-endpoint resources. |
| DBFS or control plane timeout | NSG or routing blocking outbound 443 | Ensure NSG rules allow outbound to Azure Active Directory and Azure Front Door; ensure NAT gateway (or egress) is attached to the workspace subnets. |
| `mws ncc private endpoint rule` request timed out after 1m5s | Account API is slow creating the Azure PE request (common) | Run `terraform apply` again. The NCC and binding already exist; the rule creation often succeeds on the second run. The provider does not support a longer timeout for this resource. |

## File structure

This scenario follows the [repository Terraform guidelines](../../README.md#terraform-files): version constraints in `versions.tf`, provider config in `providers.tf`, and an example variables file with no sensitive data. Terraform files under `tf/` are split by purpose:

```
azure-privatelink-classic/
├── README.md
└── tf/
    ├── main.tf                      # Shared locals (prefix, DBFS name, tags, dp_rg_*) and data sources
    ├── azure.tf                     # Data plane resource group (create or reference existing)
    ├── versions.tf                  # Terraform and provider version constraints
    ├── providers.tf                 # Azure provider configuration
    ├── variables.tf                 # Input variable definitions
    ├── terraform.tfvars.example     # Example variable values (copy to terraform.tfvars)
    ├── network.tf                   # Data plane VNet, NSG, subnets (public, private, Private Link)
    ├── databricks.tf                # Databricks workspace (VNet injection, root storage)
    ├── dns_zones.tf                # Private DNS zones (control plane + DBFS) and VNet links
    ├── pe_backend.tf               # Private endpoint for control plane (databricks_ui_api)
    ├── pe_dbfs.tf                  # Private endpoints for DBFS storage (dfs and blob)
    └── outputs.tf                  # workspace, resource group, vnet, subnets
```

| File | Purpose |
|------|--------|
| **main.tf** | Azure client config and current user data; locals (prefix, dbfsname, tags, dp_rg_name/id/location). |
| **azure.tf** | Data plane resource group (created or referenced via data source depending on create_data_plane_resource_group). |
| **versions.tf** | Terraform required version (~> 1.3) and required providers (azurerm, external). |
| **providers.tf** | Azure provider configuration (subscription_id). Authentication via Azure CLI or ARM_* environment variables. |
| **variables.tf** | Input variables with section headers (Azure, Network, Workspace) and validation. |
| **terraform.tfvars.example** | Example variable values; copy to `terraform.tfvars` and set your subscription, CIDR, location, etc. |
| **network.tf** | Data plane VNet; NSG with outbound rules for AAD and Azure Front Door; public, private, and Private Link subnets with delegation where needed. |
| **databricks.tf** | `azurerm_databricks_workspace` (Premium, VNet injection, public access always enabled, customer-managed key, root storage name). |
| **dns_zones.tf** | Private DNS zones for control plane and DBFS (dfs/blob); VNet links. |
| **pe_backend.tf** | Private endpoint for Databricks control plane in the Private Link subnet. |
| **pe_dbfs.tf** | Private endpoints for DBFS storage (dfs and blob) in the Private Link subnet. |
| **outputs.tf** | Workspace URL/ID; resource group name/id; VNet name/id; public, private, and Private Link subnet IDs. |

## Terraform template examples and more documentation

These templates are for reference and exploration and are not formally supported by Databricks with SLAs. Use them as examples and adapt to your environment.

- [Deploy with Private Link](https://github.com/databricks/terraform-databricks-examples/tree/main/examples/adb-with-private-link-standard)
- [Security Reference Architecture Template](https://github.com/databricks/terraform-databricks-sra/tree/main/azure)
- [Terraform Databricks provider documentation](https://registry.terraform.io/providers/databricks/databricks/latest/docs)
- [Configure a workspace with Private Link (classic)](https://learn.microsoft.com/en-us/azure/databricks/security/network/classic/private-link)
