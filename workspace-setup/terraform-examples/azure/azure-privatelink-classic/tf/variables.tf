# =============================================================================
# variables.tf - Input variables for Azure Private Link (classic) workspace
# =============================================================================
# All configurable inputs: naming, subscription, location, resource group,
# network (CIDR, service endpoints), tags, and workspace (public access).
# =============================================================================

# =============================================================================
# Naming
# =============================================================================

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
  description = "Azure region when create_data_plane_resource_group is true (new RG and all resources). When using an existing resource group, leave empty—the template uses the existing group's region for every resource."
  type        = string
  default     = ""
  validation {
    condition     = !var.create_data_plane_resource_group || length(trimspace(var.location)) > 0
    error_message = "location must be set (e.g. eastus2) when create_data_plane_resource_group is true."
  }
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
  description = "CIDR for the data plane VNet address space (e.g. 10.0.0.0/16). Must encompass all subnets. Use a block between /16 and /24."
  type        = string
  validation {
    condition     = length(regexall("^[0-9.]+/(\\d+)$", var.cidr_dp)) > 0 && tonumber(regexall("^[0-9.]+/(\\d+)$", var.cidr_dp)[0][0]) >= 16 && tonumber(regexall("^[0-9.]+/(\\d+)$", var.cidr_dp)[0][0]) <= 24
    error_message = "cidr_dp must be a CIDR block with prefix length between /16 and /24 (e.g. 10.0.0.0/16)."
  }
}

variable "subnet_workspace_cidrs" {
  description = "CIDRs for the Databricks workspace subnets: [public, private]. Must be within the VNet (cidr_dp). Each subnet must be at least /26 (Databricks does not recommend smaller). Example: [\"10.0.0.0/24\", \"10.0.1.0/24\"]."
  type        = list(string)
  validation {
    condition     = length(var.subnet_workspace_cidrs) == 2 && length([for c in var.subnet_workspace_cidrs : 1 if length(regexall("/(\\d+)$", c)) > 0 && tonumber(regexall("/(\\d+)$", c)[0][0]) <= 26]) == 2
    error_message = "subnet_workspace_cidrs must contain exactly two CIDRs [public, private], each with prefix length at least /26 (e.g. /24 or /26)."
  }
}

variable "subnet_private_endpoint_cidr" {
  description = "CIDR for the Private Link subnet (control plane and DBFS private endpoints). Must be within the VNet (cidr_dp). Example: 10.0.2.0/26."
  type        = string
}



variable "create_nat_gateway" {
  description = "When true, creates a NAT gateway and attaches it to the workspace subnets, providing outbound internet access for cluster nodes (e.g. installing packages from PyPI or Maven). Set to false when Microsoft.Storage and Microsoft.EventHub service endpoints cover all required Azure traffic and no general internet egress is needed — for example, in fully private deployments or when a network virtual appliance handles egress. When false, nat_gateway_zones has no effect."
  type        = bool
  default     = true
}

variable "service_endpoint_policy_storage_accounts" {
  description = "Additional Azure Storage account resource IDs to allow through the service endpoint policy, alongside the built-in /services/Azure/Databricks alias. Use this for storage accounts that cluster nodes must reach via the Microsoft.Storage service endpoint — for example, Unity Catalog external location storage accounts or data lake accounts. Each entry must be a full resource ID: /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<name>. Leave empty (default) when only Databricks-managed storage is required."
  type        = list(string)
  default     = []
}

variable "nat_gateway_zones" {
  description = "Availability zones for the NAT gateway and its public IP. Only used when create_nat_gateway is true. Empty list [] (default) creates a non-zonal (regional) NAT gateway, which survives a single-AZ outage. Pinning to a single zone (e.g. [\"1\"]) makes all workspace outbound (SNAT) traffic depend on that one AZ — lower availability than the default. Azure NAT gateway cannot span zones; for zone resilience deploy a NAT gateway per zone. Supply at most one zone."
  type        = list(string)
  default     = []
  validation {
    condition     = length(var.nat_gateway_zones) <= 1
    error_message = "nat_gateway_zones accepts at most one zone. An Azure NAT gateway is either non-zonal (empty list) or pinned to a single zone; it cannot span zones. For zone resilience, deploy a NAT gateway per zone manually."
  }
  validation {
    condition     = alltrue([for z in var.nat_gateway_zones : contains(["1", "2", "3"], z)])
    error_message = "nat_gateway_zones values must each be one of \"1\", \"2\", or \"3\"."
  }
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
# Unity Catalog
# =============================================================================
# Metastore: set metastore_id (assign existing) OR new_metastore_name (create one),
# or neither to attach a metastore manually. Catalog: see new_catalog below.
# =============================================================================

variable "metastore_id" {
  description = "Unity Catalog metastore ID (UUID) of an existing metastore to assign to this workspace via the account API. Azure allows one metastore per region per account, so the regional metastore usually already exists (list with: databricks account metastores list). Leave empty to skip—attach manually after deploy, use account/regional defaults, or set new_metastore_name to create one. Mutually exclusive with new_metastore_name."
  type        = string
  default     = ""
  validation {
    condition     = var.metastore_id == "" || can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.metastore_id))
    error_message = "metastore_id must be empty or a valid UUID (e.g. aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee). Find IDs with: databricks account metastores list."
  }
}

variable "new_metastore_name" {
  description = "Name of a new Unity Catalog metastore to create in the workspace region and assign to the workspace. Requires admin_user (becomes a member of the new metastore's admins group). Leave empty to not create a metastore. Mutually exclusive with metastore_id."
  type        = string
  default     = ""
  validation {
    condition     = can(regex("^[a-zA-Z0-9_-]*$", var.new_metastore_name))
    error_message = "new_metastore_name can only contain alphanumerical characters, hyphens, and underscores."
  }
}

variable "admin_user" {
  description = "Databricks account user (email / user name) to make workspace admin. Required when new_metastore_name is set (added to the metastore admins group). Also granted ALL PRIVILEGES on the user-defined catalog (new_catalog), since otherwise only the Terraform principal (the catalog owner) can see it. Leave empty otherwise."
  type        = string
  default     = ""
}

variable "new_catalog" {
  description = "Set to true to create a user-defined catalog on a dedicated storage account with public network access disabled (access connector allowed by a resource instance rule) (private endpoints for classic compute, NCC private endpoint rules for serverless), together with its access connector, storage credential and external location. Requires a metastore (metastore_id or new_metastore_name). Needs Owner or User Access Administrator on the resource group to create the role assignment."
  type        = bool
  default     = false
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

# =============================================================================
# Cluster Configuration (optional)
# =============================================================================

variable "create_cluster" {
  description = "Set to true to create a UC-compatible single-node classic cluster to validate the deployment. Requires a metastore."
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
# Tags
# =============================================================================

variable "tags" {
  description = "Tags applied to Azure resources that support tags. Leave default {} for none."
  type        = map(string)
  default     = {}
}
