variable "resource_group" {
  type        = string
  description = "Azure resource group name"
}

variable "location" {
  type        = string
  description = "Azure region/location for resources"
}

variable "create_storage_account" {
  type        = bool
  description = "Whether to create a storage account"
  default     = true
}

variable "storage_account_name" {
  type        = string
  description = "Name of the Azure storage account"
}

variable "tags" {
  type        = map(string)
  description = "Tags to apply to Azure resources"
}