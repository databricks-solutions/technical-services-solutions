variable "aws_account_id" {
  type        = string
  description = "AWS account ID"
}

variable "catalog_name" {
  type        = string
  description = "Name of the Unity Catalog catalog to create"
}

variable "bucket_name" {
  type        = string
  description = "Name of the S3 bucket to create"
}

variable "force_destroy_s3_bucket" {
  type        = bool
  description = "Whether to force destroy the S3 bucket when removing"
  default     = false
}

# Making force_destroy configurable to prevent accidental data loss
variable "force_destroy_external_location" {
  description = "Whether to force destroy the external location when removing"
  type        = bool
  default     = false  # Default to false for safety in production
}

# Making catalog force_destroy configurable for production safety
variable "force_destroy_catalog" {
  description = "Whether to force destroy the catalog when removing. WARNING: This will delete all catalog data including schemas and tables!"
  type        = bool
  default     = false  # Default to false for safety in production environments
}

variable "owner" {
  type        = string
  description = "Owner of the catalog (user email, group name or service principal ID)"
}