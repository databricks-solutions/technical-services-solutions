variable "storage_account_resource_group" {
  type        = string
  description = "Name of the storage account resource group"
}

variable "storage_account_name" {
  type        = string
  description = "Name of the storage account"
}

variable "location" {
  type        = string
  description = "Azure region/location for resources"
}

variable "catalogs" {
    type = map(object({
        name = string
        owner = string
        permissions = list(object({
            principal = string
            privileges = list(string)
        }))
    }))
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to the storage resources"
  default     = {}
}
