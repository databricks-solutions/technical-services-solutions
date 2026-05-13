# Databricks Serverless Workspace with NCC and S3 External Location

This Terraform configuration deploys a Databricks serverless workspace on AWS with private connectivity to an S3 bucket via Network Connectivity Configuration (NCC), plus a Unity Catalog external location backed by that bucket.

## Architecture Overview

This configuration creates:
- **Databricks Workspace**: Serverless compute mode workspace
- **NCC**: Network Connectivity Configuration to route serverless egress traffic privately
- **S3 Private Endpoint Rule**: Provisions an AWS VPC endpoint that the workspace uses to reach the bucket
- **S3 Bucket Policy**: Adds an `aws:SourceVpce` allow statement so only the Databricks-owned VPC endpoint can reach the bucket
- **Unity Catalog Metastore**: Creates new (or attaches to existing), assigns it to the workspace, grants the workspace admin admin-level privileges on it
- **IAM Cross-Account Role + Policy**: Standard Databricks UC trust policy and permissions, used by the storage credential
- **Unity Catalog Storage Credential**: Wraps the IAM role
- **Unity Catalog External Location**: Exposes the bucket via the storage credential
- **Workspace Admin Assignment**: Assigns the specified user as workspace admin

## Prerequisites

1. **Terraform**: Version 1.4 or higher (uses `terraform_data`)
2. **AWS Account**: With permissions to create IAM roles/policies and put bucket policies on the target bucket
3. **Databricks Account**: E2 account with account admin OAuth M2M service principal
4. **AWS CLI**: Configured with valid credentials
5. **`curl` and `jq`**: Required for the Databricks API call that enables the NCC private endpoint rule (both standard on macOS / most Linux)
6. **S3 bucket**: Must already exist in the same region as the workspace — the script does not create it

## Required Permissions

### AWS Permissions
- `iam:CreateRole`, `iam:CreatePolicy`, `iam:AttachRolePolicy`, `iam:Tag*`
- `s3:PutBucketPolicy`, `s3:GetBucketPolicy` on the target bucket

### Databricks Permissions
- Account admin (creates workspace, NCC, metastore, assigns workspace admin)
- The SP retains metastore ownership during deploy so it can create the storage credential and external location; the user gets equivalent admin-level access via grants

## Quick Start

### 1. Configure Authentication

#### AWS Authentication

```bash
# Option 1: Environment variables
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_SESSION_TOKEN="your-session-token"  # if using temporary credentials

# Option 2: AWS CLI profile
export AWS_PROFILE="your-profile"

# Verify
aws sts get-caller-identity
```

#### Databricks Authentication

```bash
# OAuth M2M for the account-level service principal
export DATABRICKS_CLIENT_ID="your-client-id"
export DATABRICKS_CLIENT_SECRET="your-client-secret"
```

### 2. Configure Variables

```bash
cd tf/
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` with your values:

```hcl
databricks_account_id = "your-account-id"

region = "ap-south-1"
prefix = "demo"

create_new_workspace = true
workspace_name       = "my-workspace"
ncc_name             = "ncc-my-workspace"

workspace_admin_email = "you@databricks.com"

use_existing_metastore = false
metastore_name         = "my-metastore"

external_location_bucket_name     = "my-existing-bucket"
storage_credential_name           = "my-bucket-cred"
external_location_name            = "my-bucket-ext-loc"
uc_iam_role_name                  = "my-bucket-uc-role"
external_location_grant_principal = "account users"
merge_existing_bucket_policy      = false
create_private_endpoint_rule      = false
```

### 3. Deploy

From inside `tf/`:

```bash
terraform init
terraform plan
terraform apply
```

Typical end-to-end time: 5–10 minutes. Slowest steps:
- Workspace creation: ~30s
- 90s wait for AWS to provision the VPC endpoint
- 60s wait for IAM propagation before creating the external location
- 1–5 min waiting for the NCC connection to transition `PENDING → ESTABLISHED`

### 4. Access Your Workspace

```bash
terraform output created_workspace_url
```

Log in with `workspace_admin_email`.

## Configuration Options

### Use an existing workspace

```hcl
create_new_workspace    = false
existing_workspace_id   = "1234567890123456"        # OR existing_workspace_name = "..."
existing_workspace_host = "https://dbc-xxxxx.cloud.databricks.com"
```

### Use an existing metastore

```hcl
use_existing_metastore  = true
existing_metastore_id   = "00000000-0000-0000-0000-000000000000"  # OR existing_metastore_name = "primary"
```

### Merge with existing bucket policy

If your S3 bucket already has a policy you need to preserve, set:

```hcl
merge_existing_bucket_policy = true
```

The Terraform run will read the existing policy and append the VPCE-allow statement instead of replacing.

### Optional non-S3 NCC private endpoint rule

For RDS, Kinesis, or custom VPC endpoint services:

```hcl
create_private_endpoint_rule = true
endpoint_service             = "com.amazonaws.vpce.us-east-1.vpce-svc-xxxxxxxxx"
domain_names                 = ["mydb.example.com"]
```

## Multiple Deployments

To deploy multiple workspaces from the same config without affecting each other, use Terraform workspaces (each gets its own state file):

