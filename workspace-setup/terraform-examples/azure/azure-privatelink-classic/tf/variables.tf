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

variable "subnets_service_endpoints" {
  description = "List of Azure service endpoints to associate with the public and private subnets (e.g. [\"Microsoft.Storage\"])"
  type        = list(string)
  default     = []
}

variable "nat_gateway_zones" {
  description = "Availability zones for the NAT gateway and its public IP. Empty list [] (default) creates a non-zonal (regional) NAT gateway, which survives a single-AZ outage. Pinning to a single zone (e.g. [\"1\"]) makes all workspace outbound (SNAT) traffic depend on that one AZ — lower availability than the default. Azure NAT gateway cannot span zones; for zone resilience deploy a NAT gateway per zone. Supply at most one zone."
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

variable "metastore_id" {
  description = "Unity Catalog metastore ID (UUID) of an existing metastore to assign to this workspace via the account API. Leave empty to skip—attach manually after deploy or use account/regional defaults if your org configures them."
  type        = string
  default     = ""
  validation {
    condition     = var.metastore_id == "" || can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.metastore_id))
    error_message = "metastore_id must be empty or a valid UUID (e.g. aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee). Find IDs with: databricks account metastores list."
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

