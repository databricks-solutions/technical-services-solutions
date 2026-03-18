terraform {
  required_version = "~> 1.3"

  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.84"
    }
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.76, < 7.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.9"
    }
  }
}

