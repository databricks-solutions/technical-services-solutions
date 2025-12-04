terraform {
  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = ">= 1.16.0"
    }
  }
}

provider "databricks" {
  alias         = "workspace"
  host          = var.workspace_host
  client_id     = var.client_id
  client_secret = var.client_secret
}
