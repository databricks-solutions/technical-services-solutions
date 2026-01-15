# Azure VNet injection Workspace Setup Guide (with VNet deployment)

## Requirements

- Terraform is installed on your local machine: [link](https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli#install-terraform)
- Azure CLI is installed on your local machine: [Mac](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-macos?view=azure-cli-latest#install-with-homebrew) or [Windows](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows?view=azure-cli-latest&pivots=winget)
- Azure CLI configured with appropriate credentials
- Databricks account created
- Databricks account admin access
- Contributor rights to your Azure subscription (Contributor rights on the resource group level are not sufficient, as Databricks provisioning creates resources in a separate managed resource group, which requires subscription-level access.)

## Before you begin

In this deployment, we define key configuration values, such as subscription ID, resource group location, CIDR block, asset naming, and others, as variables. This keeps our code organized and makes it easy to adjust settings without changing the core infrastructure definitions. You can choose to define these variables directly or reference them from a separate configuration file for better modularity. In this document, we will create a configuration file to store them separately (`terraform.tfvars.example`).

## Authenticate the Azure CLI

### Option 1: Interactive user login (for users)

```sh
az login
```

This command opens a browser for user authentication, and it is commonly referred to as U2M (User-to-machine) authentication. This command is sufficient for all operations in this document.

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


## General Requirements for VNet
Before proceeding, ensure your VNet meets the following requirements:

- The address space for the VNet must use a CIDR block between /16 and /24.

## Variables

If you want Terraform to automatically load values for variables from a file, the file must be named either `terraform.tfvars`, `terraform.tfvars.json`, or end with `.auto.tfvars` or `.auto.tfvars.json`. If your file has a custom name (like `random_name.tfvars`), you must provide it explicitly using the `-var-file` flag when running Terraform commands.

You can use the `terraform.tfvars.example` file as a base for your variables. Leter renaming this file to `terraform.tfvars` will automatically load the values for the variables.

### List of variables

- tenant_id
    - You Azure tenant ID
- azure_subscription_id
    - Your Azure Subscription ID
- resource_group_name
    - The name of the resource group where the Databricks Workspace will be deployed
- tags
    - A map of tags to assign to the resources
- databricks_account_id
    - ID of the Databricks Account
- workspace_name
    - The name of the Databricks workspace
- admin_user
    - The email of the user to assign admin access to the workspace and the new metastore
- root_storage_name
    - The name of the root storage account. Can only consist of lowercase letters and numbers, and must be between 3 and 24 characters long.
- location
    - The Azure region to deploy the workspace to. See [supported regions](https://learn.microsoft.com/en-us/azure/databricks/resources/supported-regions).
- existing_metastore_id
    - The ID of the existing metastore. Leave empty to create a new metastore.
- new_metastore_name
    - The name of the new metastore.
- create_new_vnet
    - Whether to create a new VNet or use an existing one
- vnet_name
    - The name of the virtual network
- vnet_resource_group_name
    - The name of the VNet resource group
- cidr
    - The CIDR address of the virtual network
- subnet_public_cidr
    - The CIDR address of the first subnet
- subnet_private_cidr
    - The CIDR address of the second subnet
- managed_resource_group_name
    - The name of the managed resource group


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
```

Navigate to the workspace URL and log in with your Databricks credentials.

## File Structure

This project uses a flat, organized structure with purpose-specific files instead of a monolithic `main.tf`:

```
tf/
├── azure.tf                    # Azure resources
├── databricks.tf               # Databricks workspace
├── network.tf                  # VNet, subnets, and networking
├── outputs.tf                  # All output values
├── providers.tf                # Provider configurations
├── terraform.tfvars.example    # Configuration template
├── variables.tf                # All input variable definitions
├── versions.tf                 # Version of the providers
```

**Note:** There is no `main.tf` file in this project. Instead, resources are organized into descriptive, purpose-specific files. 

Terraform will automatically load all `.tf` files in the directory, so the absence of `main.tf` doesn't affect functionality.


## Terraform template examples and more documentation:

Keep in mind that the git code is not always up to date. You should use these templates as an example and not directly copy and paste. Please note that the code in the template projects is provided for your exploration only and is not formally supported by Databricks with Service Level Agreements (SLAs). They are provided AS-IS, and we do not make any guarantees of any kind.

- [Deploy with Private Link](https://github.com/databricks/terraform-databricks-examples/tree/main/examples/adb-with-private-link-standard)
- [Security Reference Architecture Template](https://github.com/databricks/terraform-databricks-sra/tree/main/azure)
    - This is a template that adheres to the best security practices we recommend.
- [Terraform Databricks provider documentation](https://registry.terraform.io/providers/databricks/databricks/latest/docs)
- [Configure a workspace with VNet injection](https://learn.microsoft.com/en-us/azure/databricks/security/network/classic/vnet-inject)

