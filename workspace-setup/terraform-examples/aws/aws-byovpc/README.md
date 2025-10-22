# Databricks on AWS with Customer-Managed VPC (BYOVPC)

This Terraform configuration deploys a Databricks workspace on AWS using the "Bring Your Own VPC" (BYOVPC) pattern, giving you full control over your network infrastructure.

## Architecture Overview

This configuration creates:
- **Databricks Workspace**: Enterprise-tier workspace with Unity Catalog
- **VPC Infrastructure**: Customer-managed VPC with public/private subnets (or use existing VPC)
- **Security**: IAM roles, security groups, and S3 bucket policies
- **Unity Catalog**: Optional metastore creation or attachment to existing metastore

## Prerequisites

1. **Terraform**: Version 1.3 or higher
2. **AWS Account**: With appropriate permissions to create VPC, IAM, S3 resources
3. **Databricks Account**: E2 account with account admin access
4. **AWS CLI**: Configured with valid credentials
5. **Databricks CLI**: Service principal credentials for account-level operations

## Required Permissions

### AWS Permissions
- VPC, Subnet, Internet Gateway, NAT Gateway, Route Table management
- IAM Role and Policy management
- S3 Bucket creation and policy management
- Security Group management

### Databricks Permissions
- Account Admin access to create workspaces
- Ability to create credentials, storage configs, and networks

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

# Network configuration
vpc_cidr_range       = "10.0.0.0/16"
availability_zones   = ["us-west-2a", "us-west-2b"]
private_subnets_cidr = ["10.0.1.0/24", "10.0.2.0/24"]
public_subnets_cidr  = ["10.0.101.0/24", "10.0.102.0/24"]

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
security_group_ids   = []
```

### Option 2: Use Existing VPC

```hcl
vpc_id             = "vpc-xxxxxxxxx"
subnet_ids         = ["subnet-xxxxxxxxx", "subnet-yyyyyyyyy"]
security_group_ids = ["sg-xxxxxxxxx"]
```

**Requirements for existing VPC:**
- At least 2 private subnets in different AZs
- Subnets must have outbound internet connectivity (NAT Gateway or similar)
- Security group must allow required Databricks ports

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

This project uses a flat, organized structure with purpose-specific files instead of a monolithic `main.tf`:

```
tf/
├── versions.tf           # Terraform and provider version constraints
├── providers.tf          # Provider configurations (AWS, Databricks)
├── variables.tf          # All input variable definitions
├── outputs.tf            # All output values
├── terraform.tfvars.example  # Configuration template
├── workspace.tf          # Databricks workspace and MWS resources
├── network.tf            # VPC, subnets, and networking
├── security_group.tf     # Security group rules
├── credential.tf         # IAM cross-account role and policies
├── root_s3_bucket.tf     # S3 bucket for workspace root storage
└── metastore.tf          # Unity Catalog metastore

```

**Note:** There is no `main.tf` file in this project. Instead, resources are organized into descriptive, purpose-specific files. 

Terraform will automatically load all `.tf` files in the directory, so the absence of `main.tf` doesn't affect functionality.


