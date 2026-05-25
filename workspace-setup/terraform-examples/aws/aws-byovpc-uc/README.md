# AWS BYOVPC with User-Defined Catalog Workspace Setup Guide

This Terraform example deploys a Databricks workspace on AWS using the "Bring Your Own VPC" (BYOVPC) pattern with Unity Catalog and a user-defined catalog backed by an external location. It provisions the full networking stack (VPC, subnets, NAT Gateway, VPC endpoints, security groups), a cross-account IAM role, an S3 root storage bucket, a Databricks workspace, and configures Unity Catalog with a storage credential, external location, and user-defined catalog backed by a dedicated S3 bucket.

It is important to note that this deployment creates a new VPC from scratch and currently does not support using an existing VPC.

### Important
The difference between this deployment option and the standard option for aws-byovpc is the inclusion of a user-defined catalog and external location. The requirements and authentication procedures remain the same.

## Requirements

- Terraform is installed on your local machine (version ~> 1.3): [link](https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli#install-terraform)
- AWS CLI is installed on your local machine: [Mac](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) or [Windows](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
- AWS CLI configured with appropriate credentials
- Databricks account created (E2 account)
- Databricks account admin access
- AWS permissions to create VPC, IAM, S3, and Security Group resources
- When using an existing metastore (i.e. `metastore_id` is set), the identity used by Terraform (typically the Databricks **service principal** configured via `DATABRICKS_CLIENT_ID` / `DATABRICKS_CLIENT_SECRET`) must be able to create external locations on that metastore (for example `CREATE EXTERNAL LOCATION` on the metastore, or equivalent metastore-level permissions your organization grants). Metastores created by this template configure admin principals as part of this flow; attaching to an existing metastore often requires an account admin to grant this explicitly.

## Before you begin

Configuration values (Databricks account ID, AWS region, VPC and subnet CIDRs, availability zones, metastore options) are defined as variables. Copy `tf/terraform.tfvars.example` to `tf/terraform.tfvars` and set your values there. Terraform loads `terraform.tfvars` automatically. You can also use a file ending in `.auto.tfvars` or pass variables via the command line.

## Authenticate

### AWS Authentication

#### Option 1: Environment variables (for users)

```sh
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_SESSION_TOKEN="your-session-token"  # If using temporary credentials
```

#### Option 2: AWS CLI profile

```sh
export AWS_PROFILE="your-profile"
```

#### Option 3: AWS SSO login (for users)

```sh
aws sso login --profile your-profile
```

### Databricks Authentication

Use a service principal for account-level operations:

```sh
export DATABRICKS_CLIENT_ID="your-client-id"
export DATABRICKS_CLIENT_SECRET="your-client-secret"
```

For more information on creating a Databricks service principal, visit the [Databricks documentation](https://docs.databricks.com/en/dev-tools/service-principals.html).

## What this Terraform code does

### Overview

The code provisions:

1. **VPC** -- A VPC with address space from `vpc_cidr_range`, containing three subnet types:
   - **Private subnets** -- CIDRs from `private_subnets_cidr`. Used by Databricks for cluster nodes.
   - **Public subnets** -- CIDRs from `public_subnets_cidr`. Used for the NAT Gateway and internet gateway.
   - **Intra subnets** -- CIDRs from `intra_subnet_cidr`. Used for VPC endpoints (STS, Kinesis).
2. **NAT Gateway** -- A single NAT Gateway for outbound internet connectivity from private subnets.
3. **VPC Endpoints** -- Gateway endpoint for S3 and interface endpoints for STS and Kinesis Streams.
4. **Security group** -- Default VPC security group configured with Databricks-required egress rules (ports 443, 3306, 2443, 8443-8451), internal TCP/UDP egress, and self-ingress. Optionally, you can provide existing security group IDs via `security_group_ids`.
5. **Cross-account IAM role** -- An IAM role that grants Databricks access to your AWS account for workspace provisioning.
6. **Root S3 bucket** -- An S3 bucket for workspace root storage (DBFS), with a Databricks-specific bucket policy.
7. **Databricks workspace** -- An E2 workspace using the provisioned network, credentials, and storage configuration.
8. **Unity Catalog metastore** -- Either creates a new metastore (when `metastore_id` is empty) or uses an existing one. The metastore is assigned to the workspace.
9. **Unity Catalog IAM role and S3 bucket** -- A dedicated IAM role and S3 bucket for the Unity Catalog external location, with appropriate trust and access policies.
10. **Storage credential and external location** -- A Unity Catalog storage credential backed by the IAM role, and an external location pointing to the catalog S3 bucket.
11. **User-defined catalog** -- A Unity Catalog catalog backed by the external location's storage.

### Variables

Copy `terraform.tfvars.example` to `terraform.tfvars` in the `tf/` directory and set your values. Do not commit `terraform.tfvars` (it may contain sensitive data). Terraform automatically loads `terraform.tfvars`; for other file names use `-var-file`.

#### List of variables

| Variable | Description |
|----------|-------------|
| `databricks_account_id` | **(Required)** ID of the Databricks account. |
| `prefix` | **(Optional)** Prefix for Databricks resource names (workspace name, storage config, etc.). Default: `databricks-workspace`. |
| `resource_prefix` | **(Optional)** Prefix for naming AWS resources (VPC, S3, IAM, etc.). Lowercase letters, numbers, hyphens, and dots only, max 40 characters. Default: `databricks-workspace`. |
| `pricing_tier` | **(Optional)** Pricing tier for the workspace. `ENTERPRISE` or `PREMIUM`. Default: `PREMIUM`. |
| `region` | **(Required)** AWS region code where resources will be deployed. Must be a [Databricks-supported region](https://docs.databricks.com/en/resources/supported-regions.html). |
| `tags` | **(Optional)** Additional tags to apply to all AWS resources. Default: `{}`. |
| `vpc_cidr_range` | **(Optional)** CIDR range for the VPC. Default: `10.0.0.0/16`. |
| `availability_zones` | **(Required)** List of AWS availability zones for subnet distribution (e.g. `["us-west-2a", "us-west-2b"]`). |
| `private_subnets_cidr` | **(Required)** List of private subnet CIDR blocks (one per AZ). |
| `public_subnets_cidr` | **(Required)** List of public subnet CIDR blocks (one per AZ). |
| `intra_subnet_cidr` | **(Required)** List of intra subnet CIDR blocks for VPC endpoints. |
| `security_group_ids` | **(Optional)** Existing security group IDs to use. If empty, the VPC default security group is used. Default: `[]`. |
| `sg_egress_ports` | **(Optional)** List of egress ports to allow in security group rules. Default: `[443, 3306, 2443, 8443, 8444, 8445, 8446, 8447, 8448, 8449, 8450, 8451]`. |
| `aws_account_id` | **(Required)** AWS account ID where resources are deployed (used to construct IAM role ARNs for Unity Catalog). |
| `metastore_id` | **(Optional)** Existing Unity Catalog metastore ID. Leave empty to create a new one. Default: `""`. |
| `metastore_name` | **(Optional)** Name for the Unity Catalog metastore. Required when `metastore_id` is empty. Default: `""`. |
| `catalog_name` | **(Optional)** Unity Catalog catalog name. Default `""` uses `prefix`. |
| `external_location_name` | **(Optional)** Unity Catalog external location name. Default `""` uses `{resource_prefix}-external-location`. |
| `storage_credential_name` | **(Optional)** Unity Catalog storage credential name. Default `""` uses `{resource_prefix}-storage-credential`. |

**Note:** Those three variables default to `""` in `variables.tf`. They cannot default to `prefix` or `resource_prefix` there because Terraform does not allow a variable `default` to reference another variable; fallbacks are applied in `locals` in `unity_catalog.tf`.

## Deploy

```bash
cd tf/

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

## Validation

To verify the deployment succeeded:

1. **Terraform outputs** -- From the `tf/` directory, run `terraform output` and confirm `workspace_url`, `workspace_id`, `vpc_id`, and `metastore_id` are present and non-empty.
2. **AWS console** -- In your account, check that the VPC, subnets, NAT Gateway, S3 buckets, and IAM roles exist and are in a healthy state.
3. **Workspace access** -- Open `terraform output -raw workspace_url` in a browser and sign in.
4. **Classic cluster** -- Create and start a **classic cluster** (Compute > Create cluster; use the default cluster type). Once the cluster is in "Running" state, the setup is proven.

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
| AWS provider auth fails | AWS CLI not configured or credentials expired | Run `aws configure` or set `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` environment variables. |
| Databricks provider auth fails | Missing or invalid service principal credentials | Set `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` environment variables. |
| `terraform plan` fails on permissions | Insufficient AWS IAM permissions | Ensure the identity has permissions to create VPC, IAM, S3, and Security Group resources. |
| Subnet CIDR errors | CIDRs overlap or don't fit in VPC range | Ensure `private_subnets_cidr`, `public_subnets_cidr`, and `intra_subnet_cidr` are non-overlapping and within `vpc_cidr_range`. |
| NAT Gateway or outbound connectivity issues | Cluster nodes cannot reach the control plane | Verify the NAT Gateway exists and has a public IP. Check that security group rules allow outbound traffic on required ports. |
| Cannot delete catalog on destroy | Catalog still has schemas, tables, or volumes | This template already sets `force_destroy = true` on `databricks_catalog.uc_quickstart` and `databricks_external_location`, so a normal `terraform destroy` should remove them. If destroy fails, empty or drop objects in that catalog in the workspace, then run `terraform destroy` again. 

## File Structure

This project uses a flat, organized structure with purpose-specific files instead of a monolithic `main.tf`:

```
tf/
├── versions.tf                 # Terraform and provider version constraints
├── providers.tf                # Provider configurations (AWS, Databricks)
├── variables.tf                # All input variable definitions
├── outputs.tf                  # All output values
├── terraform.tfvars.example    # Configuration template
├── workspace.tf                # Databricks workspace and MWS resources
├── network.tf                  # VPC, subnets, and VPC endpoints
├── security_group.tf           # Security group rules
├── credential.tf               # IAM cross-account role and policies
├── root_s3_bucket.tf           # S3 bucket for workspace root storage
├── metastore.tf                # Unity Catalog metastore
├── unity_catalog.tf            # Storage credential, external location, and user-defined catalog
```

| File | Purpose |
|------|---------|
| **versions.tf** | Terraform and provider version constraints (aws, databricks, random, time, null). |
| **providers.tf** | AWS provider (region-based) and Databricks providers (account-level via MWS endpoint, workspace-level via workspace URL). Auth via environment variables. |
| **variables.tf** | Input variables (Databricks config, AWS config, network CIDRs, security group options, metastore options) with validation. |
| **terraform.tfvars.example** | Example variable values; copy to `terraform.tfvars` and set your account ID, region, CIDRs, etc. |
| **workspace.tf** | Databricks MWS resources: storage configuration, credentials, network configuration, and workspace. |
| **network.tf** | VPC module (address space, public/private/intra subnets, NAT Gateway, IGW) and VPC endpoints (S3 gateway, STS and Kinesis interface endpoints). |
| **security_group.tf** | Default security group egress rules for Databricks-required ports, internal TCP/UDP egress, and self-ingress. |
| **credential.tf** | Cross-account IAM role and policy for Databricks workspace provisioning. |
| **root_s3_bucket.tf** | S3 bucket for workspace root storage (DBFS) with Databricks bucket policy. |
| **metastore.tf** | Unity Catalog metastore (create new or use existing), region check for existing metastores, and workspace assignment. |
| **unity_catalog.tf** | Unity Catalog IAM role, S3 bucket, storage credential, external location, and user-defined catalog. |
| **outputs.tf** | Workspace URL/ID; VPC ID; subnet IDs; NAT gateway IDs; security group ID; S3 bucket names; metastore ID; Unity Catalog catalog, external location, and storage credential names; credentials and network config IDs. |

**Note:** There is no `main.tf` file in this project. Instead, resources are organized into descriptive, purpose-specific files.

Terraform will automatically load all `.tf` files in the directory, so the absence of `main.tf` doesn't affect functionality.


## Terraform template examples and more documentation:

Keep in mind that the git code is not always up to date. You should use these templates as an example and not directly copy and paste. Please note that the code in the template projects is provided for your exploration only and is not formally supported by Databricks with Service Level Agreements (SLAs). They are provided AS-IS, and we do not make any guarantees of any kind.

- [Databricks on AWS Configuration](https://github.com/databricks/terraform-databricks-examples/tree/main/examples/aws-databricks-flat)
- [Security Reference Architecture Template](https://github.com/databricks/terraform-databricks-sra/tree/main/aws)
    - This is a template that adheres to the best security practices we recommend.
- [Terraform Databricks provider documentation](https://registry.terraform.io/providers/databricks/databricks/latest/docs)
- [Databricks on AWS networking](https://docs.databricks.com/en/security/network/classic/customer-managed-vpc.html)
