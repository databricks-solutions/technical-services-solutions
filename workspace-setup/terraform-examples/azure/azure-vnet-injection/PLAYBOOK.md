# Deployment Playbook: Azure Databricks Workspace with VNet Injection

This playbook walks you through deploying an Azure Databricks workspace with VNet injection using the Terraform code provided in the `tf/` directory. Follow each step in order.

---

## Table of Contents

1. [What This Deploys](#1-what-this-deploys)
2. [Prerequisites](#2-prerequisites)
3. [Gather Required Information](#3-gather-required-information)
4. [Authenticate to Azure](#4-authenticate-to-azure)
5. [Configure Variables](#5-configure-variables)
6. [Deploy](#6-deploy)
7. [Verify the Deployment](#7-verify-the-deployment)
8. [Tear Down / Cleanup](#8-tear-down--cleanup)
9. [Troubleshooting](#9-troubleshooting)
10. [Additional Resources](#10-additional-resources)

---

## 1. What This Deploys

This Terraform project provisions a **Premium-tier** Azure Databricks workspace deployed into your own Virtual Network (VNet injection) with **Secure Cluster Connectivity** (no public IP on cluster nodes). The deployment supports two modes: creating a new VNet or injecting into an existing one.

### Resources Created


| Category            | Resources                                                                                                                     |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| **Resource Groups** | Workspace resource group; VNet resource group (if creating a new VNet); Azure-managed resource group for Databricks internals |
| **Networking**      | VNet (new or existing), public subnet, private subnet, Network Security Group (NSG), NAT Gateway with static public IP        |
| **Databricks**      | Premium workspace with VNet injection, Unity Catalog metastore (new or existing assignment), workspace admin user assignment  |


### Architecture at a Glance

```
Azure Subscription
│
├── Resource Group (workspace)
│   └── Databricks Workspace (Premium, no public IP)
│       └── Managed Resource Group (created by Azure)
│
└── Resource Group (VNet — new or existing)
    ├── Virtual Network
    │   ├── Public Subnet  (delegated to Databricks)
    │   └── Private Subnet (delegated to Databricks)
    ├── Network Security Group (associated with both subnets)
    ├── NAT Gateway (associated with both subnets)
    └── Static Public IP (attached to NAT Gateway)
```

### Key Security Characteristics

- **No public IPs** on cluster nodes (`no_public_ip = true`).
- **NAT Gateway** provides a single, stable egress IP for allowlisting.
- **Default outbound access disabled** on both subnets — all egress must go through the NAT Gateway.
- Both subnets are **delegated** to `Microsoft.Databricks/workspaces`.

---

## 2. Prerequisites

Before you begin, ensure you have the following:

### Tools


| Tool      | Minimum Version | Install Link                                                                                                                                                  |
| --------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Terraform | ~> 1.3          | [Install Terraform](https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli#install-terraform)                                        |
| Azure CLI | Latest          | [Mac](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-macos) / [Windows](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows) |


### Access & Permissions

- **Azure**: Contributor role on the target Azure subscription. Subscription-level access is required because Databricks provisioning creates resources in a separate managed resource group.
- **Databricks**: Account admin access to your Databricks account.
- The `admin_user` email you plan to use must already exist as a user in the Databricks account.

### Network Planning

Decide which deployment mode you will use:


| Mode              | When to Use                                                                                                        | Variable Setting          |
| ----------------- | ------------------------------------------------------------------------------------------------------------------ | ------------------------- |
| **New VNet**      | You want Terraform to create the VNet, subnets, and resource group for you.                                        | `create_new_vnet = true`  |
| **Existing VNet** | You already have a VNet and want to inject Databricks into it. The VNet and its resource group must already exist. | `create_new_vnet = false` |


In both cases:

- The VNet CIDR must be between `/16` and `/24`.
- You need two dedicated, non-overlapping subnets (public and private) that are **not used by other resources**. The subnets will be created by Terraform in both modes.

---

## 3. Gather Required Information

Collect the following values before starting. You will need them in Step 5.

### Azure


| Value               | Where to Find It                                                                               |
| ------------------- | ---------------------------------------------------------------------------------------------- |
| **Tenant ID**       | Azure Portal > Microsoft Entra ID > Overview, or run `az account show --query tenantId -o tsv` |
| **Subscription ID** | Azure Portal > Subscriptions, or run `az account show --query id -o tsv`                       |


### Databricks


| Value                                     | Where to Find It                                                                                      |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| **Account ID**                            | [Databricks Account Console](https://accounts.azuredatabricks.net/) > Settings > Account details      |
| **Admin user email**                      | The email of a user that already exists in the Databricks account                                     |
| **Existing metastore ID** (if applicable) | Account Console > Catalog > Metastore details. Leave empty if you want Terraform to create a new one. |


### Naming

Choose names for the following resources. These must be unique within your subscription/account:

- Resource group name (e.g., `rg-databricks-prod`)
- Workspace name (e.g., `databricks-workspace-prod`)
- Root storage account name — **lowercase letters and numbers only, 3-24 characters** (e.g., `dbaborootprod01`)
- VNet name (e.g., `vnet-databricks-prod`)
- VNet resource group name (e.g., `rg-vnet-databricks-prod`)
- Managed resource group name (optional — Azure will auto-generate if not provided)
- New metastore name (only if creating a new metastore)

### Network CIDRs

Plan your address space. Example:


| Parameter           | Example Value |
| ------------------- | ------------- |
| VNet CIDR           | `10.0.0.0/16` |
| Public subnet CIDR  | `10.0.1.0/24` |
| Private subnet CIDR | `10.0.2.0/24` |


The subnet CIDRs must fall within the VNet CIDR range and must not overlap with each other.

---

## 4. Authenticate to Azure

Open a terminal and navigate to the `workspace-setup/terraform-examples/azure/azure-vnet-injection/tf/` directory:

```sh
cd ./workspace-setup/terraform-examples/azure/azure-vnet-injection/tf/
```

### Interactive Login (recommended for first-time deployment)

```sh
az login
```

This opens a browser window for authentication. If you have multiple subscriptions, set the correct one:

```sh
az account set --subscription "<your-subscription-id>"
```

Verify your active subscription:

```sh
az account show
```

### Service Principal Login (for CI/CD pipelines)

If you are running this from an automated pipeline, authenticate with a service principal:

```sh
az login --service-principal -u <appId> -p <password> --tenant <tenantId>
```

See the [README](README.md) for detailed instructions on creating a service principal.

---

## 5. Configure Variables

### 5.1 Create Your Variables File

Copy the example file:

```sh
cp terraform.tfvars.example terraform.tfvars
```

### 5.2 Edit the Variables

Open `terraform.tfvars` in your editor and fill in every value. Below are two complete examples for the two deployment modes.

#### Example A: Creating a New VNet

```hcl
# Azure Configuration
tenant_id             = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
azure_subscription_id = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
tags = {
  "Owner"       = "Jane Doe"
  "Environment" = "Production"
}

# Databricks Workspace Configuration
resource_group_name         = "rg-databricks-prod"
workspace_name              = "databricks-workspace-prod"
admin_user                  = "jane.doe@company.com"
root_storage_name           = "daborootprod01"
location                    = "westeurope"
databricks_account_id       = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
existing_metastore_id       = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
new_metastore_name          = ""
managed_resource_group_name = null

# Network Configuration — new VNet
create_new_vnet         = true
vnet_name               = "vnet-databricks-prod"
vnet_resource_group_name = "rg-vnet-databricks-prod"
cidr                    = "10.0.0.0/16"
subnet_public_cidr      = "10.0.1.0/24"
subnet_private_cidr     = "10.0.2.0/24"
```

#### Example B: Using an Existing VNet

```hcl
# Azure Configuration
tenant_id             = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
azure_subscription_id = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
tags = {
  "Owner"       = "Jane Doe"
  "Environment" = "Production"
}

# Databricks Workspace Configuration
resource_group_name         = "rg-databricks-prod"
workspace_name              = "databricks-workspace-prod"
admin_user                  = "jane.doe@company.com"
root_storage_name           = "daborootprod01"
location                    = "westeurope"
databricks_account_id       = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
existing_metastore_id       = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
new_metastore_name          = ""
managed_resource_group_name = null

# Network Configuration — existing VNet
create_new_vnet          = false
vnet_name                = "my-existing-vnet"
vnet_resource_group_name = "my-existing-vnet-rg"
cidr                     = "10.0.0.0/16"
subnet_public_cidr       = "10.0.10.0/24"
subnet_private_cidr      = "10.0.11.0/24"
```

> **Note on metastore configuration:** If `existing_metastore_id` is left empty (`""`), Terraform will create a new metastore using `new_metastore_name`. If you provide an existing metastore ID, `new_metastore_name` is ignored. Most regions already have a metastore — check the Account Console first.

### 5.3 Variable Reference


| Variable                      | Required | Default       | Description                                                                                                             |
| ----------------------------- | -------- | ------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `tenant_id`                   | Yes      | —             | Your Azure Tenant ID                                                                                                    |
| `azure_subscription_id`       | Yes      | —             | Your Azure Subscription ID                                                                                              |
| `resource_group_name`         | Yes      | —             | Name of the resource group for the Databricks workspace                                                                 |
| `managed_resource_group_name` | No       | `null`        | Name of the managed resource group. Must differ from `resource_group_name`. If `null`, Azure generates one.             |
| `tags`                        | No       | `{}`          | Map of tags applied to all resources                                                                                    |
| `databricks_account_id`       | Yes      | —             | Your Databricks account ID (treated as sensitive)                                                                       |
| `workspace_name`              | Yes      | —             | Name of the Databricks workspace                                                                                        |
| `admin_user`                  | Yes      | —             | Email of the user to assign as workspace and metastore admin                                                            |
| `root_storage_name`           | Yes      | —             | Root storage account name. Lowercase letters and numbers only, 3-24 characters.                                         |
| `location`                    | Yes      | —             | Azure region ([supported regions](https://learn.microsoft.com/en-us/azure/databricks/resources/supported-regions))      |
| `existing_metastore_id`       | No       | `""`          | ID of an existing metastore. Leave empty to create a new one.                                                           |
| `new_metastore_name`          | No       | `""`          | Name for a new metastore. Only used when `existing_metastore_id` is empty. Alphanumeric, hyphens, and underscores only. |
| `create_new_vnet`             | No       | `true`        | `true` to create a new VNet; `false` to use an existing one                                                             |
| `vnet_name`                   | Yes      | —             | Name of the VNet (new or existing)                                                                                      |
| `vnet_resource_group_name`    | Yes      | —             | Resource group containing the VNet (created if new, must exist if existing)                                             |
| `cidr`                        | No       | `10.0.0.0/20` | CIDR block for the VNet (between /16 and /24)                                                                           |
| `subnet_public_cidr`          | Yes      | —             | CIDR for the public (host) subnet                                                                                       |
| `subnet_private_cidr`         | Yes      | —             | CIDR for the private (container) subnet                                                                                 |


---

## 6. Deploy

Run the following commands from the `tf/` directory:

### 6.1 Initialize Terraform

```sh
terraform init
```

This downloads the required providers (`azurerm ~> 4.50`, `databricks ~> 1.84`) and initializes the working directory. You should see **"Terraform has been successfully initialized"**.

### 6.2 Review the Plan

```sh
terraform plan
```

Review the output carefully. It will show you every resource that Terraform intends to create. Verify that:

- The correct subscription and region are being used.
- Resource names match your expectations.
- The number of resources to be created looks right (roughly 13-16 depending on whether you're creating a new VNet and metastore).

### 6.3 Apply

```sh
terraform apply
```

Terraform will display the plan again and prompt for confirmation. Type `yes` to proceed.

The deployment typically takes **10-15 minutes**. The most time-consuming step is the Databricks workspace provisioning itself.

When complete, Terraform will print the outputs, including your workspace URL.

---

## 7. Verify the Deployment

### 7.1 Check Terraform Outputs

```sh
terraform output workspace_url
terraform output databricks_workspace_id
terraform output nat_gateway_public_ip
```

All available outputs:


| Output                      | Description                                                             |
| --------------------------- | ----------------------------------------------------------------------- |
| `workspace_url`             | The URL of the deployed Databricks workspace                            |
| `databricks_workspace_id`   | The Azure resource ID of the workspace                                  |
| `nat_gateway_public_ip`     | The static public IP used for egress (useful for firewall allowlisting) |
| `vnet_id`                   | Azure resource ID of the VNet                                           |
| `public_subnet_id`          | Azure resource ID of the public subnet                                  |
| `private_subnet_id`         | Azure resource ID of the private subnet                                 |
| `nat_gateway_id`            | Azure resource ID of the NAT Gateway                                    |
| `security_group_id`         | Azure resource ID of the Network Security Group                         |
| `managed_resource_group_id` | Azure resource ID of the Databricks managed resource group              |


### 7.2 Access the Workspace

1. Open the `workspace_url` in your browser.
2. Log in with the credentials of the `admin_user` you configured.
3. Verify Unity Catalog is attached: navigate to **Catalog** in the left sidebar. You should see the metastore assigned to your workspace.

### 7.3 Validate Networking

To confirm VNet injection and Secure Cluster Connectivity are working:

1. Create a small test cluster in the workspace.
2. While the cluster is starting, navigate to the Azure Portal:
  - Open the VNet resource and verify both subnets show Databricks delegation.
  - Open the managed resource group — you should see Databricks-managed resources (disks, NICs) appearing without public IPs.
3. Once the cluster is running, check the NAT Gateway's metrics in the Azure Portal to confirm egress traffic is flowing through it.

### 7.4 Note the NAT Gateway IP

The `nat_gateway_public_ip` output provides the single egress IP for all outbound traffic from your Databricks clusters. Use this IP for:

- Firewall allowlisting on external data sources.
- Network security rules on downstream services.

---

## 8. Tear Down / Cleanup

To destroy all resources created by this Terraform project:

```sh
terraform destroy
```

Type `yes` when prompted. This will remove the workspace, networking resources, resource groups, and the metastore (if Terraform created it).

> **Warning:** This is irreversible. Ensure you have backed up any data, notebooks, or configurations from the workspace before destroying it.

> **Note:** If you manually created resources inside the managed resource group (or the workspace itself), `terraform destroy` may fail. Remove those resources manually first, then retry.

---

## 9. Troubleshooting

### "Managed resource group name should not be same as resource group name"

The `managed_resource_group_name` variable must differ from `resource_group_name`. Either choose a different name or set it to `null` to let Azure generate one.

### "root_storage_name can only contain lowercase letters and numbers"

The root storage account name has strict naming rules: only lowercase letters (`a-z`) and numbers (`0-9`), between 3 and 24 characters. No hyphens, underscores, or uppercase characters.

### Deployment fails at workspace creation with a VNet error

- Verify your VNet CIDR is between `/16` and `/24`.
- Ensure the public and private subnet CIDRs fall within the VNet CIDR and do not overlap.
- If using an existing VNet (`create_new_vnet = false`), confirm the VNet and its resource group already exist and you have the correct names.
- Ensure the subnets are not already in use by other services.

### "Error: retrieving User" or permission errors on the Databricks provider

- Confirm the `admin_user` email exists in the Databricks account (Account Console > User Management).
- Ensure your `databricks_account_id` is correct.
- Verify your Azure CLI session is authenticated and has the correct subscription set.

### Terraform state lock errors

If a previous `terraform apply` was interrupted, you may see state lock errors. Wait a few minutes for the lock to expire, or remove it manually:

```sh
terraform force-unlock <lock-id>
```

### Metastore assignment fails

- If providing `existing_metastore_id`, confirm the metastore ID is correct and belongs to the same region as your workspace.
- If creating a new metastore, ensure `new_metastore_name` is not empty and contains only alphanumeric characters, hyphens, and underscores.
- A region can only have one metastore. If one already exists, use `existing_metastore_id` instead of creating a new one.

---

## 10. Additional Resources

- [Azure Databricks VNet Injection Documentation](https://learn.microsoft.com/en-us/azure/databricks/security/network/classic/vnet-inject)
- [Secure Cluster Connectivity (No Public IP)](https://learn.microsoft.com/en-us/azure/databricks/security/network/classic/secure-cluster-connectivity)
- [Terraform Databricks Provider Documentation](https://registry.terraform.io/providers/databricks/databricks/latest/docs)
- [Terraform AzureRM Provider Documentation](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs)
- [Databricks Security Reference Architecture (Terraform)](https://github.com/databricks/terraform-databricks-sra/tree/main/azure)
- [Terraform Examples with Private Link](https://github.com/databricks/terraform-databricks-examples/tree/main/examples/adb-with-private-link-standard)
- [Azure Databricks Supported Regions](https://learn.microsoft.com/en-us/azure/databricks/resources/supported-regions)

