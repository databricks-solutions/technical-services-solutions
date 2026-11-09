# Azure VNet injection with User-Defined Catalog Workspace Setup Guide (with VNet deployment)

> [!NOTE]
> **This is the recommended, canonical Azure VNet injection template.** It supersedes the
> legacy [`azure-vnet-injection`](../azure-vnet-injection/) example, which is now deprecated.

This Terraform example deploys an Azure Databricks workspace with VNet Injection, Unity Catalog, and a user-defined catalog with an external location. It provisions the full networking stack (VNet, subnets, NSG, NAT Gateway), a Databricks workspace with Secure Cluster Connectivity (No Public IP), configures Unity Catalog with a storage credential, external location, and user-defined catalog backed by an Azure Storage Account, and creates a single-node Databricks cluster on the latest LTS runtime in standard (shared) access mode.

By default this deployment creates a new resource group and a new virtual network from scratch. It can also reuse an existing resource group (`create_resource_group = false`) and an existing VNet (`create_new_vnet = false`, with `vnet_name`, and `vnet_resource_group_name` if the VNet is not in the workspace resource group). When reusing a VNet the module looks it up and creates the delegated subnets, NSG, and NAT Gateway within it. The same options exist in `azure-privatelink-classic`.

### Important 
The difference between this deployment option and the standard option for azure-vnet-injection is the inclusion of a user-defined catalog and external location. The requirements and authentication procedures remain the same.

## Requirements

