################################################################################
# 1. Providers
################################################################################

# Account-level Databricks provider — used to create workspace, NCC, metastore,
# permission assignments. Reads OAuth M2M credentials from
# DATABRICKS_CLIENT_ID / DATABRICKS_CLIENT_SECRET env vars.
provider "databricks" {
  alias      = "account"
  host       = "https://accounts.cloud.databricks.com"
  account_id = var.databricks_account_id
}

# Workspace-level Databricks provider — used for storage credential, external
# location, and grants. account_id is required so the SDK fetches the OAuth
# token from the accounts URL when authenticating with an account-level SP.
# Without account_id, the SDK would attempt workspace-level OAuth and fail.
provider "databricks" {
  alias = "workspace"
  host = var.create_new_workspace ? databricks_mws_workspaces.serverless_workspace[0].workspace_url : (
    var.existing_workspace_host != null ? var.existing_workspace_host : "https://accounts.cloud.databricks.com"
  )
  account_id = var.databricks_account_id
}

# AWS provider — credentials read from environment (AWS_PROFILE,
# AWS_ACCESS_KEY_ID, AWS_SESSION_TOKEN, etc.). default_tags applies the tags
# below to every AWS resource managed by this config.
provider "aws" {
  region = var.region

  default_tags {
    tags = {
      ManagedBy = "Terraform"
      Project   = var.prefix
    }
  }
}
