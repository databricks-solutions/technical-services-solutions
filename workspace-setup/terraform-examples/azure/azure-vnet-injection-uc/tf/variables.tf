# =============================================================================
# Azure Configuration
# =============================================================================

variable "azure_subscription_id" {
  description = "Your Azure Subscription ID"
  type        = string
}

variable "create_resource_group" {
  description = "Set to true to create the workspace resource group; set to false to reuse the existing group named resource_group_name (it must already exist, and its region is used)."
  type        = bool
  default     = true
}

variable "resource_group_name" {
  description = "Name of the workspace resource group (workspace, access connector, catalog storage). Created when create_resource_group is true, otherwise it must already exist."
  type        = string
}

variable "managed_resource_group_name" {
  description = "Name of the Databricks managed resource group. Leave empty to use mrg-dbw-<resource_prefix> (this template always names it). Must differ from resource_group_name. Changing it forces workspace replacement."
  type        = string
  default     = ""
  validation {
    condition     = var.managed_resource_group_name == "" || var.managed_resource_group_name != var.resource_group_name
    error_message = "managed_resource_group_name must not be the same as resource_group_name."
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

variable "resource_prefix" {
  description = "Prefix for Azure resource names (VNet, NSG, subnets, resource group). Used to derive DBFS storage account name (alphanumeric only, 3-24 chars)."
  type        = string
  default     = "databricks-workspace"
  validation {
    condition     = can(regex("^[a-z0-9-.]{1,40}$", var.resource_prefix))
    error_message = "resource_prefix must be 1-40 characters containing only a-z, 0-9, -, ."
  }
}

variable "workspace_name" {
  description = "Name of the Databricks workspace (3-30 characters: letters, numbers, hyphens, underscores). Leave empty to use dbw-<resource_prefix>."
  type        = string
  default     = ""
  validation {
    condition     = var.workspace_name == "" || can(regex("^[A-Za-z0-9_-]{3,30}$", var.workspace_name))
    error_message = "workspace_name must be 3-30 characters: letters, numbers, hyphens and underscores only."
  }
}

variable "admin_user" {
  description = "Databricks account user (email) made workspace admin and granted ALL PRIVILEGES on the user-defined catalog, external location and storage credential. Required when new_metastore_name is set (added to the metastore admins group); run Terraform as this user in that case. Leave empty to skip."
  type        = string
  default     = ""
}

variable "root_storage_name" {
  description = "Name of the workspace root (DBFS) storage account: lowercase letters and numbers only, 3-24 characters, globally unique. Leave empty to derive it from resource_prefix (\"dbfs\" + up to 20 alphanumeric characters)."
  type        = string
  default     = ""
  validation {
    condition     = var.root_storage_name == "" || can(regex("^[a-z0-9]{3,24}$", var.root_storage_name))
    error_message = "root_storage_name must be 3-24 characters: lowercase letters and numbers only."
  }
}
variable "new_catalog" {
  description = "Set to true to create a user-defined catalog on a dedicated storage account, together with its access connector, storage credential and external location. Requires a metastore (metastore_id or new_metastore_name)."
  type        = bool
  default     = true
}

variable "uc_storage_account_name" {
  description = "Name of the storage account for the Unity Catalog catalog (3-24 chars, lowercase letters and numbers, globally unique). Leave empty to derive it from resource_prefix (\"uc\" + up to 22 alphanumeric characters), which may collide with an existing account. Only used when new_catalog is true."
  type        = string
  default     = ""
  validation {
    condition     = var.uc_storage_account_name == "" || can(regex("^[a-z0-9]{3,24}$", var.uc_storage_account_name))
    error_message = "uc_storage_account_name must be 3-24 characters, lowercase letters and numbers only."
  }
}

variable "uc_container_name" {
  description = "Name of the storage container used as the catalog storage root. Only used when new_catalog is true."
  type        = string
  default     = "uc-catalog"
  validation {
    condition     = can(regex("^[a-z0-9]([a-z0-9]|-[a-z0-9]){2,62}$", var.uc_container_name))
    error_message = "uc_container_name must be 3-63 characters: lowercase letters, numbers and single hyphens, starting and ending with a letter or number."
  }
}

variable "catalog_name" {
  description = "Name of the Unity Catalog catalog. Leave empty to use \"<resource_prefix>_catalog\" (hyphens and dots replaced by underscores)."
  type        = string
  default     = ""
}

variable "storage_credential_name" {
  description = "Name of the Unity Catalog storage credential. Leave empty to use \"<resource_prefix>-storage-credential\"."
  type        = string
  default     = ""
}

variable "external_location_name" {
  description = "Name of the Unity Catalog external location. Leave empty to use \"<resource_prefix>-external-location\"."
  type        = string
  default     = ""
}

variable "location" {
  description = "Azure region to deploy to. Required when create_resource_group is true. When reusing a resource group, leave empty: the template uses that group's region for every regional resource."
  type        = string
  default     = ""
  validation {
    condition = var.location == "" ? !var.create_resource_group : contains([
      "australiacentral", "australiacentral2", "australiaeast", "australiasoutheast", "brazilsouth", "canadacentral", "canadaeast", "centralindia", "centralus", "chinaeast2", "chinaeast3", "chinanorth2", "chinanorth3", "eastasia", "eastus", "eastus2", "francecentral", "germanywestcentral", "japaneast", "japanwest", "koreacentral", "mexicocentral", "northcentralus", "northeurope", "norwayeast", "qatarcentral", "southafricanorth", "southcentralus", "southeastasia", "southindia", "swedencentral", "switzerlandnorth", "switzerlandwest", "uaenorth", "uksouth", "ukwest", "westcentralus", "westeurope", "westindia", "westus", "westus2", "westus3"
    ], var.location)
    error_message = "location must be set to a standard Azure region supported by Databricks when create_resource_group is true; leave it empty only when reusing a resource group."
  }
}

variable "metastore_id" {
  description = "Unity Catalog metastore ID (UUID) of an existing metastore to assign to this workspace via the account API. Azure allows one metastore per region per account, so the regional metastore usually already exists (list with: databricks account metastores list). Leave empty to create one with new_metastore_name, or to skip and attach a metastore manually. Mutually exclusive with new_metastore_name."
  type        = string
  default     = ""
  validation {
    condition     = var.metastore_id == "" || can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.metastore_id))
    error_message = "metastore_id must be empty or a valid UUID (e.g. aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee). Find IDs with: databricks account metastores list."
  }
}

