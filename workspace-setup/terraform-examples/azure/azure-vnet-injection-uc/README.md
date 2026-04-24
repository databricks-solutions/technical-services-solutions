# Azure VNet injection with User-Defined Catalog Workspace Setup Guide (with VNet deployment)

This Terraform example deploys an Azure Databricks workspace with VNet Injection, Unity Catalog, and a user-defined catalog with an external location. It provisions the full networking stack (VNet, subnets, NSG, NAT Gateway), a Databricks workspace with Secure Cluster Connectivity (No Public IP), configures Unity Catalog with a storage credential, external location, and user-defined catalog backed by an Azure Storage Account, and creates a single-node Databricks cluster on the latest LTS runtime governed by the built-in **Personal Compute** cluster policy.

It is important to note that this deployment creates a new virtual network from scratch and currently does not support using an existing VNet.

### Important 
The difference between this deployment option and the standard option for azure-vnet-injection is the inclusion of a user-defined catalog and external location. The requirements and authentication procedures remain the same.

## Requirements

- Terraform is installed on your local machine: [link](https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli#install-terraform)
- Azure CLI is installed on your local machine: [Mac](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-macos?view=azure-cli-latest#install-with-homebrew) or [Windows](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows?view=azure-cli-latest&pivots=winget)
- Azure CLI configured with appropriate credentials
- Databricks account created
- Databricks account admin access
- Contributor rights to your Azure subscription (Contributor rights on the resource group level are not sufficient, as Databricks provisioning creates resources in a separate managed resource group, which requires subscription-level access.)
- When using an existing metastore (i.e. `existing_metastore_id` is set), the `admin_user` must have the `CREATE EXTERNAL LOCATION` privilege on the metastore. This is required to create the external location backing the user-defined catalog. New metastores created by this module grant the necessary privileges automatically.

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

1. **Resource groups** – Two resource groups: one for the Databricks workspace and Unity Catalog resources (`resource_group_name`), and a separate one for the VNet and networking resources (`vnet_resource_group_name`).
2. **Virtual network** – A VNet with address space from `cidr`, containing two subnets:
   - **Public subnet** – CIDR from `subnet_public_cidr`. Delegated to `Microsoft.Databricks/workspaces` for cluster host IPs.
   - **Private subnet** – CIDR from `subnet_private_cidr`. Delegated to `Microsoft.Databricks/workspaces` for cluster container IPs.
3. **Network security group (NSG)** – Attached to both public and private subnets.
4. **NAT Gateway** – With a static public IP, associated to both subnets for outbound connectivity (Secure Cluster Connectivity / No Public IP).
5. **Databricks workspace** – Premium SKU, VNet-injected into the public/private subnets with No Public IP enabled. Root DBFS storage uses a named storage account (`root_storage_name`).
6. **Unity Catalog metastore** – Either creates a new metastore (when `existing_metastore_id` is empty) with an admin group and owner assignment, or uses an existing one. The metastore is assigned to the workspace.
7. **Workspace access** – Grants ADMIN permissions to the specified `admin_user` on the workspace.
8. **Managed identity and storage** – An Azure Databricks Access Connector (system-assigned managed identity), a storage account and container for the catalog, and a Storage Blob Data Contributor role assignment on the storage account.
9. **Storage credential** – A Unity Catalog storage credential backed by the managed identity.
10. **External location** – Points to the storage container using the storage credential.
11. **User-defined catalog** – A Unity Catalog catalog backed by the external location's storage.
12. **Single-node cluster** – A UC-compatible cluster attached to the built-in **Personal Compute** policy, which enforces Single User access mode, the single-node profile, and other UC-safe defaults. Overrides set by this template: latest LTS Databricks Runtime (via the `databricks_spark_version` data source), node type (`var.node_type_id`), idle auto-termination (`var.autotermination_minutes`, default `10`), and a `ClusterType = TerraformDeploymentTesting` custom tag. The cluster is created after the metastore assignment and workspace admin permission so UC is fully wired up before it boots. Single-user ownership is set by the policy to whoever runs `terraform apply`.

### Variables

Copy `terraform.tfvars.example` to `terraform.tfvars` in the `tf/` directory and set your values. Do not commit `terraform.tfvars` (it may contain sensitive data). Terraform automatically loads `terraform.tfvars`; for other file names use `-var-file`.

#### List of variables

| Variable | Description |
|----------|-------------|
| `tenant_id` | **(Required)** Your Azure Tenant ID. |
| `azure_subscription_id` | **(Required)** Your Azure Subscription ID. |
| `resource_group_name` | **(Required)** The name of the resource group for the Databricks workspace and UC resources. |
| `managed_resource_group_name` | **(Optional)** The name of the Databricks managed resource group. If `null`, Azure generates one automatically. Must differ from `resource_group_name`. |
| `tags` | **(Optional)** Map of tags to assign to all resources. Default: `{}`. |
| `databricks_account_id` | **(Required)** Databricks account ID. Find it in the account console URL. |
| `workspace_name` | **(Required)** The name of the Databricks workspace. |
| `admin_user` | **(Required)** Email of the user to assign admin access to the workspace and metastore. |
| `root_storage_name` | **(Required)** Root DBFS storage account name. Lowercase letters and numbers only, 3-24 characters. |
| `uc_storage_name` | **(Required)** Storage account name for the Unity Catalog external location. Lowercase letters and numbers only, 3-24 characters. Must be globally unique. |
| `location` | **(Required)** Azure region for all resources (e.g. `eastus`). See [supported regions](https://learn.microsoft.com/en-us/azure/databricks/resources/supported-regions). |
| `existing_metastore_id` | **(Optional)** ID of an existing metastore. Leave empty to create a new one. When set, `admin_user` must have the `CREATE EXTERNAL LOCATION` privilege on that metastore. |
| `new_metastore_name` | **(Optional)** Name for the new metastore. Required when `existing_metastore_id` is empty. |
| `node_type_id` | **(Optional)** Azure VM SKU used for the single-node UC cluster driver. Default: `Standard_DS3_v2`. |
| `autotermination_minutes` | **(Optional)** Idle minutes before the single-node cluster auto-terminates. Default: `10`. Minimum: `10`. Must fit within the Personal Compute policy's allowed range in your workspace. |
| `vnet_name` | **(Required)** Name of the virtual network. |
| `vnet_resource_group_name` | **(Required)** Name of the resource group for the VNet and networking resources. Must differ from `resource_group_name`. |
| `cidr` | **(Optional)** CIDR for the VNet address space. Default: `10.0.0.0/20`. |
| `subnet_public_cidr` | **(Required)** CIDR for the public (host) subnet. Must be within the VNet. |
| `subnet_private_cidr` | **(Required)** CIDR for the private (container) subnet. Must be within the VNet. |

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

# Get the cluster ID created by Terraform
terraform output cluster_id
```

Navigate to the workspace URL and log in with your Databricks credentials. The pre-created single-node cluster is visible under **Compute**.

## Validation

To verify the deployment succeeded:

1. **Terraform outputs** – From the `tf/` directory, run `terraform output` and confirm `workspace_url`, `workspace_id`, `cluster_id`, and `vnet_id` are present and non-empty.
2. **Azure portal** – In your subscription, check that the resource group, VNet, subnets, NAT gateway, and the Databricks workspace exist and are in "Succeeded" or "Ready" state.
3. **Workspace access** – Open `terraform output -raw workspace_url` in a browser and sign in (public access is always enabled).
4. **Single-node cluster** – Under **Compute**, locate the cluster named `<workspace_name>-uc-cluster`. Confirm the **Policy** field is `Personal Compute`, access mode is **Single user**, runtime is the latest LTS, node type matches `var.node_type_id`, auto-termination matches `var.autotermination_minutes` (default `10`), and the cluster carries the `ClusterType = TerraformDeploymentTesting` tag. Start the cluster and wait for "Running".

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
| Subnet or delegation errors | CIDR too small or delegation conflict | Ensure `cidr` encompasses both subnets. Set `subnet_public_cidr` and `subnet_private_cidr` to non-overlapping CIDRs within the VNet (e.g. /24 each within a /20 VNet). |
| Resource group name conflict | `vnet_resource_group_name` is the same as `resource_group_name` | These must be different values. Terraform creates two separate resource groups; using the same name causes a conflict on the second create. |
| NAT Gateway or outbound connectivity issues | Cluster nodes cannot reach the control plane | Verify the NAT Gateway is associated to both subnets and has a public IP. Check that NSG rules allow outbound traffic on port 443. |

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
| **cluster.tf** | `databricks_spark_version` (latest LTS) and `databricks_cluster_policy` ("Personal Compute") data sources, plus the `databricks_cluster` resource attached to the Personal Compute policy. Overrides node type, Spark version, auto-termination minutes, and the `ClusterType` tag. Depends on metastore assignment and workspace admin permission. |
| **databricks.tf** | `azurerm_databricks_workspace` (Premium, VNet injection, No Public IP); metastore creation or assignment; workspace admin permissions; metastore owner group. |
| **network.tf** | VNet resource group; VNet (address_space from `cidr`); NSG; public and private subnets (CIDRs from `subnet_public_cidr` and `subnet_private_cidr`); NAT Gateway with public IP and subnet associations. |
| **providers.tf** | Azure and Databricks providers (workspace-level via workspace URL, account-level via accounts endpoint). Auth via Azure CLI. |
| **variables.tf** | Input variables (Azure config, Databricks config, network CIDRs, metastore options) with validation. |
| **terraform.tfvars.example** | Example variable values; copy to `terraform.tfvars` and set subscription, tenant, VNet CIDR, subnet CIDRs, location, etc. |
| **versions.tf** | Terraform and provider version constraints (azurerm, databricks). |
| **unity_catalog.tf** | Access connector (managed identity), storage account and container, role assignment, storage credential, external location, and user-defined catalog. |
| **outputs.tf** | Workspace URL/ID; cluster ID; managed resource group ID; VNet ID; public and private subnet IDs; NSG ID; NAT gateway ID and public IP; catalog and external location names. |

**Note:** There is no `main.tf` file in this project. Instead, resources are organized into descriptive, purpose-specific files. 

Terraform will automatically load all `.tf` files in the directory, so the absence of `main.tf` doesn't affect functionality.


## Terraform template examples and more documentation:

Keep in mind that the git code is not always up to date. You should use these templates as an example and not directly copy and paste. Please note that the code in the template projects is provided for your exploration only and is not formally supported by Databricks with Service Level Agreements (SLAs). They are provided AS-IS, and we do not make any guarantees of any kind.

- [Deploy with Private Link](https://github.com/databricks/terraform-databricks-examples/tree/main/examples/adb-with-private-link-standard)
- [Security Reference Architecture Template](https://github.com/databricks/terraform-databricks-sra/tree/main/azure)
    - This is a template that adheres to the best security practices we recommend.
- [Terraform Databricks provider documentation](https://registry.terraform.io/providers/databricks/databricks/latest/docs)
- [Configure a workspace with VNet injection](https://learn.microsoft.com/en-us/azure/databricks/security/network/classic/vnet-inject)

