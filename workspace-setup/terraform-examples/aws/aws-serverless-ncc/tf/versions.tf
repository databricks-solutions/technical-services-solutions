terraform {
  # 1.4.0 required for terraform_data resource (used in s3_endpoint.tf — none currently, but pinned for safety)
  required_version = ">= 1.4.0"

  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = ">= 1.76.0"
    }
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.0"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.13"
    }
    external = {
      source  = "hashicorp/external"
      version = "~> 2.3"
    }
  }
}
