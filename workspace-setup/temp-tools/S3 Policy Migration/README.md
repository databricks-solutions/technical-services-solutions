# S3 Policy Migration (Terraform)

This is a small Terraform “tool” that:

- Discovers **Databricks external locations** in a workspace
- Derives the backing **S3 bucket ARNs**
- Reads the current **S3 bucket policy** for each bucket
- Filters for the “network guardrail” deny statement (the `IPDeny`-style statement)
- Updates that statement to include the required org-path guardrail:
  - Adds `Condition["ForAnyValue:StringNotLikeIfExists"]["aws:VpceOrgPaths"]`
  - Removes the invalid `aws:VpceOrgPaths` key if it was previously placed under `StringNotEqualsIfExists`

> Important: this tool **updates bucket policies**. Always run `terraform plan` and review the diff before applying.

## Prereqs

- Terraform installed
- AWS credentials available to Terraform (via env vars, AWS profile, etc.) with permissions to:
  - `s3:GetBucketPolicy`
  - `s3:PutBucketPolicy`
- Databricks service principal credentials with access to:
  - List external locations in the metasotre attahced to the workspace
  - Read external location definitions

## Configure

Edit `terraform.tfvars` and set:

- `databricks_account_id`
- `client_id`
- `client_secret`
- `workspace_host`
- `aws_region`

Optional:

- `bucket_arns_override` (map) — use this if discovery returns nothing (e.g., permissions). Example:

```hcl
bucket_arns_override = {
  main = "arn:aws:s3:::my-bucket"
}
```

## Run

```bash
terraform init
terraform plan
terraform apply
```

## Outputs

- `external_location_bucket_arns`: discovered buckets (from workspace external locations)
- `storage_bucket_policies`: the current policies (as read)
- `storage_bucket_policies_filtered`: the filtered subset used to identify guardrail statements / changes

## Debug mode

By default, debug output is disabled.

Enable it with:

```hcl
debug = true
```

When enabled, the root output `debug` includes:

- External location names + URLs
- Derived bucket ARNs (including nulls for non-S3 locations)
- Workspace metastore info
- Bucket ARN inputs / resolved bucket-name map

## Safety notes

- This tool manages bucket policies via `aws_s3_bucket_policy`. Deleting resources/state incorrectly can remove bucket policies. Use with care.
- Prefer running:
  - `terraform plan` first
  - then `terraform apply` only after reviewing the policy diff


