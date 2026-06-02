# =============================================================================
# Databricks Configuration
# =============================================================================

variable "databricks_account_id" {
  description = "ID of the Databricks account"
  type        = string
  sensitive   = true
}

variable "prefix" {
  description = "Prefix for Databricks resource names (workspace name, storage config, etc.)"
  type        = string
  default     = "databricks-workspace"
}

variable "resource_prefix" {
  description = "Prefix for naming AWS resources (VPC, S3, IAM, etc.)"
  type        = string
  default     = "databricks-workspace"
  validation {
    condition     = can(regex("^[a-z0-9-.]{1,40}$", var.resource_prefix))
    error_message = "Invalid resource prefix. Allowed 40 characters containing only a-z, 0-9, -, ."
  }
}

variable "pricing_tier" {
  description = "Pricing tier for Databricks workspace"
  type        = string
  default     = "PREMIUM"
  validation {
    condition     = contains(["ENTERPRISE", "PREMIUM"], var.pricing_tier)
    error_message = "pricing_tier must be either 'ENTERPRISE' or 'PREMIUM'."
  }
}

# =============================================================================
# AWS Configuration
# =============================================================================

variable "region" {
  description = "AWS region code where resources will be deployed"
  type        = string
  validation {
    condition = contains([
      "ap-northeast-1", "ap-northeast-2", "ap-south-1", "ap-southeast-1",
      "ap-southeast-2", "ca-central-1", "eu-central-1", "eu-west-1",
      "eu-west-2", "eu-west-3", "sa-east-1", "us-east-1", "us-east-2", "us-west-2"
    ], var.region)
    error_message = "Valid values for var.region are standard AWS regions supported by Databricks."
  }
}

variable "tags" {
  description = "Additional tags to apply to all AWS resources"
  type        = map(string)
  default     = {}
}

# =============================================================================
# Network Configuration
# =============================================================================

variable "vpc_cidr_range" {
  description = "CIDR range for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "List of AWS availability zones for subnet distribution"
  type        = list(string)
  default     = []
}

variable "private_subnets_cidr" {
  description = "List of private subnet CIDR blocks"
  type        = list(string)
  default     = []
}

variable "public_subnets_cidr" {
  description = "List of public subnet CIDR blocks"
  type        = list(string)
  default     = []
}

variable "intra_subnet_cidr" {
  description = "List of intra subnet CIDR blocks that contain the VPC endpoints"
  type        = list(string)
  default     = []
}

# =============================================================================
# Security Group Configuration
# =============================================================================

variable "security_group_ids" {
  description = "Existing security group IDs to use. If empty, default VPC security group will be used"
  type        = list(string)
  default     = []
}

variable "sg_egress_ports" {
  description = "List of egress ports to allow in security group rules"
  type        = list(number)
  default     = [443, 3306, 2443, 5432, 8443, 8444, 8445, 8446, 8447, 8448, 8449, 8450, 8451]
}

# =============================================================================
# Unity Catalog Metastore Configuration
# =============================================================================

variable "aws_account_id" {
  description = "AWS account ID where resources are deployed (used to construct IAM role ARNs for Unity Catalog)"
  type        = string
}

variable "metastore_id" {
  description = "Existing Unity Catalog metastore ID. If empty, a new metastore will be created"
  type        = string
  default     = ""
}

variable "metastore_name" {
  description = "Name for the Unity Catalog metastore. Required only when metastore_id is empty (new metastore)."
  type        = string
  default     = ""
  validation {
    condition     = var.metastore_id != "" || var.metastore_name != ""
    error_message = "metastore_name is required when creating a new metastore (metastore_id is empty)."
  }
}
# =============================================================================
# User Defined Catalog
# =============================================================================
variable "catalog_name" {
  description = "Name for the user defined catalog"
  type        = string
  default     = ""
}

variable "external_location_name" {
  description = "Name for the user defined external location"
  type        = string
  default     = ""
}

variable "storage_credential_name" {
  description = "Name for the user defined storage credential (Unity Catalog). If empty, defaults to \"{resource_prefix}-storage-credential\""
  type        = string
  default     = ""
}