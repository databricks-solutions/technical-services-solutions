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
    description = "The name of the root storage account"
    type        = string
}

variable "location" {
    description = "The Azure region to deploy the workspace to"
    type        = string
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

variable "vnet_resource_group_name" {
    description = "The name of the resource group where the existing VNet is located"
    type        = string
}

variable "subnet_public_cidr" {
    description = "The CIDR address of the first subnet"
    type        = string
}

variable "subnet_private_cidr" {
    description = "The CIDR address of the second subnet"
    type        = string
}

# =============================================================================
# Customer Managed Keys Configuration
# =============================================================================

# variable "managed_services_cmk_key_vault_id" {
#     description = "The Key Vault ID of the CMK for managed services encryption"
#     type        = string
# }

# variable "managed_services_cmk_key_vault_key_id" {
#     description = "The CMK ID for managed services encryption"
#     type        = string
# }

# variable "managed_disk_cmk_key_vault_id" {
#     description = "The Key Vault ID of the CMK for managed disks encryption"
#     type        = string
# }

# variable "managed_disk_cmk_key_vault_key_id" {
#     description = "The CMK ID for managed disks encryption"
#     type        = string
# }