- Terraform is installed on your local machine: [link](https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli#install-terraform)
- Azure CLI is installed on your local machine: [Mac](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-macos?view=azure-cli-latest#install-with-homebrew) or [Windows](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows?view=azure-cli-latest&pivots=winget)
- Azure CLI configured with appropriate credentials
- Databricks account initialized: If this is your first time accessing Azure Databricks at the account level (and no account admin has been established yet), follow [this](https://learn.microsoft.com/en-us/azure/databricks/admin/admin-concepts#establish-first-account-admin) documentation to assign the first account admin.
- Databricks account admin access
- Contributor rights to your Azure subscription (Contributor rights on the resource group level are not sufficient, as Databricks provisioning creates resources in a separate managed resource group, which requires subscription-level access.)
- When using an existing metastore (i.e. `metastore_id` is set), the identity running Terraform (usually `admin_user`) must be able to create a storage credential, an external location and a catalog on it: `CREATE STORAGE CREDENTIAL`, `CREATE EXTERNAL LOCATION` and `CREATE CATALOG` on the metastore (not needed when `new_catalog = false`). A metastore admin can grant them, e.g. ``GRANT CREATE STORAGE CREDENTIAL ON METASTORE TO `<principal>`;`` and likewise for the other two. A new metastore created by this template (`new_metastore_name`) is owned by a `<name>-admins` group whose only member is `admin_user`, so run Terraform as `admin_user` in that case.

## Before you begin

Configuration values (subscription ID, VNet and subnet CIDRs, location, resource group behavior, and network options) are defined as variables. Copy `tf/terraform.tfvars.example` to `tf/terraform.tfvars` and set your values there. Terraform loads `terraform.tfvars` automatically. You can also use a file ending in `.auto.tfvars` or pass variables via the command line.

## Authenticate the Azure CLI

### Option 1: Interactive user login (for users)

```sh
az login
```

This command opens a browser for user authentication, and it is commonly referred to as U2M (User-to-machine) authentication. This command is sufficient for all operations in this document.

As a best practice, explicitly pin the Databricks provider to Azure CLI auth:

```sh
export DATABRICKS_AUTH_TYPE=azure-cli
```

### Option 2: Service principal login (for automation, CI/CD)

Choose this option if you want to deploy the Terraform script to a Git repository and integrate it into your CI/CD processes after completing this guide. It is the recommended approach for automation in non-interactive environments such as pipelines or scripts.

Steps to Create a Service Principal via Azure CLI:

1. Log in to Azure via Azure CLI

```sh
az login
```

This command opens a browser to authenticate your Azure user account.

2. (Optional) Choose the Target Subscription

If you have multiple subscriptions, set your target subscription:

```sh
az account set --subscription "<subscription-id>"
```

You can find your subscription ID with:

```sh
az account show
```

3. Create the Service Principal
Use the following command to create a service principal, specifying the name, role, and scope:

```sh
az ad sp create-for-rbac --name "<sp-name>" --role <role> --scopes /subscriptions/<subscription-id>
```

- `<sp-name>`: Desired service principal name.
- `<role>`: e.g. Contributor, Reader, Owner.
- `<subscription-id>`: Your Azure Subscription ID.

The command outputs JSON with appId, password, and tenant.

**Important**: Save the password (client secret) immediately; you cannot retrieve it later.

4. Use the Newly Created SP Credentials

You can now use the output values:
- `appId` for the username
- `password` as the client secret
- `tenant` as the tenant ID

For authentication in automation (like CI/CD or scripts), use:

```sh
az login --service-principal -u <appId> -p <password> --tenant <tenant>
```

For more information on creating a Service Principal, visit the [following link](https://learn.microsoft.com/en-us/cli/azure/azure-cli-sp-tutorial-1?view=azure-cli-latest&tabs=bash).


## What this Terraform code does

### Overview

The code provisions:

1. **Resource groups** – One resource group for the Databricks workspace and Unity Catalog resources (`resource_group_name`), created when `create_resource_group = true` (default) or looked up (must already exist, its region is used) when `false`. Networking uses the same group unless `vnet_resource_group_name` names a different one; that group is created when `create_new_vnet = true`, or must already exist when reusing a VNet.
2. **Virtual network** – When `create_new_vnet = true` (default), a new VNet is created with address space from `vnet_cidr`. When `create_new_vnet = false`, the existing VNet `vnet_name` (in `vnet_resource_group_name`, or the workspace resource group when that is empty) is used instead; it needs free address space for both subnet CIDRs. Either way it contains two subnets:
   - **Public subnet** – CIDR from `subnet_public_cidr`. Delegated to `Microsoft.Databricks/workspaces` for cluster host IPs.
   - **Private subnet** – CIDR from `subnet_private_cidr`. Delegated to `Microsoft.Databricks/workspaces` for cluster container IPs.
3. **Network security group (NSG)** – Attached to both public and private subnets.
4. **NAT Gateway** (`create_nat_gateway`, default `true`) – Standard SKU with a static Standard-SKU public IP, associated to both subnets for outbound connectivity (Secure Cluster Connectivity / No Public IP). Placed in the availability zone(s) from `nat_gateway_zones` (default `["1"]`).
5. **Databricks workspace** – Premium SKU, VNet-injected into the public/private subnets with No Public IP enabled. The workspace is named `workspace_name` (default `dbw-<resource_prefix>`), its managed resource group `managed_resource_group_name` (default `mrg-dbw-<resource_prefix>`), and root DBFS storage uses the storage account `root_storage_name` (default derived from `resource_prefix`, so it must be globally unique).
6. **Unity Catalog metastore** – Set `metastore_id` to assign an existing metastore, or `new_metastore_name` (plus `admin_user`) to create one with an admin group and owner assignment. The metastore is assigned to the workspace. With neither set, no metastore is assigned here and the catalog resources below cannot be created.
7. **Workspace access** – When `admin_user` is set, grants it ADMIN permissions on the workspace and `ALL PRIVILEGES` on the user-defined catalog, external location and storage credential.
8. **Managed identity and storage** _(when `new_catalog = true`, default)_ – An Azure Databricks Access Connector (system-assigned managed identity), a hardened storage account (TLS 1.2, infrastructure encryption, no public blob access) and container for the catalog, and a Storage Blob Data Contributor role assignment on the storage account. See [Unity Catalog storage security](#unity-catalog-storage-security).
9. **Storage credential** – A Unity Catalog storage credential backed by the managed identity.
10. **External location** – Points to the storage container using the storage credential.
11. **User-defined catalog** – A Unity Catalog catalog backed by the external location's storage.
12. **Single-node cluster (optional)** – Created only when `create_cluster = true` (default `false`). A UC-compatible single-node cluster in standard (shared) access mode, so workspace users can attach to it. No cluster policy is used; the template sets the latest LTS Databricks Runtime (via the `databricks_spark_version` data source), node type (`var.node_type_id`), idle auto-termination (`var.cluster_autotermination_minutes`, default `10`), access mode (constant `USER_ISOLATION`, shown as Standard/Shared in the UI), single-node (`is_single_node`), and a `ClusterType = TerraformDeploymentTesting` custom tag. The cluster is created after the metastore assignment and workspace admin permission so UC is fully wired up before it boots.

### Variables

Copy `terraform.tfvars.example` to `terraform.tfvars` in the `tf/` directory and set your values. Do not commit `terraform.tfvars` (it may contain sensitive data). Terraform automatically loads `terraform.tfvars`; for other file names use `-var-file`.

#### List of variables

| Variable | Description |
|----------|-------------|
| `azure_subscription_id` | **(Required)** Your Azure Subscription ID. |
| `create_resource_group` | **(Optional)** `true` (default) creates the workspace resource group; `false` reuses the existing group named `resource_group_name`, and its region is used. |
| `resource_group_name` | **(Required)** Name of the workspace resource group (workspace, access connector, catalog storage). Created when `create_resource_group` is `true`, otherwise it must already exist. |
| `resource_prefix` | **(Optional)** Prefix for Azure resource names, following the Azure CAF pattern `<abbreviation>-<resource_prefix>[-suffix]` (`vnet-…`, `nsg-…`, `snet-…-public`, `ng-…-nat`, `pip-…-nat`, `dbac-…-uc`) and the defaults of the names below. Must be 1–40 characters: a-z, 0-9, `-`, `.`. Default: `databricks-workspace`. |
| `managed_resource_group_name` | **(Optional)** Name of the Databricks managed resource group; must differ from `resource_group_name`. Default `""` uses `mrg-dbw-<resource_prefix>`. Changing it forces workspace replacement. Same variable as in `azure-privatelink-classic`. |
| `tags` | **(Optional)** Map of tags to assign to all resources. Default: `{}`. |
| `databricks_account_id` | **(Required)** Databricks account ID. Find it in the account console URL. |
| `workspace_name` | **(Optional)** Name of the Databricks workspace (3–30 characters: letters, numbers, `-`, `_`). Default `""` uses `dbw-<resource_prefix>`. Same variable as in `azure-privatelink-classic`. |
| `admin_user` | **(Optional)** Databricks account user (email) made workspace admin and granted `ALL PRIVILEGES` on the catalog, external location and storage credential. Required with `new_metastore_name` (becomes the only member of the metastore admins group), and run Terraform as this user in that case. Default `""`. |
| `root_storage_name` | **(Optional)** Root DBFS storage account name: lowercase letters and numbers, 3–24 characters, globally unique. Default `""` derives `dbfs` + up to 20 alphanumeric characters of `resource_prefix`. Same variable as in `azure-privatelink-classic`. |
| `new_catalog` | **(Optional)** Create the user-defined catalog stack (access connector, storage account, container, storage credential, external location, catalog). Requires a metastore (`metastore_id` or `new_metastore_name`). Default `true`. |
| `uc_storage_account_name` | **(Optional)** Catalog storage account name (3-24 chars, lowercase letters and numbers, globally unique). Default `""` derives `uc` + up to 22 alphanumeric characters of `resource_prefix`, which can collide — set it explicitly if so. |
| `uc_container_name` | **(Optional)** Container used as catalog storage root. Default `uc-catalog`. |
| `catalog_name` / `storage_credential_name` / `external_location_name` | **(Optional)** Unity Catalog object names. Defaults: `<resource_prefix>_catalog` (hyphens/dots become underscores), `<resource_prefix>-storage-credential`, `<resource_prefix>-external-location`. |
| `location` | **(Conditional)** Azure region for all resources (e.g. `eastus`). Required when `create_resource_group = true`; leave empty when reusing a resource group (its region is used). See [supported regions](https://learn.microsoft.com/en-us/azure/databricks/resources/supported-regions). |
| `metastore_id` | **(Optional)** UUID of an **existing** metastore to assign to the workspace (list with `databricks account metastores list`). Mutually exclusive with `new_metastore_name`. Default `""`. |
| `new_metastore_name` | **(Optional)** Name of a **new** metastore to create in the workspace region and assign; creates a `<name>-admins` group (owner) with `admin_user` as member. Mutually exclusive with `metastore_id`. Default `""`. |
| `create_cluster` | **(Optional)** Whether to create the single-node UC cluster. Requires a metastore. Default: `false`. |
| `node_type_id` | **(Optional)** Azure VM SKU used for the single-node UC cluster driver. Default: `Standard_DS3_v2`. |
| `cluster_autotermination_minutes` | **(Optional)** Idle minutes before the single-node cluster auto-terminates. Default: `10`. Minimum: `10`. |
| `create_new_vnet` | **(Optional)** Whether to create a new VNet (`true`, default) or use an existing one (`false`). When `false`, set `vnet_name` to the existing VNet. The template still creates its own subnets and NSG in it. |
| `vnet_name` | **(Conditional)** Name of the virtual network. Required when `create_new_vnet = false` (the existing VNet to reuse); ignored when creating a new VNet. |
| `vnet_resource_group_name` | **(Optional)** Resource group for the VNet and networking resources (subnets, NSG, NAT gateway). Empty (default), or equal to `resource_group_name`, uses the workspace resource group. A different name is created when `create_new_vnet = true`; when reusing a VNet it must be the group that holds it. |
| `vnet_cidr` | **(Conditional)** CIDR for the VNet address space (e.g. `10.0.0.0/20`). Required when `create_new_vnet = true`; ignored when reusing an existing VNet. |
| `subnet_public_cidr` | **(Required)** CIDR for the public (host) subnet. Must be within the VNet. |
| `subnet_private_cidr` | **(Required)** CIDR for the private (container) subnet. Must be within the VNet. |
| `create_nat_gateway` | **(Optional)** Create the NAT gateway for outbound access. Default `true`. `false` is rejected by this template: without Private Link, clusters reach the Databricks control plane only through NAT and would not launch. To deploy without NAT use `azure-privatelink-classic`. |
| `nat_gateway_zones` | **(Optional)** Availability zone(s) for the NAT gateway and its public IP. Azure NAT gateway is a zonal resource, so provide at most one zone. Default: `["1"]`. Use `[]` for regions without availability-zone support. For zone-redundant egress, deploy one NAT gateway per zone (not covered by this example). |

### Renamed and removed variables

If you are updating an existing `terraform.tfvars`, change these before the next `terraform plan`:

| Old | New | Notes |
|-----|-----|-------|
| `existing_metastore_id` | `metastore_id` | Leaving the old name set fails with an error (it would otherwise unassign the metastore). |
| `cidr` | `vnet_cidr` | No default any more; required when `create_new_vnet = true`. |
| `vnet_resource_group_name` (required, must differ) | `vnet_resource_group_name` (optional) | Existing values keep working. Empty now means the workspace resource group. |
| `workspace_name` (required) and `root_storage_name` (required) | `workspace_name` and `root_storage_name` (both optional) | Resource names now derive from the new `resource_prefix` using the Azure CAF pattern `<abbreviation>-<resource_prefix>[-suffix]` (it used to be `<workspace_name>-<suffix>`). The renamed resources are replaced on an existing deployment, so redeploy rather than upgrade in place. |
| `tenant_id` | _(removed)_ | The tenant is taken from the logged-in identity. Set `ARM_TENANT_ID` if your CLI session defaults to another tenant. |

The workspace resource group, NAT gateway resources and UC catalog resources now use `count`; `moved` blocks keep existing deployments from being replaced. Read the plan: it should report the resources as moved, not destroyed and re-created.

### Unity Catalog storage security

The UC external-location storage account is created with TLS 1.2 minimum, infrastructure (double) encryption, and public blob access disabled. This is a VNet-injection (non-Private Link) example, so the account keeps its public endpoint. For production, restrict it with an [Azure Storage account firewall](https://learn.microsoft.com/en-us/azure/storage/common/storage-network-security) (allowlist your networks and enable trusted-service access for the Databricks access connector).

> **Note:** `infrastructure_encryption_enabled` is applied at storage-account creation only. Enabling it on an account that already exists from a previous deploy forces the account to be replaced — plan a migration for existing state, or accept the recreation on a throwaway sandbox.

### Provider authentication

The `databricks` providers do not pin `auth_type`, so authentication is auto-detected: Azure CLI (`az login`) for interactive use, or a service principal via `ARM_CLIENT_ID` / `ARM_CLIENT_SECRET` / `ARM_TENANT_ID` for CI/CD (see [Option 2](#option-2-service-principal-login-for-automation-cicd) above).

## Deploy

```bash
# Initialize Terraform
terraform init

# Review the execution plan
terraform plan

# Apply the configuration
terraform apply
```

Occasionally, you'll be asked to confirm certain actions; type yes when prompted. The deployment typically takes 10-15 minutes. Once the execution finishes, the terminal will output the URL of the created workspace.

## Access Your Workspace

After successful deployment:
```bash
# Get the workspace URL
terraform output workspace_url

# Get the workspace ID
terraform output workspace_id

# Get the cluster ID created by Terraform (only when create_cluster = true)
terraform output cluster_id
```

Navigate to the workspace URL and log in with your Databricks credentials. The pre-created single-node cluster is visible under **Compute**.

## Validation

To verify the deployment succeeded:

1. **Terraform outputs** – From the `tf/` directory, run `terraform output` and confirm `workspace_url`, `workspace_id`, and `vnet_id` are present and non-empty. `cluster_id` is populated only when `create_cluster = true` (otherwise it is `null`).
2. **Azure portal** – In your subscription, check that the resource group, VNet, subnets, NAT gateway, and the Databricks workspace exist and are in "Succeeded" or "Ready" state.
3. **Workspace access** – Open `terraform output -raw workspace_url` in a browser and sign in (public access is always enabled).
4. **Single-node cluster** (only when `create_cluster = true`) – Under **Compute**, locate the cluster named `<resource_prefix>-uc-cluster`. Confirm the access mode is **Standard** (shared), runtime is the latest LTS, node type matches `var.node_type_id`, auto-termination matches `var.cluster_autotermination_minutes` (default `10`), and the cluster carries the `ClusterType = TerraformDeploymentTesting` tag. Start the cluster and wait for "Running".

## Clean-up

To destroy all resources created by this scenario:

```bash
cd tf
terraform destroy
```

Type `yes` when prompted. Destruction can take several minutes. 


## Troubleshooting

| Issue | Possible cause | Solution |
|-------|----------------|----------|
| `az login` or provider auth fails | Azure CLI not installed or not logged in | Install Azure CLI, run `az login`, or set `ARM_CLIENT_ID`, `ARM_CLIENT_SECRET`, `ARM_TENANT_ID`, `ARM_SUBSCRIPTION_ID` for service principal. |
| `terraform plan` fails on subscription or permission | Wrong subscription or insufficient rights | Run `az account set --subscription "<id>"` and ensure the identity has Contributor at subscription scope. |
| Subnet or delegation errors | CIDR too small or delegation conflict | Ensure `vnet_cidr` encompasses both subnets. Set `subnet_public_cidr` and `subnet_private_cidr` to non-overlapping CIDRs within the VNet (e.g. /24 each within a /20 VNet). |
| `Resource group already exists` on `create_resource_group` | The group named `resource_group_name` already exists | Set `create_resource_group = false` to reuse it, or choose another name. |
| `create_nat_gateway = false is not supported by this template` | NAT disabled without Private Link | Set `create_nat_gateway = true`, or use the `azure-privatelink-classic` template for deployments without NAT. |
| NAT Gateway or outbound connectivity issues | Cluster nodes cannot reach the control plane | Verify the NAT Gateway is associated to both subnets and has a public IP. Check that NSG rules allow outbound traffic on port 443. |

> **Note:** Terraform occasionally encounters transient errors during first-time deployments — particularly when cloud resources take a moment to fully propagate after being created. If you hit an unexpected error on `terraform apply`, a second run will often resolve it without any changes to the configuration.

## File Structure

This project uses a flat, organized structure with purpose-specific files instead of a monolithic `main.tf`:

```
tf/
├── azure.tf                    # Azure resources
├── cluster.tf                  # UC-compatible single-node cluster
├── databricks.tf               # Databricks workspace
├── network.tf                  # VNet, subnets, and networking
├── outputs.tf                  # All output values
├── providers.tf                # Provider configurations
├── terraform.tfvars.example    # Configuration template
├── variables.tf                # All input variable definitions
├── versions.tf                 # Version of the providers
├── unity_catalog.tf            # Creates user-defined catalog and external location
```

| File | Purpose |
|------|--------|
| **azure.tf** | Resource group for the Databricks workspace and Unity Catalog resources. |
| **cluster.tf** | `databricks_spark_version` (latest LTS) data source and the `databricks_cluster` resource (standard/shared access mode, single node, no cluster policy). Sets node type, Spark version, auto-termination minutes, and the `ClusterType` tag. Depends on metastore assignment and workspace admin permission. |
| **databricks.tf** | `azurerm_databricks_workspace` (Premium, VNet injection, No Public IP); metastore creation or assignment; workspace admin permissions; metastore owner group. |
| **network.tf** | VNet and its resource group — created when `create_new_vnet = true`, or looked up via data sources when `create_new_vnet = false` (BYO existing VNet); NSG; public and private subnets (CIDRs from `subnet_public_cidr` and `subnet_private_cidr`); NAT Gateway with public IP and subnet associations. |
| **providers.tf** | Azure and Databricks providers (workspace-level via workspace URL, account-level via accounts endpoint). Auth via Azure CLI. |
| **variables.tf** | Input variables (Azure config, Databricks config, network CIDRs, metastore options) with validation. |
| **terraform.tfvars.example** | Example variable values; copy to `terraform.tfvars` and set subscription, VNet CIDR, subnet CIDRs, location, etc. |
| **versions.tf** | Terraform and provider version constraints (azurerm, databricks). |
| **unity_catalog.tf** | Access connector (managed identity), storage account and container, role assignment, storage credential, external location, and user-defined catalog. |
| **outputs.tf** | Workspace URL/ID; cluster ID; managed resource group ID; VNet ID; public and private subnet IDs; NSG ID; NAT gateway ID and public IP; Unity Catalog metastore ID, catalog, external location and storage credential names, and the catalog storage account name. |

**Note:** There is no `main.tf` file in this project. Instead, resources are organized into descriptive, purpose-specific files. 

Terraform will automatically load all `.tf` files in the directory, so the absence of `main.tf` doesn't affect functionality.


## Terraform template examples and more documentation:

Keep in mind that the git code is not always up to date. You should use these templates as an example and not directly copy and paste. Please note that the code in the template projects is provided for your exploration only and is not formally supported by Databricks with Service Level Agreements (SLAs). They are provided AS-IS, and we do not make any guarantees of any kind.

- [Deploy with Private Link](https://github.com/databricks/terraform-databricks-examples/tree/main/examples/adb-with-private-link-standard)
- [Security Reference Architecture Template](https://github.com/databricks/terraform-databricks-sra/tree/main/azure)
    - This is a template that adheres to the best security practices we recommend.
- [Terraform Databricks provider documentation](https://registry.terraform.io/providers/databricks/databricks/latest/docs)
- [Configure a workspace with VNet injection](https://learn.microsoft.com/en-us/azure/databricks/security/network/classic/vnet-inject)

