# AWS Serverless Workspace Setup Guide

This Terraform example deploys a Databricks workspace on AWS in serverless compute mode with Unity Catalog. It does not create or attach a customer-managed VPC or Network Connectivity Configuration (NCC). The example creates the workspace, assigns a new or existing Unity Catalog metastore, and can optionally create a user-defined catalog with its own S3 bucket, IAM role, storage credential, and external location.

For private connectivity from serverless compute to AWS resources, use [`aws-serverless-ncc`](../aws-serverless-ncc/) instead.

## Requirements

- Terraform is installed on your local machine (version ~> 1.3): [link](https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli#install-terraform)
- AWS CLI is installed and configured with appropriate credentials
- Databricks account created (E2 account) with serverless workspaces enabled
- Databricks account-admin service principal with OAuth M2M credentials
- AWS permissions to create IAM and S3 resources when `new_catalog = true`
- When using an existing metastore, the Terraform service principal must be able to create storage credentials and external locations on that metastore

## Before you begin

Configuration values are defined as Terraform variables. Copy `tf/terraform.tfvars.example` to `tf/terraform.tfvars` and set the Databricks account ID, AWS account ID, region, and metastore options. Terraform loads `terraform.tfvars` automatically.

By default, this example creates a user-defined catalog. Set `new_catalog = false` when only the workspace and metastore assignment are required.

## Authenticate

### AWS Authentication

#### Option 1: Environment variables

```sh
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_SESSION_TOKEN="your-session-token" # If using temporary credentials
```

#### Option 2: AWS CLI profile

```sh
export AWS_PROFILE="your-profile"
```

#### Option 3: AWS SSO login

```sh
aws sso login --profile your-profile
```

### Databricks Authentication

Use an account-admin service principal for account-level operations:

```sh
export DATABRICKS_CLIENT_ID="your-client-id"
export DATABRICKS_CLIENT_SECRET="your-client-secret"
```

Do not put credentials in `terraform.tfvars`. For more information, see the [Databricks service principal documentation](https://docs.databricks.com/en/dev-tools/service-principals.html).

## What this Terraform code does

### Overview

The code provisions:

1. **Databricks workspace** -- An E2 workspace with `compute_mode = "SERVERLESS"`. No customer-managed network configuration is attached.
2. **Unity Catalog metastore** -- Creates a metastore when `metastore_id` is empty or uses the specified existing metastore, then assigns it to the workspace.
3. **Unity Catalog IAM role and S3 bucket** _(optional, when `new_catalog = true`)_ -- Creates a dedicated self-assuming IAM role and private S3 bucket for catalog storage.
4. **Storage credential and external location** _(optional, when `new_catalog = true`)_ -- Creates a Unity Catalog storage credential backed by the IAM role and an external location for the S3 bucket.
5. **User-defined catalog** _(optional, when `new_catalog = true`)_ -- Creates a catalog whose managed storage uses the external location.

Unlike `aws-byovpc-uc`, this example does not create a VPC, subnets, NAT gateways, VPC endpoints, security groups, a workspace root-storage bucket, cross-account workspace credentials, or a classic cluster.

### Variables

Copy `terraform.tfvars.example` to `terraform.tfvars` in the `tf/` directory and set your values. Do not commit `terraform.tfvars`. For other file names, use `-var-file`.

| Variable | Description |
|----------|-------------|
| `databricks_account_id` | **(Required)** ID of the Databricks account. |
| `aws_account_id` | **(Required)** 12-digit AWS account ID where Unity Catalog resources are created. |
| `region` | **(Required)** AWS region for the workspace and metastore. Must be a [Databricks-supported region](https://docs.databricks.com/en/resources/supported-regions.html). |
| `prefix` | **(Optional)** Prefix for Databricks resource names and the workspace name. Default: `databricks-workspace`. |
| `resource_prefix` | **(Optional)** Prefix for AWS resource names. Lowercase letters, numbers, hyphens, and dots only, max 40 characters. Default: `databricks-workspace`. |
| `tags` | **(Optional)** Additional tags to apply to AWS resources. Default: `{}`. |
| `metastore_id` | **(Optional)** Existing Unity Catalog metastore ID. Leave empty to create a new metastore. Default: `""`. |
| `metastore_name` | **(Required when creating a metastore)** Name for the new metastore. Default: `""`. |
| `new_catalog` | **(Optional)** Create an S3 bucket, IAM role, storage credential, external location, and catalog. Default: `true`. |
| `catalog_name` | **(Optional)** Catalog name. Default `""` uses `{prefix}-catalog`. |
| `external_location_name` | **(Optional)** External location name. Default `""` uses `{resource_prefix}-external-location`. |
| `storage_credential_name` | **(Optional)** Storage credential name. Default `""` uses `{resource_prefix}-storage-credential`. |

## Deploy

```bash
cd tf/

# Copy and edit the configuration
cp terraform.tfvars.example terraform.tfvars

# Initialize Terraform
terraform init

# Review the execution plan
terraform plan

# Apply the configuration
terraform apply
```

Type `yes` when prompted. The workspace and Unity Catalog resources can take several minutes to become available.

## Access Your Workspace

After a successful deployment:

```bash
# Get the workspace URL
terraform output -raw workspace_url

# Get the workspace ID
terraform output -raw workspace_id
```

Navigate to the workspace URL and log in with your Databricks credentials.

## Validation

To verify the deployment succeeded:

1. **Terraform outputs** -- Run `terraform output` and confirm `workspace_url`, `workspace_id`, and `metastore_id` are present and non-empty.
2. **Workspace access** -- Open `terraform output -raw workspace_url` and sign in.
3. **Unity Catalog** -- When `new_catalog = true`, confirm that `catalog_name` exists in Catalog Explorer.
4. **Serverless access** -- Start a serverless notebook or SQL warehouse and read or write data in the created catalog.

## Clean-up

To destroy all resources created by this scenario:

```bash
cd tf
terraform destroy
```

Type `yes` when prompted. The generated catalog and S3 bucket use `force_destroy = true`; review the destroy plan before removing resources containing data.

## Troubleshooting

| Issue | Possible cause | Solution |
|-------|----------------|----------|
| AWS provider authentication fails | AWS CLI is not configured or credentials expired | Run `aws configure`, refresh AWS SSO, or set the standard AWS credential environment variables. |
| Databricks provider authentication fails | Missing or invalid service principal credentials | Set `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` for an account-admin service principal. |
| Existing metastore assignment fails | The metastore is in another region | Use a metastore in the same region as the workspace. |
| Storage credential or external location creation fails | The service principal lacks metastore privileges or IAM changes have not propagated | Grant the required metastore privileges and retry `terraform apply`. The configuration already waits 60 seconds for IAM propagation. |
| S3 or IAM creation fails | Insufficient AWS permissions or a conflicting resource name | Grant the required permissions or choose a unique `resource_prefix`. |
| Cannot delete the catalog on destroy | The catalog contains objects protected outside this configuration | Remove the protected objects, then run `terraform destroy` again. |

## File Structure

This project uses the same flat, purpose-specific structure as `aws-byovpc-uc`:

```text
tf/
├── versions.tf                 # Terraform and provider version constraints
├── providers.tf                # AWS and Databricks providers
├── variables.tf                # Input variable definitions
├── outputs.tf                  # Output values
├── terraform.tfvars.example    # Configuration template
├── workspace.tf                # Serverless workspace
├── metastore.tf                # Unity Catalog metastore and assignment
└── unity_catalog.tf            # Optional S3-backed catalog resources
```

| File | Purpose |
|------|---------|
| **versions.tf** | Terraform and provider version constraints for AWS, Databricks, Random, and Time. |
| **providers.tf** | AWS provider plus account-level and workspace-level Databricks providers. |
| **variables.tf** | Databricks, AWS, metastore, and optional catalog inputs. |
| **terraform.tfvars.example** | Example values to copy to `terraform.tfvars`. |
| **workspace.tf** | Serverless workspace creation and readiness wait. |
| **metastore.tf** | New or existing metastore resolution, region validation, and workspace assignment. |
| **unity_catalog.tf** | Optional S3 bucket, IAM role, storage credential, external location, and catalog. |
| **outputs.tf** | Workspace, metastore, catalog, external location, and storage credential outputs. |

There is no `main.tf`. Terraform automatically loads every `.tf` file in the directory.

## Terraform template examples and more documentation

The templates are provided for exploration and are not formally supported by Databricks with Service Level Agreements (SLAs). They are provided AS-IS without guarantees.

- [Databricks Terraform provider documentation](https://registry.terraform.io/providers/databricks/databricks/latest/docs)
- [Create a serverless workspace using the account API](https://docs.databricks.com/aws/en/admin/workspace/serverless-workspaces)
- [Unity Catalog external locations](https://docs.databricks.com/aws/en/connect/unity-catalog/cloud-storage/s3)
