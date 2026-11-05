# Azure Private Link (Classic) Workspace Setup Guide

This example deploys a Databricks workspace on Azure with **Private Link (classic)** for backend and DBFS. Control plane and DBFS use private endpoints in your VNet; **public network access is always enabled** for the workspace (no front-end Private Link), so you can reach the UI from the internet.

**When to use this scenario:** Choose this when you want backend and DBFS over Private Link with workspace UI reachable from the public internet (no front-end Private Link), NAT gateway for outbound from cluster subnets, and the classic (non–secure cluster connectivity) architecture.

## Requirements

- Terraform is installed on your local machine: [link](https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli#install-terraform)
- Azure CLI is installed on your local machine: [Mac](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-macos?view=azure-cli-latest#install-with-homebrew) or [Windows](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows?view=azure-cli-latest&pivots=winget)
- Azure CLI configured with appropriate credentials
- Databricks account initialized: If this is your first time accessing Azure Databricks at the account level (and no account admin has been established yet), follow [this](https://learn.microsoft.com/en-us/azure/databricks/admin/admin-concepts#establish-first-account-admin) documentation to assign the first account admin.
- Databricks account admin access (required if you enable serverless NCC)
- Contributor rights to your Azure subscription (Contributor rights on the resource group level are not sufficient, as Databricks provisioning creates resources in a separate managed resource group, which requires subscription-level access.)

## Before you begin

Configuration values (subscription ID, VNet and subnet CIDRs, location, resource group behavior, and network options) are defined as variables. Copy `tf/terraform.tfvars.example` to `tf/terraform.tfvars` and set your values there. Terraform loads `terraform.tfvars` automatically. You can also use a file ending in `.auto.tfvars` or pass variables via the command line.

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
2. **Data plane VNet** – A virtual network with address space `cidr_dp`. Three subnets use explicit CIDR variables so you can match any existing layout (e.g. /16, /22, or /24 for workspace subnets):
   - **Public subnet (host)** – CIDR from `subnet_workspace_cidrs[0]`. Host IPs for cluster nodes. Delegation to `Microsoft.Databricks/workspaces`; optional service endpoints via `subnets_service_endpoints`.
   - **Private subnet (container)** – CIDR from `subnet_workspace_cidrs[1]`. Container IPs for cluster nodes. Delegation to `Microsoft.Databricks/workspaces`; optional service endpoints via `subnets_service_endpoints`.
   - **Private Link subnet** – CIDR from `subnet_private_endpoint_cidr`. Dedicated subnet for private endpoints (no delegation); used for control plane and DBFS private endpoints.
3. **Network security group (NSG)** – Attached to both public and private subnets, with outbound rules for Azure Active Directory (port 443) and Azure Front Door (port 443).
4. **Databricks workspace** – Premium SKU, VNet-injected into the public/private subnets, with public network access always enabled (no front-end Private Link). Managed resource group name is set to `mrg-dbw-<resource_prefix>-dp`. Root storage (DBFS) uses a uniquely named storage account.
5. **Private DNS zones** – For control plane (`privatelink.azuredatabricks.net`) and for DBFS (`privatelink.dfs.core.windows.net`, `privatelink.blob.core.windows.net`), linked to the data plane VNet.
6. **Private endpoints**:
   - **Control plane** – One private endpoint for the Databricks UI/API (`databricks_ui_api`), in the Private Link subnet, with DNS in `privatelink.azuredatabricks.net`.
   - **DBFS** – Two private endpoints for the workspace root storage account: one for `dfs` and one for `blob`, each with the corresponding private DNS zone.
7. **Network Connectivity Config (NCC)** – Creates an account-level NCC, attaches it to the workspace, and adds private endpoint rules for the same DBFS storage (blob, then dfs with a short delay to avoid API timeouts). Databricks creates private endpoint requests for serverless compute; Terraform **auto-approves** them on the storage account so serverless (SQL warehouses, serverless jobs, etc.) can reach DBFS over Private Link without manual approval in the portal.
8. **Unity Catalog metastore (optional)** – Set `metastore_id` to assign an existing metastore (account API), or `new_metastore_name` (plus `admin_user`) to create one in the workspace region, owned by a new `<name>-admins` group, and assign it. If you set neither, no assignment runs here; attach a metastore manually in the [account console](https://accounts.azuredatabricks.net/) (or rely on org defaults that auto-assign new workspaces in some regions).
9. **User-defined catalog (optional, `new_catalog = true`)** – Creates a dedicated ADLS Gen2 storage account, an access connector (system-assigned managed identity with *Storage Blob Data Contributor* on the account), a Unity Catalog storage credential, an external location, and a catalog using that location as storage root. The storage account is locked down like the rest of the deployment:
   - **Public network access is disabled**, in two steps: the catalog’s access connector is first added as a resource instance rule (as with “enabled from selected networks”, default action Deny), then public access is switched off. The rule stays in place, so the Databricks control plane can still validate the credential and manage the catalog. Compute reaches the data only through the private endpoints below.
   - **Classic compute** reaches it over two private endpoints (`dfs`, `blob`) in the Private Link subnet, using the same private DNS zones as DBFS.
   - **Serverless compute** reaches it over two additional NCC private endpoint rules (`dfs`, `blob`) on the existing NCC, auto-approved on the storage account by Terraform like the DBFS ones.
10. **Legacy Hive metastore access disabled (always, when a metastore is assigned)** – Direct access to the legacy Hive metastore is disabled for the workspace (`databricks_disable_legacy_access_setting`), so all data access goes through Unity Catalog, as in the [Databricks SRA template](https://github.com/databricks/terraform-databricks-sra). With `new_catalog = true` the default catalog is set to the new catalog first, because the default cannot remain `hive_metastore`. **Permanent after 30 days:** once disabled for 30 days the workspace is Unity Catalog only and direct Hive metastore access cannot be re-enabled. Runtimes older than 13.3 LTS stop working and anything referencing `hive_metastore` fails; restart running clusters and SQL warehouses after the setting changes.
11. **Validation cluster (optional, `create_cluster = true`)** – A UC-compatible single-node classic cluster in standard (shared) access mode, so workspace users can attach to it (no cluster policy, latest LTS runtime).

Backend, DBFS and Unity Catalog storage traffic from classic compute use the private endpoints in your VNet; serverless compute uses the NCC private endpoints (auto-approved). Workspace UI remains reachable via public network.

### Variables

Copy `terraform.tfvars.example` to `terraform.tfvars` in the `tf/` directory and set your values. Do not commit `terraform.tfvars` (it may contain sensitive data). Terraform automatically loads `terraform.tfvars`; for other file names use `-var-file`.

#### List of variables

| Variable | Description |
|----------|-------------|
| `resource_prefix` | **(Optional)** Prefix for Azure resource names (VNet, NSG, subnets, resource group) and the Databricks workspace name. Also used to derive the DBFS root storage account name (alphanumeric only). Must be 1–40 characters: a-z, 0-9, `-`, `.`. Default: `databricks-workspace`. |
| `az_subscription` | **(Required)** Azure subscription ID where resources are deployed. |
| `location` | **Required when creating a resource group:** Azure region for the new RG and all resources (e.g. `eastus2`). **When using an existing resource group:** omit or leave empty; the template uses the existing RG’s region for the VNet, workspace, private endpoints, and NCC so they stay aligned. See [supported regions](https://learn.microsoft.com/en-us/azure/databricks/resources/supported-regions). |
| `create_data_plane_resource_group` | Set to `true` to create a new resource group (name: `rg-<resource_prefix>-dp` per [Azure CAF abbreviations](https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ready/azure-best-practices/resource-abbreviations)). Set to `false` to use `existing_data_plane_resource_group_name`. |
| `existing_data_plane_resource_group_name` | Name of the existing resource group when `create_data_plane_resource_group` is `false`. Must be non-empty in that case. The RG must be in `az_subscription`; its region drives all regional resources. |
| `cidr_dp` | **(Required)** CIDR for the data plane VNet address space (e.g. `10.0.0.0/16`). Must encompass all subnets. |
| `subnet_workspace_cidrs` | **(Required)** List of two CIDRs for the workspace subnets: `[public, private]`. Must be within the VNet. Example: `["10.0.0.0/24", "10.0.1.0/24"]`. |
| `subnet_private_endpoint_cidr` | **(Required)** CIDR for the Private Link subnet (control plane and DBFS private endpoints). Must be within the VNet. Example: `10.0.2.0/26`. |
| `service_endpoint_policy_storage_accounts` | **(Optional)** Additional Azure Storage account resource IDs to allow through the service endpoint policy, alongside the built-in `/services/Azure/Databricks` alias. Use for storage accounts cluster nodes must reach via the `Microsoft.Storage` service endpoint — for example, Unity Catalog external location accounts or data lake accounts. Each entry must be a full resource ID: `/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<name>`. Default: `[]` (only Databricks-managed storage allowed). |
| `create_nat_gateway` | **(Optional)** When `true`, creates a NAT gateway and attaches it to the workspace subnets for outbound internet access from cluster nodes (e.g. installing packages from PyPI or Maven). Set to `false` when `Microsoft.Storage` and `Microsoft.EventHub` service endpoints cover all required Azure traffic and no general internet egress is needed — for example in fully private deployments or when a network virtual appliance handles egress. Default: `true`. |
| `nat_gateway_zones` | **(Optional)** Availability zone(s) for the NAT gateway and its public IP. Only used when `create_nat_gateway` is `true`. `[]` (default) creates a non-zonal (regional) NAT gateway. Provide a single zone (e.g. `["1"]`) to pin the NAT gateway to that zone. An Azure NAT gateway cannot span multiple zones. Default: `[]`. |
| `databricks_account_id` | **(Required)** Databricks account ID for serverless NCC. Find it in the account console URL: `https://accounts.azuredatabricks.net/accounts/<account_id>`. NCC is always created so serverless compute can reach DBFS over Private Link; private endpoint connections are auto-approved. |
| `metastore_id` | **(Optional)** UUID of an **existing** Unity Catalog metastore to assign to the workspace (account API; requires account admin). Azure allows one metastore per region per account, so the regional metastore usually already exists — list them with `databricks account metastores list`. Mutually exclusive with `new_metastore_name`. Default `""` (attach later in the account console if your account does not auto-assign). |
| `new_metastore_name` | **(Optional)** Name of a **new** metastore to create in the workspace region and assign. Creates a `<name>-admins` group (owner) with `admin_user` as member. Mutually exclusive with `metastore_id`. Default `""`. |
| `admin_user` | **(Optional)** Databricks account user (email) made workspace admin and granted `ALL PRIVILEGES` on the user-defined catalog, external location and storage credential. Required with `new_metastore_name`. Use the identity running Terraform so it can create the storage credential, external location and catalog. Default `""`. |
| `new_catalog` | **(Optional)** Create the user-defined catalog stack (storage account, access connector, private endpoints, NCC rules, storage credential, external location, catalog). Requires a metastore (`metastore_id` or `new_metastore_name`) and Owner / User Access Administrator on the resource group (role assignment). Default `false`. |
| `uc_storage_account_name` | **(Optional)** Catalog storage account name (3–24 chars, lowercase letters and numbers, globally unique). Default `""` derives `uc` + up to 22 alphanumeric characters of `resource_prefix`, which can collide — set it explicitly if so. |
| `uc_container_name` | **(Optional)** Container used as catalog storage root. Default `uc-catalog`. |
| `catalog_name` / `storage_credential_name` / `external_location_name` | **(Optional)** Unity Catalog object names. Defaults: `<resource_prefix>_catalog` (hyphens/dots become underscores), `<resource_prefix>-storage-credential`, `<resource_prefix>-external-location`. |
| `create_cluster` | **(Optional)** Create a UC-compatible single-node classic cluster to validate the deployment. Requires a metastore. Default `false`. |
| `node_type_id` / `cluster_autotermination_minutes` | **(Optional)** VM SKU (default `Standard_DS3_v2`) and idle minutes (default `10`, minimum `10`) for the validation cluster. |
| `tags` | **(Optional)** Tags applied to Azure resources that support tags. Default `{}` applies no tags (no built-in `Project` or `owner`). |

## Existing metastore prerequisites

Skip this section if you let the template create the metastore (`new_metastore_name`): the metastore is then owned by a new `<name>-admins` group whose only member is `admin_user`, so run Terraform as `admin_user` (or add the identity running Terraform to that group).

When you attach to an **existing** metastore (`metastore_id`), the identity running Terraform is usually not a metastore admin, so it cannot create the storage credential, external location and catalog. Before deploying, have a **metastore admin** run this SQL in a workspace attached to that metastore (a SQL warehouse or notebook), replacing the principal with the identity's application (client) ID or user name:

```sql
GRANT CREATE STORAGE CREDENTIAL ON METASTORE TO `<application-id-or-user>`;
GRANT CREATE EXTERNAL LOCATION ON METASTORE TO `<application-id-or-user>`;
GRANT CREATE CATALOG ON METASTORE TO `<application-id-or-user>`;
```

These are only needed when the user-defined catalog is created (`new_catalog = true`). Without them the apply fails with a `PERMISSION_DENIED` error on the first Unity Catalog object. The identity keeps ownership of the objects it creates and then grants `admin_user` `ALL PRIVILEGES` on the catalog, external location and storage credential.

## Deploy

```bash
cd tf

# Copy the example variables file and set your values
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your subscription ID, VNet and subnet CIDRs, location, etc.

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

**Important:** To confirm the setup works end-to-end, create and start a **classic (non–high-concurrency) cluster** (or set `create_cluster = true` and let Terraform do it). A classic cluster uses the VNet-injected subnets, NAT gateway, and private endpoints; if it reaches "Running" state, the deployment is validated.

## Validation

To verify the deployment succeeded:

1. **Terraform outputs** – From the `tf/` directory, run `terraform output` and confirm `workspace_url`, `workspace_id`, `resource_group_name`, and `vnet_id` are present and non-empty.
2. **Azure portal** – In your subscription, check that the resource group, VNet, subnets, NAT gateway, private endpoints, and the Databricks workspace exist and are in "Succeeded" or "Ready" state.
3. **Workspace access** – Open `terraform output -raw workspace_url` in a browser and sign in (public access is always enabled).
4. **Classic cluster** – Create and start a **classic cluster** (Compute → Create cluster; use the default "Standard” cluster type, not high-concurrency/shared). Once the cluster is in "Running" state, the setup is proven: the cluster has obtained IPs from the VNet subnets and can reach the control plane and DBFS over the private endpoints.

## Clean-up

To destroy all resources created by this scenario:

```bash
cd tf
terraform destroy
```

Type `yes` when prompted. Destruction can take several minutes. The workspace is destroyed before the NCC (Network Connectivity Config) so the account API can delete the NCC; ensure no other workloads depend on the resource group, VNet, or workspace before running `terraform destroy`.

## Troubleshooting

| Issue | Possible cause | Solution |
|-------|----------------|----------|
| `az login` or provider auth fails | Azure CLI not installed or not logged in | Install Azure CLI, run `az login`, or set `ARM_CLIENT_ID`, `ARM_CLIENT_SECRET`, `ARM_TENANT_ID`, `ARM_SUBSCRIPTION_ID` for service principal. |
| `terraform plan` fails on subscription or permission | Wrong subscription or insufficient rights | Run `az account set --subscription "<id>"` and ensure the identity has Contributor at subscription scope. |
| Workspace URL does not load (Private Link only) | Client not on the VNet or DNS not resolving privately | Use a machine/VPN that can reach the data plane VNet; ensure private DNS zones are linked and private endpoints are approved. |
| Subnet or delegation errors | CIDR too small or delegation conflict | Ensure `cidr_dp` encompasses all three subnets. Set `subnet_workspace_cidrs` and `subnet_private_endpoint_cidr` to non-overlapping CIDRs within the VNet (e.g. /24 for workspace, /26 for Private Link). Do not use the Private Link subnet for non–private-endpoint resources. |
| DBFS or control plane timeout | NSG or routing blocking outbound 443 | Ensure NSG rules allow outbound to Azure Active Directory and Azure Front Door; ensure NAT gateway (or egress) is attached to the workspace subnets. |
| `mws ncc private endpoint rule` request timed out after 1m5s | Account API is slow creating the Azure PE request | The code creates the blob rule first, then waits (~75s), then the dfs rule to reduce timeouts. If the dfs rule still times out, run `terraform apply` again; the rule creation often succeeds on retry. |
| `cannot delete mws network connectivity config ... attached to one or more workspaces` | NCC cannot be deleted while attached to a workspace | The workspace is configured to be destroyed before the NCC. If you see this after a partial destroy, run `terraform destroy` again; once the workspace is gone, the NCC can be deleted. |
| Workspace has no Unity Catalog metastore | No metastore configured; auto-assignment depends on your account | Set `metastore_id` to an existing metastore UUID (or `new_metastore_name` + `admin_user` to create one) and re-apply, or assign the workspace to a metastore in the Databricks account console. |
| `new_catalog = true needs a Unity Catalog metastore` | Catalog requested without a metastore | Set `metastore_id` or `new_metastore_name`. |
| Storage credential or external location creation fails with 403 / `AuthorizationPermissionMismatch` | Role assignment not propagated yet, or the Terraform identity is not a metastore admin | Re-run `terraform apply` after a few minutes. Make sure the identity running Terraform can create storage credentials/external locations on the metastore (for a new metastore, set `admin_user` to that identity). |
| `AuthorizationFailed` on `azurerm_role_assignment` | Identity cannot create role assignments | Grant Owner or User Access Administrator on the data plane resource group (or subscription). |
| Storage credential, external location or catalog creation fails with a storage access error | The access connector rule did not survive disabling public access, or has not propagated yet | Check the storage account’s networking: public access disabled and the access connector listed under resource instances. Re-run `terraform apply` after a few minutes. |
| Clusters or SQL warehouses cannot read the catalog | Private endpoint not approved / DNS not resolving, or NCC rules not approved | Check the private endpoint connections on the catalog storage account are `Approved` (Terraform approves the NCC ones) and the DNS zones are linked to the VNet. |

## File structure

This scenario follows the [repository Terraform guidelines](../../README.md#terraform-files): version constraints in `versions.tf`, provider config in `providers.tf`, and an example variables file with no sensitive data. Terraform files under `tf/` are split by purpose:

```
azure-privatelink-classic/
├── README.md
└── tf/
    ├── main.tf                      # Shared locals (prefix, DBFS name, optional tags, dp_rg_*) and client config
    ├── azure.tf                     # Data plane resource group (create or reference existing)
    ├── versions.tf                  # Terraform and provider version constraints (azurerm, azapi, databricks, time)
    ├── providers.tf                 # Azure, azapi, and Databricks account provider configuration
    ├── variables.tf                 # Input variable definitions
    ├── terraform.tfvars.example     # Example variable values (copy to terraform.tfvars)
    ├── network.tf                   # Data plane VNet, NSG, subnets (CIDRs from variables)
    ├── databricks.tf                # DBFS access connector, workspace (VNet injection, DBFS storage firewall), optional metastore create/assign, workspace admin
    ├── dns_zones.tf                 # Private DNS zones (control plane + DBFS) and VNet links
    ├── pe_backend.tf                # Private endpoint for control plane (databricks_ui_api)
    ├── pe_dbfs.tf                   # Private endpoints for DBFS storage (dfs and blob)
    ├── ncc.tf                       # NCC config, binding, private endpoint rules (blob/dfs), auto-approve PE connections
    ├── unity_catalog.tf             # Optional catalog: access connector, private-only storage account (access connector allowed by resource instance rule), credential, external location, catalog
    ├── pe_uc.tf                     # Private endpoints for the catalog storage account (dfs and blob)
    ├── ncc_uc.tf                    # NCC private endpoint rules + auto-approval for the catalog storage account
    ├── cluster.tf                   # Optional UC-compatible single-node cluster
    └── outputs.tf                   # workspace, resource group, vnet, subnets
```

| File | Purpose |
|------|--------|
| **main.tf** | Azure client config data source; locals (prefix, dbfsname, tags from `var.tags`, dp_rg_name/id/location). |
| **azure.tf** | Data plane resource group (created or referenced via data source depending on create_data_plane_resource_group). |
| **versions.tf** | Terraform and provider version constraints (azurerm, azapi, databricks, time). |
| **providers.tf** | Azure, azapi, and Databricks account provider (subscription_id, account_id). Auth via Azure CLI or ARM_* / account-level env. |
| **variables.tf** | Input variables (naming, Azure, network including subnet CIDRs, NCC, optional `metastore_id`, tags) with validation. |
| **terraform.tfvars.example** | Example variable values; copy to `terraform.tfvars` and set subscription, VNet CIDR, subnet CIDRs, location, etc. |
| **network.tf** | Data plane VNet (address_space from cidr_dp); NSG; public, private, and Private Link subnets (CIDRs from subnet_workspace_cidrs and subnet_private_endpoint_cidr). |
| **databricks.tf** | `azurerm_databricks_access_connector` for DBFS; `azurerm_databricks_workspace` with `default_storage_firewall_enabled` and `access_connector_id` (Premium, VNet injection, named MRG, workspace UI public access enabled); optional metastore creation (`new_metastore_name`) and `databricks_metastore_assignment`; workspace admin assignment for `admin_user`; legacy Hive metastore access disabled (and default catalog set) when a metastore is assigned. |
| **dns_zones.tf** | Private DNS zones for control plane and DBFS (dfs/blob); VNet links. |
| **pe_backend.tf** | Private endpoint for Databricks control plane in the Private Link subnet. |
| **pe_dbfs.tf** | Private endpoints for DBFS storage (dfs and blob) in the Private Link subnet. |
| **ncc.tf** | NCC config, binding to workspace, private endpoint rules (blob then dfs with delay), and azapi auto-approval of PE connections on DBFS storage. |
| **unity_catalog.tf** | When `new_catalog` is true: access connector, storage account (resource instance rule for the access connector, then public network access disabled via azapi), container, container, role assignment, storage credential, external location, catalog. |
| **pe_uc.tf** | Private endpoints (dfs, blob) for the catalog storage account in the Private Link subnet, registered in the existing DBFS private DNS zones. |
| **ncc_uc.tf** | NCC private endpoint rules (blob then dfs with delay) for the catalog storage account and azapi auto-approval of the connections. |
| **cluster.tf** | Optional UC-compatible single-node cluster when `create_cluster` is true. |
| **outputs.tf** | Workspace URL/ID; resource group name/id; VNet name/id; public, private, and Private Link subnet IDs; NCC ID; Unity Catalog and cluster outputs. |

## Terraform template examples and more documentation

These templates are for reference and exploration and are not formally supported by Databricks with SLAs. Use them as examples and adapt to your environment.

- [Deploy with Private Link](https://github.com/databricks/terraform-databricks-examples/tree/main/examples/adb-with-private-link-standard)
- [Security Reference Architecture Template](https://github.com/databricks/terraform-databricks-sra/tree/main/azure)
- [Terraform Databricks provider documentation](https://registry.terraform.io/providers/databricks/databricks/latest/docs)
- [Configure a workspace with Private Link (classic)](https://learn.microsoft.com/en-us/azure/databricks/security/network/classic/private-link)
