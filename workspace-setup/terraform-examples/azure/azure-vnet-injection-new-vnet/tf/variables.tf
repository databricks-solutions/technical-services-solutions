# =============================================================================
# Azure Configuration
# =============================================================================

variable "azure_subscription_id" {
    description = "Your Azure Subscription ID"
    type        = string
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
# Databricks Workspace Configuration
# =============================================================================

variable "workspace_name" {
    description = "The name of the Databricks workspace"
    type        = string  
}

variable "root_storage_name" {
  type        = string
  description = "The root storage name. Only lowercase letters and numbers, 3-24 characters."
  validation {
    condition     = length(var.root_storage_name) >= 3 && length(var.root_storage_name) <= 24
    error_message = "root_storage_name must be between 3 and 24 characters."
  }
  validation {
    condition     = can(regex("^[a-z0-9]+$", var.root_storage_name))
    error_message = "root_storage_name can only contain lowercase letters and numbers."
  }
}

variable "location" {
    description = "The Azure region to deploy the workspace to"
    type        = string
    validation {
    condition = contains([
      "australiacentral", "australiacentral2", "australiaeast", "australiasoutheast", "brazilsouth", "canadacentral", "canadaeast", "centralindia", "centralus", "chinaeast2", "chinaeast3", "chinanorth2", "chinanorth3", "eastasia", "eastus", "eastus2", "francecentral", "germanywestcentral", "japaneast", "japanwest", "koreacentral", "mexicocentral", "northcentralus", "northeurope", "norwayeast", "qatarcentral", "southafricanorth", "southcentralus", "southeastasia", "southindia", "swedencentral", "switzerlandnorth", "switzerlandwest", "uaenorth", "uksouth", "ukwest", "westcentralus", "westeurope", "westindia", "westus", "westus2", "westus3"
    ], var.location)
    error_message = "Valid values for var.location are standard Azure regions supported by Databricks."
  }
}

# =============================================================================
# Network Configuration
# =============================================================================

variable "vnet_name" {
    description = "The name of the virtual network"
    type        = string
}

variable "cidr" {
    description = "The CIDR address of the virtual network"
    type        = string
    default     = "10.0.0.0/20"
}

variable "subnet_public_cidr" {
    description = "The CIDR address of the first subnet"
    type        = string
}

variable "subnet_private_cidr" {
    description = "The CIDR address of the second subnet"
    type        = string
}

