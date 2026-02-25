# Input validation to ensure proper configuration

locals {
  # Validate VPC configuration
  vpc_validation = (
    var.create_new_vpc ?
    (var.vpc_cidr != "" && length(var.private_subnet_cidrs) >= 2) :
    (var.existing_vpc_id != "" && length(var.existing_subnet_ids) >= 2)
  )

  # Validate CMK configuration
  cmk_validation = (
    var.create_new_cmk ?
    true :
    var.existing_cmk_arn != ""
  )
}

# Validation checks
resource "null_resource" "validation" {
  lifecycle {
    precondition {
      condition     = local.vpc_validation
      error_message = <<-EOT
        VPC Configuration Error:
        - If create_new_vpc = true, you must provide vpc_cidr and at least 2 private_subnet_cidrs
        - If create_new_vpc = false, you must provide existing_vpc_id and at least 2 existing_subnet_ids
      EOT
    }

    precondition {
      condition     = local.cmk_validation
      error_message = <<-EOT
        CMK Configuration Error:
        - If create_new_cmk = false, you must provide existing_cmk_arn
      EOT
    }

    precondition {
      condition     = !var.create_new_vpc ? length(var.existing_subnet_ids) >= 2 : true
      error_message = "When using existing VPC, you must provide at least 2 subnet IDs in different Availability Zones."
    }
  }
}

