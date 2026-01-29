# S3 Policy Migration (Terraform)

This is a small Terraform “tool” that:

- Discovers **Databricks external locations** in a workspace
- Derives the backing **S3 bucket ARNs**
- Outputs a guidance list of **which buckets’ policies need to be reviewed/updated**

> Important: this tool is **guidance-only** (no S3 reads/writes, no policy updates).

## Prereqs

- Terraform installed
- Databricks service principal credentials with access to:
  - List external locations in the metasotre attahced to the workspace
  - Read external location definitions

## Configure

Edit `terraform.tfvars` and set:

- `databricks_account_id`
- `client_id`
- `client_secret`
- `workspace_host`
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

- `s3_bucket_arns_requiring_policy_update`: list of bucket ARNs customers should update
- `debug_external_location_bucket_arns`: same as `external_location_bucket_arns`, but only emitted when `debug = true`

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
- Resolved `external_location_bucket_arns` (filtered to S3-backed locations)

## Safety notes

- This tool does **not** manage bucket policies.


