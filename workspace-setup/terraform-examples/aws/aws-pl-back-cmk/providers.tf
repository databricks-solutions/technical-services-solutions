provider "aws" {
  region = var.region
}

# Account-level provider (used for mws_* resources)
# Auth via env: DATABRICKS_CLIENT_ID, DATABRICKS_CLIENT_SECRET, DATABRICKS_ACCOUNT_ID, DATABRICKS_HOST
# Or use explicit client_id/client_secret attributes
provider "databricks" {
  alias         = "mws"
  account_id    = var.databricks_account_id
  host          = var.databricks_account_host
  client_id     = var.databricks_client_id     # Optional: comment out to use env vars
  client_secret = var.databricks_client_secret # Optional: comment out to use env vars
}

# Workspace-level provider for Unity Catalog resources
provider "databricks" {
  alias         = "workspace"
  host          = databricks_mws_workspaces.ws.workspace_url
  client_id     = var.databricks_client_id
  client_secret = var.databricks_client_secret
}
