variable "project" { type = string }
variable "region" { type = string }

# ==================== NETWORKING OPTIONS ====================
# Option 1: Create new VPC (set create_new_vpc = true)
variable "create_new_vpc" {
  type        = bool
  default     = true
  description = "Set to true to create new VPC, false to use existing VPC"
}

# Variables for NEW VPC creation
variable "vpc_cidr" {
  type        = string
  default     = ""
  description = "CIDR block for new VPC (required if create_new_vpc = true)"
}

variable "private_subnet_cidrs" {
  type        = list(string)
  default     = []
  description = "Two CIDR blocks in distinct AZs (required if create_new_vpc = true)"
}

# Variables for EXISTING VPC
variable "existing_vpc_id" {
  type        = string
  default     = ""
  description = "ID of existing VPC (required if create_new_vpc = false)"
}

variable "existing_subnet_ids" {
  type        = list(string)
  default     = []
  description = "List of existing subnet IDs in different AZs (required if create_new_vpc = false)"
}

variable "existing_security_group_id" {
  type        = string
  default     = ""
  description = "ID of existing security group for Databricks workspace (optional if create_new_vpc = false)"
}

# ==================== CMK OPTIONS ====================
# Option 2: Create new CMK or use existing
variable "create_new_cmk" {
  type        = bool
  default     = true
  description = "Set to true to create new CMK, false to use existing CMK"
}

variable "existing_cmk_arn" {
  type        = string
  default     = ""
  description = "ARN of existing KMS CMK (required if create_new_cmk = false)"
}

# Databricks account
variable "databricks_account_id" { type = string }
variable "databricks_account_host" {
  type    = string
  default = "https://accounts.cloud.databricks.com"
}
variable "databricks_client_id" {
  type      = string
  sensitive = true
}
variable "databricks_client_secret" {
  type      = string
  sensitive = true
}

# Root bucket for workspace storage
variable "root_bucket_name" { type = string }

# Cross-account role external ID (from Databricks Account Console -> Cloud resources -> Credentials)
variable "databricks_crossaccount_role_external_id" { type = string }

# PrivateLink service names for your region (from Databricks table)
variable "pl_service_names" {
  type = object({
    workspace = string # com.amazonaws.vpce.<region>.vpce-svc-xxxxxxxxxxxxxxxxx
    scc       = string # com.amazonaws.vpce.<region>.vpce-svc-xxxxxxxxxxxxxxxxx
  })
}

# Optional: add STS/Kinesis endpoints & S3 Gateway
variable "enable_extra_endpoints" {
  type    = bool
  default = false
}
