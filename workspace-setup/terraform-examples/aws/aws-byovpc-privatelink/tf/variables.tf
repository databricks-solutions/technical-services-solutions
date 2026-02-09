# =============================================================================
# Databricks Configuration
# =============================================================================

variable "databricks_account_id" {
  description = "ID of the Databricks account."
  type        = string
  sensitive   = true
}

variable "prefix" {
  description = "Prefix for Databricks resource names (workspace name, storage config, etc.)"
  type        = string
  default     = "databricks-workspace"
}

variable "resource_prefix" {
  description = "Prefix for naming resources (e.g., S3 buckets, IAM roles, VPC endpoints)."
  type        = string
  default     = "databricks-workspace"
  validation {
    condition     = can(regex("^[a-z0-9-.]{1,40}$", var.resource_prefix))
    error_message = "Invalid resource prefix. Allowed 40 characters containing only a-z, 0-9, -, ."
  }
}

# =============================================================================
# AWS Configuration
# =============================================================================

variable "region" {
  description = "AWS region where Databricks workspace and resources will be deployed."
  type        = string
  validation {
    condition     = contains(["ap-northeast-1", "ap-northeast-2", "ap-south-1", "ap-southeast-1", "ap-southeast-2", "ca-central-1", "eu-central-1", "eu-west-1", "eu-west-2", "eu-west-3", "sa-east-1", "us-east-1", "us-east-2", "us-west-2"], var.region)
    error_message = "Valid values for var.region are standard AWS regions supported by Databricks."
  }
}

variable "tags" {
  description = "Additional tags to apply to all AWS resources"
  type        = map(string)
  default     = {}
}

# =============================================================================
# Network Configuration
# =============================================================================

variable "vpc_id" {
  description = "Existing VPC ID to use. If empty, a new VPC will be created"
  type        = string
  default     = ""
}

variable "vpc_cidr_range" {
  description = "CIDR range for the VPC (only used if creating new VPC). Also used for security group egress rules."
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "List of AWS availability zones for subnet distribution (only used if creating new VPC)"
  type        = list(string)
  default     = []
}

variable "subnet_ids" {
  description = "Existing subnet IDs to use. If empty and creating new VPC, module private subnets will be used"
  type        = list(string)
  default     = []
}

variable "private_subnets_cidr" {
  description = "List of private subnet CIDR blocks (only used if creating new VPC)"
  type        = list(string)
  default     = []
}

variable "public_subnets_cidr" {
  description = "List of public subnet CIDR blocks (only used if creating new VPC)"
  type        = list(string)
  default     = []
}

variable "private_route_table_ids" {
  description = "List of private route table IDs for VPC endpoint (S3 gateway) associations (only when using existing VPC)"
  type        = list(string)
  default     = []
}

# =============================================================================
# Security Group Configuration
# =============================================================================

variable "sg_egress_ports" {
  description = "List of TCP egress ports for workspace security group (e.g., [443, 2443, 5432, 6666, 8443, 8444, 8445])."
  type        = list(number)
  default     = [443, 3306, 2443, 8443, 8444, 8445, 8446, 8447, 8448, 8449, 8450, 8451]
}

variable "additional_egress_ips" {
  description = "List of additional IP CIDR blocks for security group egress rules (e.g., ['198.51.100.5/32', '0.0.0.0/0'])."
  type        = list(string)
  default     = []
}

# =============================================================================
# Unity Catalog Metastore Configuration
# =============================================================================

variable "metastore_id" {
  description = "Existing Unity Catalog metastore ID. If empty, a new metastore will be created"
  type        = string
  default     = ""
}

variable "metastore_name" {
  description = "Name for the Unity Catalog metastore (only used if creating new metastore)"
  type        = string
  default     = ""
}

# =============================================================================
# Private Link Configuration
# =============================================================================

