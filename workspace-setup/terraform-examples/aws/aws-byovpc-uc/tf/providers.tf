# Authenticate using environment variables: https://docs.aws.amazon.com/cli/v1/userguide/cli-configure-envvars.html
# export AWS_ACCESS_KEY_ID=KEY_ID
# export AWS_SECRET_ACCESS_KEY=SECRET_KEY
# export AWS_SESSION_TOKEN=SESSION_TOKEN

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Resource = var.resource_prefix
      Project  = var.prefix
    }
  }
}

# OAuth M2M (service principal). For terraform plan/apply:
#   export DATABRICKS_AUTH_TYPE=oauth-m2m
#   export DATABRICKS_CLIENT_ID=...
#   export DATABRICKS_CLIENT_SECRET=...   # SP OAuth secret, not a PAT
#   unset DATABRICKS_HOST DATABRICKS_ACCOUNT_ID DATABRICKS_TOKEN

provider "databricks" {
  alias      = "mws"
  host       = "https://accounts.cloud.databricks.com"
  account_id = var.databricks_account_id
  auth_type  = "oauth-m2m"
}

provider "databricks" {
  alias        = "workspace"
  host         = databricks_mws_workspaces.this.workspace_url
  workspace_id = databricks_mws_workspaces.this.workspace_id
}