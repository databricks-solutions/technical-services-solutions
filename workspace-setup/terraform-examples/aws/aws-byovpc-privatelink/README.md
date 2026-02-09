# Databricks on AWS with Private Link (BYOVPC)

This Terraform configuration deploys a Databricks workspace on AWS using the "Bring Your Own VPC" (BYOVPC) pattern with **Private Link** for backend REST API and Secure Cluster Connectivity (SCC) relay. Traffic between your VPC and Databricks stays on the AWS network.

## Architecture Overview

This configuration creates:
- **Databricks Workspace**: Enterprise-tier workspace with Private Access Settings
- **Private Link**: VPC endpoints for Databricks REST API and SCC relay (pre-configured per region)
- **VPC Infrastructure**: Customer-managed VPC with public/private subnets (or use existing VPC)
- **Security**: IAM roles, workspace and Private Link security groups, S3 bucket policies
- **Unity Catalog**: Optional metastore creation or attachment to existing metastore
- **Additional VPC Endpoints**: STS and Kinesis (for Databricks services over Private Link)

## Prerequisites

1. **Terraform**: Version 1.3 or higher
2. **AWS Account**: With appropriate permissions to create VPC, IAM, S3, and VPC endpoint resources
3. **Databricks Account**: E2 account with account admin access
4. **AWS CLI**: Configured with valid credentials
5. **Databricks CLI**: Service principal credentials for account-level operations

## Required Permissions

### AWS Permissions
- VPC, Subnet, Internet Gateway, NAT Gateway, Route Table management
- IAM Role and Policy management
- S3 Bucket creation and policy management
- Security Group management
- VPC Endpoint (Interface) creation and management

### Databricks Permissions
- Account Admin access to create workspaces and Private Access Settings
- Ability to create credentials, storage configs, networks, and VPC endpoint configs

## Quick Start

### 1. Configure Authentication

#### AWS Authentication
```bash
# Option 1: Environment variables
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_SESSION_TOKEN="your-session-token"  # If using temporary credentials

# Option 2: AWS CLI profile
export AWS_PROFILE="your-profile"
```

#### Databricks Authentication
```bash
# Use service principal for account-level operations
export DATABRICKS_CLIENT_ID="your-client-id"
export DATABRICKS_CLIENT_SECRET="your-client-secret"
```

### 2. Configure Variables

```bash
cd tf/
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` with your specific values:
```hcl
databricks_account_id = "your-account-id"
prefix                = "my-workspace"
resource_prefix       = "my-workspace"
region                = "us-west-2"

# Network configuration (Option 1: new VPC)
vpc_id               = ""
vpc_cidr_range       = "10.0.0.0/16"
availability_zones   = ["us-west-2a", "us-west-2b"]
private_subnets_cidr = ["10.0.1.0/24", "10.0.2.0/24"]
public_subnets_cidr  = ["10.0.101.0/24", "10.0.102.0/24"]
subnet_ids           = []

# Unity Catalog
metastore_name = "my-metastore"
```

### 3. Deploy

```bash
# Initialize Terraform
terraform init

# Review the execution plan
terraform plan

# Apply the configuration
terraform apply
```

The deployment typically takes 10-15 minutes.

### 4. Access Your Workspace

After successful deployment:
```bash
# Get the workspace URL
terraform output workspace_url

# Get the workspace ID
terraform output workspace_id
```

Navigate to the workspace URL and log in with your Databricks credentials.

## Configuration Options

### Option 1: Create New VPC (Recommended for New Deployments)

```hcl
vpc_id               = ""
vpc_cidr_range       = "10.0.0.0/16"
availability_zones   = ["us-west-2a", "us-west-2b"]
private_subnets_cidr = ["10.0.1.0/24", "10.0.2.0/24"]
public_subnets_cidr  = ["10.0.101.0/24", "10.0.102.0/24"]
subnet_ids           = []
private_route_table_ids = []
```

### Option 2: Use Existing VPC

```hcl
vpc_id                 = "vpc-xxxxxxxxx"
vpc_cidr_range         = "10.0.0.0/16"
subnet_ids             = ["subnet-xxxxxxxxx", "subnet-yyyyyyyyy"]
private_route_table_ids = ["rtb-xxxxxxxxx"]
```

**Requirements for existing VPC:**
- At least 2 private subnets in different AZs
- Subnets must have outbound internet connectivity (NAT Gateway or similar) if needed for other services
- Security group egress must allow required Databricks ports; use `sg_egress_ports` and optionally `additional_egress_ips`

### Workspace Security Group Egress: Restrictive vs Permissive

- **Restrictive (default):** Egress for `sg_egress_ports` is limited to `var.vpc_cidr_range` and optionally `var.additional_egress_ips`. Use for least-privilege with Private Link.
- **Permissive:** Same ports allowed to `0.0.0.0/0`. A permissive block is commented out in `network.tf`; comment out the restrictive egress block and uncomment the one with `cidr_blocks = ["0.0.0.0/0"]` to switch.

### Unity Catalog Options

#### Create New Metastore
```hcl
metastore_id   = ""
metastore_name = "my-metastore"
```

#### Use Existing Metastore
```hcl
metastore_id   = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
metastore_name = ""  # Not required when using existing
```

## File Structure

This project uses a flat, organized structure with purpose-specific files:

```
tf/
├── versions.tf              # Terraform and provider version constraints
├── providers.tf             # Provider configurations (AWS, Databricks)
├── variables.tf             # All input variable definitions
├── outputs.tf               # All output values
├── terraform.tfvars.example # Configuration template
├── credential.tf            # IAM cross-account role and policies
├── network.tf               # VPC (optional), workspace security group
├── privatelink.tf           # Private Link security group and VPC endpoints (REST, SCC)
├── endpoints.tf             # Additional VPC endpoints (STS, Kinesis)
├── root_bucket.tf           # S3 bucket for workspace root storage
├── workspace.tf             # Databricks workspace, MWS networks, PAS, VPC endpoint configs
└── metastore.tf             # Unity Catalog metastore
```

Terraform loads all `.tf` files in the directory; the structure is organizational only.
