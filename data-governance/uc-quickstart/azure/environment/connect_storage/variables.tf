variable "storage_account_resource_group" {
  type        = string
  description = "Existing resource group for the storage account"
}

variable "location" {
  type        = string
  description = "Azure region/location"
}

variable "storage_account_name" {
  type        = string
  description = "Name of the Azure storage account"
}

variable "create_storage_account" {
  type        = bool
  description = "Whether to create a storage account"
  default     = true
}

variable "enable_file_events" {
  type        = bool
  description = "Whether to enable file events permissions for the storage account"
  default     = true
}

variable "tags" {
  type        = map(string)
  description = "Tags to apply to Azure resources"
}