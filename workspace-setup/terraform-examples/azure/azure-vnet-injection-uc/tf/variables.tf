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
#=============================================================================
# Cluster Configuration (optional)
#=============================================================================
variable "create_cluster" {
  description = "Whether to create a cluster"
  type        = bool
  default     = false
}

variable "node_type_id" {
  description = "Azure VM SKU for the single-node UC cluster driver."
  type        = string
  default     = "Standard_DS3_v2"
}

variable "cluster_autotermination_minutes" {
  description = "Idle minutes before the single-node UC cluster auto-terminates."
  type        = number
  default     = 10
  validation {
    condition     = var.cluster_autotermination_minutes >= 10
    error_message = "cluster_autotermination_minutes must be at least 10 (Databricks minimum for auto-termination)."
  }
}

# =============================================================================
# Network Configuration
# =============================================================================

variable "create_new_vnet" {
  description = "Whether to create a new VNet. Set to false to bring an existing VNet (specify vnet_name and vnet_resource_group_name)."
  type        = bool
  default     = true
}

variable "vnet_name" {
  description = "The name of the virtual network. When create_new_vnet is false, this must be the name of the existing VNet to reuse."
  type        = string
  default     = ""
  validation {
    condition     = var.create_new_vnet || length(var.vnet_name) > 0
    error_message = "vnet_name must be set to the existing VNet name when create_new_vnet is false."
  }
}

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

variable "nat_gateway_zones" {
  description = "Availability zone(s) for the NAT gateway and its public IP. Azure NAT gateway is a zonal resource, so provide at most one zone (e.g. [\"1\"]). Use [] for regions without availability-zone support (non-zonal). Default [\"1\"] preserves prior behavior. For zone-redundant egress, deploy one NAT gateway per zone (not covered by this example)."
  type        = list(string)
  default     = ["1"]
  validation {
    condition     = length(var.nat_gateway_zones) <= 1 && alltrue([for z in var.nat_gateway_zones : contains(["1", "2", "3"], z)])
    error_message = "nat_gateway_zones must be empty (non-zonal) or a single zone from [\"1\", \"2\", \"3\"]. Azure NAT gateway supports only one availability zone."
  }
}

# =============================================================================
# Unity Catalog Storage Security (optional)
# =============================================================================
# The UC external-location storage account is created with TLS 1.2, infrastructure
# encryption, and no public blob access. This is a VNet-injection (non-Private Link)
# example, so the account keeps its public endpoint; the firewall below (with the
# Microsoft.Storage service endpoint already enabled on the workspace subnets) is the
# lock-down lever. Network access defaults to open so the example applies without
# extra setup.

variable "uc_storage_network_default_action" {
  description = "Default action for the UC storage account firewall. \"Allow\" (default) keeps the account reachable for the initial deploy; \"Deny\" restricts access to AzureServices plus the IPs/subnets granted below."
  type        = string
  default     = "Allow"
  validation {
    condition     = contains(["Allow", "Deny"], var.uc_storage_network_default_action)
    error_message = "uc_storage_network_default_action must be either \"Allow\" or \"Deny\"."
  }
}

variable "uc_storage_allowed_ip_rules" {
  description = "Public IP addresses/CIDRs allowed to reach the UC storage account when uc_storage_network_default_action = \"Deny\". Include the IP running Terraform so container creation succeeds. Ignored when the default action is \"Allow\"."
  type        = list(string)
  default     = []
}

variable "uc_storage_allowed_subnet_ids" {
  description = "Subnet IDs allowed to reach the UC storage account when uc_storage_network_default_action = \"Deny\" (e.g. the workspace public/private subnets). Each subnet must have the Microsoft.Storage service endpoint enabled. Ignored when the default action is \"Allow\"."
  type        = list(string)
  default     = []
}