variable "workspace_config" {
  description = "Workspace API PrivateLink Endpoint configuration with multiple properties per region"
  type = map(object({
    primary_endpoint   = string
    secondary_endpoint = optional(string)
    region_type        = optional(string, "commercial")
  }))
  default = {
    "ap-northeast-1" = {
      primary_endpoint = "com.amazonaws.vpce.ap-northeast-1.vpce-svc-02691fd610d24fd64"
    }
    "ap-northeast-2" = {
      primary_endpoint = "com.amazonaws.vpce.ap-northeast-2.vpce-svc-0babb9bde64f34d7e"
    }
    "ap-south-1" = {
      primary_endpoint = "com.amazonaws.vpce.ap-south-1.vpce-svc-0dbfe5d9ee18d6411"
    }
    "ap-southeast-1" = {
      primary_endpoint = "com.amazonaws.vpce.ap-southeast-1.vpce-svc-02535b257fc253ff4"
    }
    "ap-southeast-2" = {
      primary_endpoint = "com.amazonaws.vpce.ap-southeast-2.vpce-svc-0b87155ddd6954974"
    }
    "ap-southeast-3" = {
      primary_endpoint = "com.amazonaws.vpce.ap-southeast-3.vpce-svc-07a698e7e9ccfd04a"
    }
    "ca-central-1" = {
      primary_endpoint = "com.amazonaws.vpce.ca-central-1.vpce-svc-0205f197ec0e28d65"
    }
    "eu-central-1" = {
      primary_endpoint = "com.amazonaws.vpce.eu-central-1.vpce-svc-081f78503812597f7"
    }
    "eu-west-1" = {
      primary_endpoint = "com.amazonaws.vpce.eu-west-1.vpce-svc-0da6ebf1461278016"
    }
    "eu-west-2" = {
      primary_endpoint = "com.amazonaws.vpce.eu-west-2.vpce-svc-01148c7cdc1d1326c"
    }
    "eu-west-3" = {
      primary_endpoint = "com.amazonaws.vpce.eu-west-3.vpce-svc-008b9368d1d011f37"
    }
    "sa-east-1" = {
      primary_endpoint = "com.amazonaws.vpce.sa-east-1.vpce-svc-0bafcea8cdfe11b66"
    }
    "us-east-1" = {
      primary_endpoint = "com.amazonaws.vpce.us-east-1.vpce-svc-09143d1e626de2f04"
    }
    "us-east-2" = {
      primary_endpoint = "com.amazonaws.vpce.us-east-2.vpce-svc-041dc2b4d7796b8d3"
    }
    "us-west-2" = {
      primary_endpoint = "com.amazonaws.vpce.us-west-2.vpce-svc-0129f463fcfbc46c5"
    }
    "us-west-1" = {
      primary_endpoint = "com.amazonaws.vpce.us-west-1.vpce-svc-09bb6ca26208063f2"
    }
    "us-gov-west-1" = {
      primary_endpoint   = "com.amazonaws.vpce.us-gov-west-1.vpce-svc-0f25e28401cbc9418"
      secondary_endpoint = "com.amazonaws.vpce.us-gov-west-1.vpce-svc-08fddf710780b2a54"
      region_type        = "govcloud"
    }
  }
}

variable "scc_relay_config" {
  description = "Secure Cluster Connectivity Relay configuration with multiple properties per region"
  type = map(object({
    primary_endpoint   = string
    secondary_endpoint = optional(string)
    region_type        = optional(string, "commercial")
  }))
  default = {
    "ap-northeast-1" = {
      primary_endpoint = "com.amazonaws.vpce.ap-northeast-1.vpce-svc-02aa633bda3edbec0"
    }
    "ap-northeast-2" = {
      primary_endpoint = "com.amazonaws.vpce.ap-northeast-2.vpce-svc-0dc0e98a5800db5c4"
    }
    "ap-south-1" = {
      primary_endpoint = "com.amazonaws.vpce.ap-south-1.vpce-svc-03fd4d9b61414f3de"
    }
    "ap-southeast-1" = {
      primary_endpoint = "com.amazonaws.vpce.ap-southeast-1.vpce-svc-0557367c6fc1a0c5c"
    }
    "ap-southeast-2" = {
      primary_endpoint = "com.amazonaws.vpce.ap-southeast-2.vpce-svc-0b4a72e8f825495f6"
    }
    "ap-southeast-3" = {
      primary_endpoint = "com.amazonaws.vpce.ap-southeast-3.vpce-svc-025ca447c232c6a1b"
    }
    "ca-central-1" = {
      primary_endpoint = "com.amazonaws.vpce.ca-central-1.vpce-svc-0c4e25bdbcbfbb684"
    }
    "eu-central-1" = {
      primary_endpoint = "com.amazonaws.vpce.eu-central-1.vpce-svc-08e5dfca9572c85c4"
    }
    "eu-west-1" = {
      primary_endpoint = "com.amazonaws.vpce.eu-west-1.vpce-svc-09b4eb2bc775f4e8c"
    }
    "eu-west-2" = {
      primary_endpoint = "com.amazonaws.vpce.eu-west-2.vpce-svc-05279412bf5353a45"
    }
    "eu-west-3" = {
      primary_endpoint = "com.amazonaws.vpce.eu-west-3.vpce-svc-005b039dd0b5f857d"
    }
    "sa-east-1" = {
      primary_endpoint = "com.amazonaws.vpce.sa-east-1.vpce-svc-0e61564963be1b43f"
    }
    "us-east-1" = {
      primary_endpoint = "com.amazonaws.vpce.us-east-1.vpce-svc-00018a8c3ff62ffdf"
    }
    "us-east-2" = {
      primary_endpoint = "com.amazonaws.vpce.us-east-2.vpce-svc-090a8fab0d73e39a6"
    }
    "us-west-2" = {
      primary_endpoint = "com.amazonaws.vpce.us-west-2.vpce-svc-0158114c0c730c3bb"
    }
    "us-west-1" = {
      primary_endpoint = "com.amazonaws.vpce.us-west-1.vpce-svc-04cb91f9372b792fe"
    }
    "us-gov-west-1" = {
      primary_endpoint   = "com.amazonaws.vpce.us-gov-west-1.vpce-svc-05f27abef1a1a3faa"
      secondary_endpoint = "com.amazonaws.vpce.us-gov-west-1.vpce-svc-05c210a2feea23ad7"
      region_type        = "govcloud"
    }
  }
}
