variable "databricks_account_id" {
  type        = string
  description = "Databricks account ID"
  sensitive   = true
}

# OAuth M2M credentials are read from environment variables:
#   DATABRICKS_CLIENT_ID, DATABRICKS_CLIENT_SECRET
# Set them in your shell before running terraform (see README).

variable "region" {
  type        = string
  description = "AWS region for both the workspace and NCC"

  validation {
    condition     = can(regex("^[a-z]{2}-[a-z]+-[0-9]+$", var.region))
    error_message = "region must look like an AWS region code, e.g. us-east-1, ap-south-1."
  }
}

variable "prefix" {
  type        = string
  description = "Name prefix used for default NCC naming if ncc_name is not set"

  validation {
    condition     = can(regex("^[a-z0-9-]{1,40}$", var.prefix))
    error_message = "prefix must be 1-40 chars, lowercase letters, digits, or hyphen."
  }
}

variable "ncc_name" {
  type        = string
  description = "Name for the Network Connectivity Configuration. Defaults to ncc-<prefix>. Change this to force creation of a new NCC (the old one will be destroyed)."
  default     = null
}

variable "create_new_workspace" {
  type        = bool
  description = "If true, create a new serverless workspace. If false, use an existing workspace."
  default     = true
}

variable "workspace_name" {
  type        = string
  description = "Workspace name to create when create_new_workspace=true"
  default     = "serverless-workspace"
}

variable "existing_workspace_id" {
  type        = string
  description = "Existing workspace ID to bind the NCC to"
  default     = null
}

variable "existing_workspace_name" {
  type        = string
  description = "Existing workspace name to look up when existing_workspace_id is not provided"
  default     = null
}

variable "create_private_endpoint_rule" {
  type        = bool
  description = "If true, create an AWS NCC private endpoint rule"
  default     = false
}

variable "endpoint_service" {
  type        = string
  description = "AWS VPC endpoint service name, for example com.amazonaws.vpce.us-east-1.vpce-svc-xxxxxxxxxxxxxxxxx"
  default     = null
}

variable "domain_names" {
  type        = list(string)
  description = "FQDNs that should route over the NCC private endpoint rule"
  default     = []
}

variable "use_existing_metastore" {
  type        = bool
  description = "If true, use an existing metastore (looked up by id, name, or region in that priority). If false, create a new one. Note: a Databricks account is limited to one metastore per region, so set this to true if your account already has one in this region."
  default     = false
}

variable "existing_metastore_id" {
  type        = string
  description = "Existing metastore ID"
  default     = null
}

variable "existing_metastore_name" {
  type        = string
  description = "Existing metastore name"
  default     = null
}

variable "metastore_name" {
  type        = string
  description = "Name to use when creating a new metastore"
  default     = null
}

variable "workspace_admin_email" {
  type        = string
  description = "Email of the user to set as workspace admin, metastore owner, and external location/storage credential owner"

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.workspace_admin_email))
    error_message = "workspace_admin_email must be a valid email address."
  }
}

variable "existing_workspace_host" {
  type        = string
  description = "Workspace URL (https://...) when create_new_workspace=false. Required for the workspace-level Databricks provider used by storage credential, external location, and grants."
  default     = null
}

variable "external_location_bucket_name" {
  type        = string
  description = "S3 bucket that will get an NCC private endpoint rule, bucket policy, and Unity Catalog external location"

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.external_location_bucket_name))
    error_message = "external_location_bucket_name must be a valid S3 bucket name (3-63 chars, lowercase letters, digits, dots, hyphens; cannot start or end with hyphen/dot)."
  }
}

variable "merge_existing_bucket_policy" {
  type        = bool
  description = "If true, read the existing bucket policy and append the VPCE allow statement instead of replacing it. Use when the bucket already has a policy."
  default     = false
}

variable "external_location_path" {
  type        = string
  description = "Optional prefix inside the bucket for the external location"
  default     = ""
}

variable "storage_credential_name" {
  type        = string
  description = "Name of the Unity Catalog storage credential"
  default     = null
}

variable "external_location_name" {
  type        = string
  description = "Name of the Unity Catalog external location"
  default     = null
}

variable "uc_iam_role_name" {
  type        = string
  description = "AWS IAM role name used by the Unity Catalog storage credential"
  default     = null
}

variable "external_location_grant_principal" {
  type        = string
  description = "Optional principal to grant access to the external location"
  default     = null
}