```bash
terraform workspace new prod-1
# edit terraform.tfvars with new names
terraform apply

terraform workspace new prod-2
terraform apply
```

Switch between them with `terraform workspace select <name>`.

## File Structure

```
aws-serverless-ncc/
├── README.md                    # This file
├── .gitignore                   # Ignores state, .terraform/, tfvars
└── tf/
    ├── versions.tf              # Terraform and provider version constraints
    ├── variables.tf             # All input variable definitions
    ├── outputs.tf               # All output values
    ├── terraform.tfvars.example # Configuration template
    ├── providers.tf             # 1. databricks.account, databricks.workspace, aws provider blocks
    ├── workspace.tf             # 2. Workspace lookup/create + admin assignment
    ├── network.tf               # 3. NCC + binding + optional generic non-S3 endpoint rule
    ├── metastore.tf             # 4. Metastore lookup/create + assignment + admin grants
    ├── s3_endpoint.tf           # 5. S3 NCC private endpoint rule + bucket policy + enable PATCH
    ├── credential.tf            # 6a. UC IAM role + storage credential + grants
    └── external_location.tf    # 6b. UC external location + grants
```

## How the NCC + bucket policy + enable flow works

The trickiest part of this config is getting an enabled, ESTABLISHED NCC private endpoint to S3 in a single `terraform apply`. The Databricks API has these constraints:

1. The rule's `vpc_endpoint_id` is null in the create response — only populated after AWS finishes provisioning the underlying VPC endpoint
2. `enabled = true` is silently ignored at create time; it can only be set via PATCH after the rule's `connection_state = ESTABLISHED`
3. The connection transitions `CREATING → PENDING → ESTABLISHED` only after the bucket policy with the matching `aws:SourceVpce` is in place

This is handled with:

- A `time_sleep` after rule creation, then a `data "databricks_mws_network_connectivity_config"` re-read to fetch the populated `vpc_endpoint_id`
- A `coalesce(rule.vpc_endpoint_id, lookup_from_data_source)` trick that propagates "(known after apply)" through plan time, so the bucket policy commits with the real `vpce-xxx` in a single apply (no two-apply convergence)
- A `null_resource` with `local-exec` that calls the Databricks REST API directly: polls the rule until `connection_state = ESTABLISHED` (up to 10 minutes), then PATCHes `enabled = true` with `update_mask=enabled`

The provider's own `enabled = true` argument is set to `false` with `lifecycle.ignore_changes = [enabled]` — Terraform stays out of the rule's enable management; the null_resource owns it.

## Outputs

| Output | Description |
|---|---|
| `created_workspace_url` | Workspace URL when a new workspace is created |
| `workspace_id` | Resolved workspace ID |
| `ncc_id`, `ncc_name` | NCC identifier and name |
| `metastore_id` | Resolved metastore ID |
| `s3_private_endpoint_rule_id` | NCC rule ID |
| `s3_vpc_endpoint_id` | AWS VPC endpoint ID created by the rule |
| `s3_private_endpoint_connection_state` | Connection state (should be `ESTABLISHED` after deploy) |
| `s3_private_endpoint_enabled` | Whether the rule is active |
| `storage_credential_name` | UC storage credential name |
| `external_location_name`, `external_location_url` | UC external location identifiers |
| `uc_iam_role_arn` | ARN of the IAM role used by the storage credential |

## Cleanup

```bash
terraform destroy
```

Notes:
- `force_destroy = true` is set on the metastore so it can be deleted even if it has catalogs/workspaces attached.
- `aws_s3_bucket_policy` will leave the bucket policy in whatever state Terraform last applied. If `merge_existing_bucket_policy = false`, this means destroy effectively *deletes* the bucket policy. If you want to preserve other statements, use `merge_existing_bucket_policy = true`.
- The IAM role / IAM policy / storage credential / external location are destroyed in the right order automatically.
- The S3 bucket itself is *not* managed by Terraform here, so it's left alone.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `cannot create external location: User does not have CREATE EXTERNAL LOCATION` | The deployment SP lost ownership of the metastore or storage credential. This config keeps the SP as owner — if you've manually transferred ownership, grant the SP `CREATE_EXTERNAL_LOCATION` and `CREATE_STORAGE_CREDENTIAL` on the metastore via the UI |
| `Field enabled can only be updated when connection_state is ESTABLISHED` | AWS hasn't auto-approved the VPC endpoint yet. The script polls up to 10 minutes — if it consistently fails, check the rule in the Databricks UI for an error message |
| `NoSuchBucket: The specified bucket does not exist` | The bucket named in `external_location_bucket_name` doesn't exist. Create it manually first: `aws s3 mb s3://<name> --region <region>` |
| `Provider produced inconsistent final plan` | Indicates a Terraform expression evaluating to one value at plan time and a different value at apply time. The `coalesce` trick in `s3_endpoint.tf` is designed to avoid this for `vpc_endpoint_id`; if you see it elsewhere, paste the error |
| `ExpiredToken` from AWS | Your AWS session expired. Refresh creds (`aws sso login --profile X`, etc.) and re-run |
| `default auth: cannot configure default credentials` | `DATABRICKS_CLIENT_ID` / `DATABRICKS_CLIENT_SECRET` aren't exported in your shell |
