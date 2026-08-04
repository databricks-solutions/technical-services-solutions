# Databricks Workspace on AWS with **Back-end PrivateLink** + **CMK** (Terraform)

This template provisions:
- AWS VPC (2 subnets across AZs), security groups, route tables **OR use existing VPC/subnets**
- VPC **Interface Endpoints** for Databricks **Workspace (REST APIs)** and **Secure Cluster Connectivity (SCC) relay)** — back‑end PrivateLink
- Optional VPC endpoints for S3 (Gateway), STS and Kinesis (Interface)
- AWS KMS Customer Managed Key (CMK) **OR use existing CMK**
- S3 root bucket for workspace storage
- Cross‑account IAM role for Databricks to access your AWS account
- Databricks **VPC endpoint registrations**, **Network configuration**, **Private Access Settings (PAS)**, **Customer‑managed key (CMK)**, and the **Workspace**

> **Notes**
> - Back‑end PrivateLink requires a **customer‑managed VPC** & **Secure Cluster Connectivity** (SCC). See Databricks docs.
> - You must supply your region's **VPC endpoint service names** for the Databricks **workspace** and **SCC relay** (var.pl_service_names). See the table in Databricks docs.
> - CMK requires Enterprise tier and KMS key policy updates; the Databricks AWS account id is `414351767826` (commercial).

## 🆕 Flexible Infrastructure Options

This template now supports **two deployment modes**:

### Option 1: Create New Resources (Default)
Terraform will create new VPC, subnets, security groups, VPC endpoints, and CMK.

### Option 2: Use Existing Resources
Bring your own VPC, subnets, and/or CMK. Terraform will only create the necessary VPC endpoints and Databricks configurations.

## Deployment Options

This template can be deployed in two ways:

1. **Local Deployment**: Run Terraform from your local machine (see Quick Start below)
2. **GitHub Actions (CI/CD)**: Automated deployment via GitHub Actions - see [GITHUB_ACTIONS.md](GITHUB_ACTIONS.md) for complete setup guide

> 💡 **GitHub Actions Support**: The IAM role self-assuming configuration works seamlessly in GitHub Actions because runners come with AWS CLI pre-installed and properly configured. See the [GitHub Actions guide](GITHUB_ACTIONS.md) for details.

## Quick Start

### Using NEW Resources (Default)

1. Install Terraform >= 1.5 and configure AWS credentials (e.g., `AWS_PROFILE`, `AWS_REGION`).

2. Configure Databricks authentication using Service Principal:
   ```bash
   export DATABRICKS_CLIENT_ID="<your_service_principal_client_id>"
   export DATABRICKS_CLIENT_SECRET="<your_service_principal_secret>"
   ```

3. Copy the example configuration:
   ```bash
   cp terraform.tfvars.example-new-resources terraform.tfvars
   ```

4. Edit `terraform.tfvars` and update:
   - `project` - Your project name
   - `region` - AWS region
   - `vpc_cidr` and `private_subnet_cidrs` - Network configuration
   - `databricks_account_id` - Your Databricks account ID
   - `databricks_client_id` and `databricks_client_secret` - Service principal credentials
   - `databricks_crossaccount_role_external_id` - From Databricks console
   - `pl_service_names` - PrivateLink service names for your region
   - `root_bucket_name` - S3 bucket name for workspace storage

5. Initialize & apply:
   ```bash
   terraform init
   terraform plan
   terraform apply
   ```

### Using EXISTING Resources

1. Follow steps 1-2 from above.

2. Copy the existing resources example:
   ```bash
   cp terraform.tfvars.example-existing-resources terraform.tfvars
   ```

3. Edit `terraform.tfvars` and configure:
   - Set `create_new_vpc = false`
   - Set `create_new_cmk = false`
   - Provide `existing_vpc_id` - Your VPC ID
   - Provide `existing_subnet_ids` - List of subnet IDs (at least 2, in different AZs)
   - Provide `existing_cmk_arn` - ARN of your KMS key
   - Optionally provide `existing_security_group_id` (if not provided, one will be created)
   - Update other Databricks configuration values

4. Initialize & apply:
   ```bash
   terraform init
   terraform plan
   terraform apply
   ```

### Important Notes for Existing Resources

**VPC Requirements:**
- DNS support and DNS hostnames must be enabled
- Subnets must be in different Availability Zones
- Subnets should have appropriate route tables configured

**CMK Requirements:**
- CMK must have a key policy that allows:
  - Your AWS account root to manage the key
  - Databricks control plane (414351767826) to use the key
  - Your cross-account IAM role to create grants
- See `modules/aws-cmk/main.tf` for the required policy structure
- The CMK must be in the same region as your workspace

**What Will Be Created (even with existing resources):**
- VPC endpoints for Databricks workspace and SCC (required for PrivateLink)
- Security groups for VPC endpoints
- Databricks workspace and related configurations

After workspace creation reaches **RUNNING**, wait ~20 minutes before starting clusters (per Databricks guidance).

## Unity Catalog

Unity Catalog is automatically configured with:
- ✅ Metastore with S3 storage
- ✅ IAM role
- ✅ Storage credential
- ⚠️ External location (requires manual step)

### External Locations (Optional)

External locations require the Unity Catalog IAM role to have self-assuming capability. Due to AWS limitations (circular dependency), this must be done manually after the initial deployment:

1. After `terraform apply` completes, go to AWS IAM Console
2. Find the Unity Catalog role (name in outputs: `unity_catalog_role_name`)
3. Edit the "Trust relationships"
4. Add this statement to the trust policy:
```json
{
  "Effect": "Allow",
  "Principal": {
    "AWS": "<unity_catalog_role_arn>"
  },
  "Action": "sts:AssumeRole",
  "Condition": {
    "StringEquals": {
      "sts:ExternalId": "<your_databricks_account_id>"
    }
  }
}
```
5. Uncomment the `databricks_external_location` resource in `main.tf`
6. Run `terraform apply` again

The role ARN is available in the Terraform outputs.

## Clean up
```bash
terraform destroy
```

## References
- Back‑end PrivateLink steps & ports. Databricks docs.
- Private Access Settings (PAS), VPC endpoint registrations & network config. Databricks docs.
- CMK configuration & KMS policy. Databricks docs.
