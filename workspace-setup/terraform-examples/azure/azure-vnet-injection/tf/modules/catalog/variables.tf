variable "storage_account_id" {
  type        = string
  description = "ID of the Azure storage account"
}

variable "storage_account_name" {
  type        = string
  description = "Name of the Azure storage account"
}

variable "storage_container_name" {
  type        = string
  description = "Name of the storage container"
}

variable "storage_credential_id" {
  type        = string
  description = "ID of the storage credential in Unity Catalog"
}

variable "catalog_name" {
  type        = string
  description = "Name of the Unity Catalog catalog to create"
}

# Making force_destroy configurable to prevent accidental data loss
variable "force_destroy_external_location" {
  description = "Whether to force destroy the external location when removing. WARNING: This will delete all data!"
  type        = bool
  default     = false  # Default to false for safety in production
}

# Making catalog force_destroy configurable for production safety
variable "force_destroy_catalog" {
  description = "Whether to force destroy the catalog when removing. WARNING: This will delete all catalog data including schemas and tables!"
  type        = bool
  default     = false  # Default to false for safety in production environments
}