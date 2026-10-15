terraform {
  required_version = ">= 1.5"
  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = ">= 1.137.0"
    }
  }
  # Use a remote backend with locking in real use. The state holds the provider API key.
}

provider "databricks" {
  host = var.workspace_url
}

variable "workspace_url" {
  type = string
}

variable "catalog" {
  description = "Catalog that holds the services. Callers need USE CATALOG on it."
  type        = string
}

variable "schema" {
  description = "Schema that holds the services. Callers need USE SCHEMA on it."
  type        = string
  default     = "ai_services"
}

variable "provider_base_url" {
  description = "Full URL of the provider's OpenAI-compatible chat completions endpoint. Unity Gateway adds no path to it."
  type        = string
  default     = "https://api.example.com/v1/chat/completions"
}

variable "provider_api_key" {
  description = "Provider API key. Pass it with TF_VAR_provider_api_key, never in code."
  type        = string
  sensitive   = true
}

variable "ai_users_group" {
  type    = string
  default = "ai-app-developers"
}
