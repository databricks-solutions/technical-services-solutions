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
5. **`databricks` CLI (>= 0.297), `aws` CLI, `jq`**: Used by the helper scripts in `tf/scripts/` that poll for VPC endpoint readiness, enable the NCC private endpoint rule, and (in merge mode) read + restore the bucket policy. Install via `brew install databricks awscli jq` (or your distro's equivalent).
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
- Polling for AWS to provision the VPC endpoint (every 10s, typically 60–120s, up to 5 min)
- 60s wait for IAM propagation before creating the external location
- 1–5 min waiting for the NCC connection to transition `PENDING → ESTABLISHED`

### 4. Access Your Workspace

```bash
terraform output created_workspace_url
```

Log in with `workspace_admin_email`.

### 5. Next Steps — create a catalog and write a table

The terraform run leaves you with an external location but no catalog. To verify the end-to-end path (workspace → NCC → S3) works, create a catalog and write an external table backed by the bucket. From a notebook or the SQL editor in the new workspace:

```sql
-- Replace <bucket> with your external_location_bucket_name
CREATE CATALOG my_catalog;
CREATE SCHEMA my_catalog.demo;

CREATE TABLE my_catalog.demo.hello (greeting STRING, ts TIMESTAMP)
  USING DELTA
  LOCATION 's3://<bucket>/demo/hello/';

INSERT INTO my_catalog.demo.hello VALUES ('world', current_timestamp());

SELECT * FROM my_catalog.demo.hello;
```

If the `SELECT` returns a row, the private S3 path is genuinely working — data was written to the bucket via the NCC private endpoint and read back through it.

> **Why external table and not `CREATE CATALOG ... MANAGED LOCATION`?** Managed locations require `CREATE_MANAGED_STORAGE` on the external location, which this Terraform config does not grant (the workspace admin gets `MANAGE, READ_FILES, WRITE_FILES, CREATE_EXTERNAL_TABLE` — see [tf/external_location.tf](tf/external_location.tf)). If you need managed catalogs, add `CREATE_MANAGED_STORAGE` to the grant block, or run the grant manually as the external location owner.

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

> A Databricks account is limited to **one metastore per region**, so if your account already has one in this region, you must use it (set `use_existing_metastore = true`). The default is `false` (create new) because the README example walks through a first-time deploy.

**Required SP permissions on the existing metastore.** The deployment service principal must be able to create a storage credential and external location on the metastore. If the SP is already metastore admin/owner, you're done. If not, grant it explicitly before running terraform:

```sql
-- Run as the current metastore admin in the workspace's SQL editor
GRANT CREATE_STORAGE_CREDENTIAL, CREATE_EXTERNAL_LOCATION
  ON METASTORE
  TO `<service-principal-application-id>`;
```

The `create new metastore` path does this automatically — for existing metastores it's your responsibility.

### Merge with existing bucket policy

If your S3 bucket already has a policy you need to preserve, set:

```hcl
merge_existing_bucket_policy = true
```

Behavior:

- **First apply:** the pre-Terraform bucket policy is snapshotted into Terraform state (via `terraform_data.original_bucket_policy` with `ignore_changes = [input]`) and the VPCE-allow statement is appended to the merged policy pushed to S3. If the bucket had no prior policy, an empty snapshot is stored — no error.
- **Subsequent applies:** the merge sources from the snapshot in state (not a fresh read), so it's stable even if the on-bucket policy drifts.
- **Destroy:** `aws_s3_bucket_policy` owns the full policy — deleting it would leave the bucket with no policy at all, wiping any pre-existing statements. To avoid that, a `null_resource` with a `when = destroy` provisioner runs `scripts/restore-bucket-policy.sh` after the merged policy is torn down, putting the snapshotted original back. If the bucket originally had no policy, the restore is a no-op.

Constraints of this approach:

- The snapshot only captures what was on the bucket at *first apply*. If someone edits the bucket policy out-of-band later, that edit is lost on destroy.
- `restore-bucket-policy.sh` tolerates the bucket having been deleted before destroy (exits 0). All other AWS failures surface non-zero.

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
    ├── ncc.tf                   # 3. NCC + binding + optional generic non-S3 endpoint rule
    ├── metastore.tf             # 4. Metastore lookup/create + assignment + admin grants
    ├── s3_endpoint.tf           # 5. S3 NCC private endpoint rule + bucket policy + enable PATCH
    ├── credential.tf            # 6a. UC IAM role + storage credential + grants
    ├── external_location.tf     # 6b. UC external location + grants
    └── scripts/
        ├── wait-for-vpc-endpoint.sh  # polls until vpc_endpoint_id is populated
        ├── enable-s3-rule.sh         # polls for ESTABLISHED, then enables the rule
        ├── read-bucket-policy.sh     # merge mode: tolerant read of existing bucket policy
        └── restore-bucket-policy.sh  # merge mode: restore original policy on destroy
```

## How the NCC + bucket policy + enable flow works

The trickiest part of this config is getting an enabled, ESTABLISHED NCC private endpoint to S3 in a single `terraform apply`. The Databricks API has these constraints:

1. The rule's `vpc_endpoint_id` is null in the create response — only populated after AWS finishes provisioning the underlying VPC endpoint
2. `enabled = true` is silently ignored at create time; it can only be set via an update after the rule's `connection_state = ESTABLISHED`
3. The connection transitions `CREATING → PENDING → ESTABLISHED` only after the bucket policy with the matching `aws:SourceVpce` is in place
4. The Databricks Terraform provider supports the enable-update, but does NOT natively poll for `connection_state = ESTABLISHED` — so a pure-config approach would fail on first apply

This is handled with two helper scripts in [tf/scripts/](tf/scripts/) invoked by `null_resource.local-exec`:

- **[scripts/wait-for-vpc-endpoint.sh](tf/scripts/wait-for-vpc-endpoint.sh)** — polls the rule via the `databricks` CLI every 10s (up to 5 min) until `vpc_endpoint_id` is populated. Then a `data "databricks_mws_network_connectivity_config"` re-read fetches the populated value.
- A `coalesce(rule.vpc_endpoint_id, lookup_from_data_source)` trick propagates "(known after apply)" through plan time, so the bucket policy commits with the real `vpce-xxx` in a single apply (no two-apply convergence).
- **[scripts/enable-s3-rule.sh](tf/scripts/enable-s3-rule.sh)** — polls the rule via the `databricks` CLI every 10s (up to 10 min) until `connection_state = ESTABLISHED`, then sends `update-private-endpoint-rule --update-mask enabled --enabled` to flip the rule on.

The provider's own `enabled = true` argument is set to `false` with `lifecycle.ignore_changes = [enabled, account_id]` — Terraform stays out of the rule's enable management; the script owns it. `account_id` is ignored because the Databricks provider versions disagree about whether to store it, causing phantom drift on upgrade that would otherwise trigger empty PATCHes the API rejects with "Update mask must be specified".

The two scripts use the `databricks` CLI (auto-handles OAuth from `DATABRICKS_CLIENT_ID` / `DATABRICKS_CLIENT_SECRET`) instead of raw `curl` to keep the bash short and the OAuth dance out of the script.

## Outputs

| Output | Description |
|---|---|
| `created_workspace_url` | Workspace URL when a new workspace is created |
| `workspace_id` | Resolved workspace ID |
| `ncc_id`, `ncc_name` | NCC identifier and name |
| `metastore_id` | Resolved metastore ID |
| `s3_private_endpoint_rule_id` | NCC rule ID. Apply succeeds only if the rule reaches ESTABLISHED + enabled; the null_resource.enable_s3_rule provisioner fails the apply otherwise. To verify after the fact, query the rule directly (see below). |
| `storage_credential_name` | UC storage credential name |
| `external_location_name`, `external_location_url` | UC external location identifiers |
| `uc_iam_role_arn` | ARN of the IAM role used by the storage credential |

## Cleanup

```bash
terraform destroy
```

Notes:
- `force_destroy = true` is set on the metastore so it can be deleted even if it has catalogs/workspaces attached.
- **Bucket policy on destroy:**
  - `merge_existing_bucket_policy = false` (default): destroy deletes the bucket policy Terraform wrote — the bucket ends up with no policy at all. Use this only when the bucket has no other statements that need to survive.
  - `merge_existing_bucket_policy = true`: destroy restores the *snapshot* captured on first apply (see [Merge with existing bucket policy](#merge-with-existing-bucket-policy)). Statements added to the bucket out-of-band *after* first apply are not preserved.
- The IAM role / IAM policy / storage credential / external location are destroyed in the right order automatically.
- The S3 bucket itself is *not* managed by Terraform here, so it's left alone.
- A `time_sleep.delay_before_ncc_delete` (30s destroy delay) sits between the NCC and its binding so the Databricks control plane has time to propagate the unbind before the NCC delete runs — avoiding the "unable to be deleted because it is attached to one or more workspaces" error that used to require a manual destroy rerun.

## Verifying the rule state on demand

A successful apply already guarantees the rule is enabled + ESTABLISHED. If you want to double-check at any point:

```bash
RULE_ID=$(terraform output -raw s3_private_endpoint_rule_id)
NCC_ID=$(terraform output -raw ncc_id)
ACCOUNT_ID="<your-databricks-account-id>"

TOKEN=$(curl -s -X POST -u "$DATABRICKS_CLIENT_ID:$DATABRICKS_CLIENT_SECRET" \
  "https://accounts.cloud.databricks.com/oidc/accounts/$ACCOUNT_ID/v1/token" \
  -d 'grant_type=client_credentials&scope=all-apis' | jq -r '.access_token')

curl -s -H "Authorization: Bearer $TOKEN" \
  "https://accounts.cloud.databricks.com/api/2.0/accounts/$ACCOUNT_ID/network-connectivity-configs/$NCC_ID/private-endpoint-rules/$RULE_ID" \
  | jq '{enabled, connection_state, vpc_endpoint_id}'
```

Expect `{"enabled": true, "connection_state": "ESTABLISHED", "vpc_endpoint_id": "vpce-..."}`.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `cannot create external location: User does not have CREATE EXTERNAL LOCATION` | The deployment SP lost ownership of the metastore or storage credential. This config keeps the SP as owner — if you've manually transferred ownership, grant the SP `CREATE_EXTERNAL_LOCATION` and `CREATE_STORAGE_CREDENTIAL` on the metastore via the UI |
| `Field enabled can only be updated when connection_state is ESTABLISHED` | AWS hasn't auto-approved the VPC endpoint yet. The script polls up to 10 minutes — if it consistently fails, check the rule in the Databricks UI for an error message |
| `NoSuchBucket: The specified bucket does not exist` | The bucket named in `external_location_bucket_name` doesn't exist. Create it manually first: `aws s3 mb s3://<name> --region <region>` |
| `Provider produced inconsistent final plan` | Indicates a Terraform expression evaluating to one value at plan time and a different value at apply time. The `coalesce` trick in `s3_endpoint.tf` is designed to avoid this for `vpc_endpoint_id`; if you see it elsewhere, paste the error |
| `ExpiredToken` from AWS | Your AWS session expired. Refresh creds (`aws sso login --profile X`, etc.) and re-run |
| `default auth: cannot configure default credentials` | `DATABRICKS_CLIENT_ID` / `DATABRICKS_CLIENT_SECRET` aren't exported in your shell |