variable "new_metastore_name" {
  description = "Name of a new Unity Catalog metastore to create in the workspace region and assign to the workspace, owned by a new <name>-admins group. Requires admin_user. Leave empty to not create a metastore. Mutually exclusive with metastore_id."
  type        = string
  default     = ""
  validation {
    condition     = can(regex("^[a-zA-Z0-9_-]*$", var.new_metastore_name))
    error_message = "new_metastore_name can only contain alphanumerical characters, hyphens, and underscores."
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
  description = "Whether to create a new VNet. Set to false to bring an existing VNet (specify vnet_name, and vnet_resource_group_name if it is not in the workspace resource group). The template still creates its own public and private subnets and NSG in the VNet, so it needs free address space for both subnet CIDRs."
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
  description = "Resource group for the VNet and networking resources (subnets, NSG, NAT gateway). Leave empty, or set to the same value as resource_group_name, to use the workspace resource group. When create_new_vnet is true and this names a different group, that group is created; when reusing a VNet it must be the group that holds the existing VNet."
  type        = string
  default     = ""
}

variable "vnet_cidr" {
  description = "CIDR of the virtual network address space (e.g. 10.0.0.0/20). Required when create_new_vnet is true; must encompass both workspace subnets. Not used when reusing an existing VNet."
  type        = string
  default     = ""
  validation {
    condition     = !var.create_new_vnet || var.vnet_cidr != ""
    error_message = "vnet_cidr must be set when create_new_vnet is true."
  }
}

variable "subnet_public_cidr" {
  description = "CIDR of the Databricks public (host) subnet. Must be within the VNet (vnet_cidr)."
  type        = string
}

variable "subnet_private_cidr" {
  description = "CIDR of the Databricks private (container) subnet. Must be within the VNet (vnet_cidr)."
  type        = string
}

variable "create_nat_gateway" {
  description = "Create a NAT gateway for outbound internet access from the workspace subnets. This template has no Private Link, so clusters can only reach the Databricks control plane through the NAT gateway: false is rejected here. To deploy without NAT, use the azure-privatelink-classic template, which provides private connectivity."
  type        = bool
  default     = true
}

variable "nat_gateway_zones" {
  description = "Availability zone(s) for the NAT gateway and its public IP. Only used when create_nat_gateway is true. Azure NAT gateway is a zonal resource, so provide at most one zone (e.g. [\"1\"]). Use [] for regions without availability-zone support (non-zonal). Default [\"1\"] preserves prior behavior. For zone-redundant egress, deploy one NAT gateway per zone (not covered by this example)."
  type        = list(string)
  default     = ["1"]
  validation {
    condition     = length(var.nat_gateway_zones) <= 1 && alltrue([for z in var.nat_gateway_zones : contains(["1", "2", "3"], z)])
    error_message = "nat_gateway_zones must be empty (non-zonal) or a single zone from [\"1\", \"2\", \"3\"]. Azure NAT gateway supports only one availability zone."
  }
}
