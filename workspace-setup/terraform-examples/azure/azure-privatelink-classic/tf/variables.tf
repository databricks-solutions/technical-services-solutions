# =============================================================================
# variables.tf - Input variables for Azure Private Link (classic) workspace
# =============================================================================
# All configurable inputs: naming, subscription, location, resource group,
# network (CIDR, service endpoints), tags, and workspace (public access).
# =============================================================================

# =============================================================================
# Naming
# =============================================================================

variable "prefix" {
  description = "Prefix for Databricks workspace and display names"
  type        = string
  default     = "databricks-workspace"
}

variable "resource_prefix" {
  description = "Prefix for Azure resource names (VNet, NSG, subnets, resource group). Used to derive DBFS storage account name (alphanumeric only, 3-24 chars)."
  type        = string
  default     = "databricks-workspace"
  validation {
    condition     = can(regex("^[a-z0-9-.]{1,40}$", var.resource_prefix))
    error_message = "resource_prefix must be 1-40 characters containing only a-z, 0-9, -, ."
  }
}

# =============================================================================
# Azure Configuration
# =============================================================================

variable "az_subscription" {
  description = "Azure subscription ID where resources will be deployed"
  type        = string
}

variable "location" {
  description = "Azure region for the resource group and all resources (e.g. eastus2)"
  type        = string
}

variable "create_data_plane_resource_group" {
  description = "Set to true to create a new resource group for data plane resources; set to false to use existing_data_plane_resource_group_name"
  type        = bool
}

variable "existing_data_plane_resource_group_name" {
  description = "Name of the existing resource group when create_data_plane_resource_group is false"
  type        = string
  default     = ""
  validation {
    condition     = var.create_data_plane_resource_group || length(var.existing_data_plane_resource_group_name) > 0
    error_message = "existing_data_plane_resource_group_name must be set when create_data_plane_resource_group is false."
  }
}

# =============================================================================
# Network Configuration
# =============================================================================

variable "cidr_dp" {
  description = "CIDR for the data plane VNet (e.g. 10.139.0.0/16). Public, private, and Private Link subnets are derived from this."
  type        = string
}

variable "subnets_service_endpoints" {
  description = "List of Azure service endpoints to associate with the public and private subnets (e.g. [\"Microsoft.Storage\"])"
  type        = list(string)
  default     = []
}

# =============================================================================
# Databricks account (for serverless NCC)
# =============================================================================
# NCC is always created so serverless compute (SQL warehouses, serverless jobs)
# can reach DBFS over Private Link. Required for serverless to work with root storage.
# =============================================================================

variable "databricks_account_id" {
  description = "Databricks account ID (required for serverless NCC). Find it in the account console URL: https://accounts.azuredatabricks.net/accounts/<account_id>"
  type        = string
}

# =============================================================================
# Tags
# =============================================================================

variable "tags" {
  description = "Tags to apply to all Azure resources. Merged with Project = prefix (user tags take precedence)."
  type        = map(string)
  default     = {}
}

