terraform {
  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.91.0"
    }
    aws = {
      source  = "hashicorp/aws"
      version = ">=6.53.0"
    }
    time = {
      source = "hashicorp/time"
    }
  }
}