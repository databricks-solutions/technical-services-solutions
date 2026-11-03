terraform {
  required_version = ">= 1.5"
  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.136" # 1.136 or later 1.x: schema-level databricks_connection (MCP service) needs 1.136
      # In your own repo, commit the .terraform.lock.hcl that terraform init creates, so that every
      # run uses the same provider version and checksums.
    }
  }
  # Use a remote backend with locking and encryption, and give only the pipeline identity access:
  # the state holds the MCP bearer token from custom_services.tf. For example:
  # backend "azurerm" { ... }
}

# Runs as the Terraform service principal. It needs MANAGE on the system.ai schema, and for your own
# services USE CATALOG, USE SCHEMA, CREATE SERVICE and CREATE CONNECTION on their schema, plus
# READ_SECRET on the provider key secret. Authenticate with workload identity federation (OIDC) in
# CI, not with a personal access token or a long-lived client secret.
# Any workspace attached to the metastore works: services and grants are stored in the metastore.
provider "databricks" {
  host = var.workspace_url
}

variable "workspace_url" {
  type = string
}

variable "break_glass_group" {
  description = "Admin group that keeps EXECUTE on every model. databricks_grants needs at least one grant per model."
  type        = string
}
