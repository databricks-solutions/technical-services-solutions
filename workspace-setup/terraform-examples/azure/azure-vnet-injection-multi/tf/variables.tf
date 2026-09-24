# =============================================================================
# Azure Configuration
# =============================================================================

variable "tenant_id" {
  description = "Your Azure Tenant ID"
  type        = string
}

variable "azure_subscription_id" {
  description = "Your Azure Subscription ID"
  type        = string
}

variable "create_resource_group" {
  description = "Whether Terraform should create the resource group. If false, RG must already exist."
  type        = bool
}

variable "resource_group_name" {
  description = "The name of the resource group"
  type        = string
}

variable "tags" {
  description = "A map of tags to assign to the resources"
  type        = map(string)
  default     = {}
}

# =============================================================================
# Databricks Configuration
# =============================================================================

variable "databricks_account_id" {
  description = "ID of the Databricks account"
  type        = string
  sensitive   = true
}

variable "admin_user" {
  description = "The email of the user to assign admin access to the workspaces"
  type        = string
}

variable "workspaces" {
  description = "Map of Databricks workspaces to create"
  type = map(object({
    workspace_name              = string
    root_storage_name           = string
    subnet_public_cidr          = string
    subnet_private_cidr         = string
    managed_resource_group_name = optional(string)
  }))
}

variable "location" {
  description = "The Azure region to deploy resources to"
  type        = string
  validation {
    condition = contains([
      "australiacentral", "australiacentral2", "australiaeast", "australiasoutheast",
      "brazilsouth", "canadacentral", "canadaeast", "centralindia", "centralus",
      "chinaeast2", "chinaeast3", "chinanorth2", "chinanorth3",
      "eastasia", "eastus", "eastus2", "francecentral", "germanywestcentral",
      "japaneast", "japanwest", "koreacentral", "mexicocentral",
      "northcentralus", "northeurope", "norwayeast", "qatarcentral",
      "southafricanorth", "southcentralus", "southeastasia", "southindia",
      "swedencentral", "switzerlandnorth", "switzerlandwest",
      "uaenorth", "uksouth", "ukwest",
      "westcentralus", "westeurope", "westindia",
      "westus", "westus2", "westus3"
    ], var.location)
    error_message = "Valid values for var.location are standard Azure regions supported by Databricks."
  }
}

variable "existing_metastore_id" {
  description = "The ID of the existing metastore. Leave empty to skip metastore creation."
  type        = string
  default     = ""
}

variable "new_metastore_name" {
  description = "The name of the new metastore (used only if creating one)."
  type        = string
  default     = ""
  validation {
    condition     = can(regex("^[a-zA-Z0-9_-]*$", var.new_metastore_name))
    error_message = "metastore_name can only contain alphanumerical characters, hyphens, and underscores."
  }
}

# =============================================================================
# Network Configuration
# =============================================================================

variable "vnet_name" {
  description = "The name of the virtual network to create"
  type        = string
}

variable "vnet_resource_group_name" {
  description = "The resource group for the VNet. If different from resource_group_name, a separate RG will be created."
  type        = string
}

variable "cidr" {
  description = "The CIDR address space of the virtual network"
  type        = string
  default     = "10.10.0.0/16"
}