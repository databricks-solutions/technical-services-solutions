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

variable "resource_group_name" {
  description = "The name of the resource group"
  type        = string
}

variable "managed_resource_group_name" {
  description = "The name of managed resource group. This is optional field"
  type        = string
  default     = null
  validation {
    condition     = var.managed_resource_group_name == null || length(var.managed_resource_group_name) > 0
    error_message = "managed_resource_group_name must not be an empty string. Leave it as null to let Azure auto-generate one."
  }
  validation {
    condition     = var.managed_resource_group_name != var.resource_group_name
    error_message = "Managed resource group name should not be same as resource group name"
  }
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

variable "workspace_name" {
  description = "The name of the Databricks workspace"
  type        = string
}

variable "admin_user" {
  description = "The email of the user to assign admin access to the workspace and the new metastore"
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
variable "catalog_name" {
  type        = string
  description = "The name of the Unity Catalog catalog"
}

variable "storage_credential_name" {
  type        = string
  description = "The name of the Databricks storage credential"
}

variable "external_location_name" {
  type        = string
  description = "The name of the external location"
}
variable "uc_storage_account_name" {
  type        = string
  description = "Azure storage account name for the Unity Catalog external location. Must be globally unique, only lowercase letters and numbers, 3-24 characters."
  validation {
    condition     = length(var.uc_storage_account_name) >= 3 && length(var.uc_storage_account_name) <= 24
    error_message = "uc_storage_account_name must be between 3 and 24 characters."
  }
  validation {
    condition     = can(regex("^[a-z0-9]+$", var.uc_storage_account_name))
    error_message = "uc_storage_account_name can only contain lowercase letters and numbers."
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

variable "existing_metastore_id" {
  description = "The ID of the existing metastore. Leave empty to create a new metastore."
  type        = string
  default     = ""
}

variable "new_metastore_name" {
  description = "The name of the new metastore."
  type        = string
  default     = ""
  validation {
    condition     = can(regex("^[a-zA-Z0-9_-]*$", var.new_metastore_name))
    error_message = "metastore_name can only contain alphanumerical characters, hyphens, and underscores."
  }
}

variable "node_type_id" {
  description = "Azure VM SKU for the single-node UC cluster driver."
  type        = string
  default     = "Standard_DS3_v2"
}

variable "autotermination_minutes" {
  description = "Idle minutes before the single-node UC cluster auto-terminates."
  type        = number
  default     = 10
  validation {
    condition     = var.autotermination_minutes >= 10
    error_message = "autotermination_minutes must be at least 10 (Databricks minimum for auto-termination)."
  }
}

variable "data_security_mode" {
  description = "Access mode for the UC-compatible single-node cluster. SINGLE_USER is required for UC workloads with the Personal Compute policy."
  type        = string
  default     = "SINGLE_USER"
  validation {
    condition     = contains(["SINGLE_USER", "USER_ISOLATION", "NONE", "LEGACY_TABLE_ACL", "LEGACY_PASSTHROUGH", "LEGACY_SINGLE_USER", "LEGACY_SINGLE_USER_STANDARD"], var.data_security_mode)
    error_message = "data_security_mode must be one of: SINGLE_USER, USER_ISOLATION, NONE, LEGACY_TABLE_ACL, LEGACY_PASSTHROUGH, LEGACY_SINGLE_USER, LEGACY_SINGLE_USER_STANDARD."
  }
}

# =============================================================================
# Network Configuration
# =============================================================================

variable "vnet_resource_group_name" {
  description = "The name of the VNet resource group"
  type        = string
  validation {
    condition     = var.vnet_resource_group_name != var.resource_group_name
    error_message = "vnet_resource_group_name must not be the same as resource_group_name"
  }
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
