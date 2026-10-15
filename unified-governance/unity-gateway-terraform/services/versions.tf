terraform {
  required_version = ">= 1.5"
  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = ">= 1.137.0" # tested version; model_service grants need >= 1.136.0
    }
  }
  # Use a remote backend with locking and encryption in real use: the state holds the
  # provider API key from custom_services.tf. For example:
  # backend "azurerm" { ... }
}

# Runs as the Terraform service principal. It needs MANAGE on the system.ai schema, and for your own
# services USE CATALOG, USE SCHEMA, CREATE SERVICE and CREATE CONNECTION on their schema.
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
  default     = "platform-admins"
}
