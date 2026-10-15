terraform {
  required_version = ">= 1.5"
  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = ">= 1.136.0"
    }
  }
  # Use a remote backend with locking in real use, for example:
  # backend "azurerm" { ... }
}

# Runs as the Terraform service principal, which needs MANAGE on the system.ai schema.
# Any workspace attached to the metastore works: grants are stored in the metastore.
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
