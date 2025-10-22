module "vpc" {
  count   = var.vpc_id == "" ? 1 : 0
  source  = "terraform-aws-modules/vpc/aws"
  version = "5.1.1"

  name = "${var.resource_prefix}-classic-compute-plane-vpc"
  cidr = var.vpc_cidr_range
  azs  = var.availability_zones

  enable_dns_hostnames   = true
  enable_nat_gateway     = true
  single_nat_gateway     = true
  one_nat_gateway_per_az = false
  create_igw             = true

  private_subnet_names = [for az in var.availability_zones : format("%s-private-%s", var.resource_prefix, az)]
  private_subnets      = var.private_subnets_cidr

  public_subnet_names = [for az in var.availability_zones : format("%s-public-%s", var.resource_prefix, az)]
  public_subnets      = var.public_subnets_cidr

  # Enable default security group management
  manage_default_security_group  = true
  default_security_group_name    = "${var.resource_prefix}-default-sg"
  default_security_group_ingress = []
  default_security_group_egress  = []

  tags = merge(
    var.tags,
    {
      Project = var.resource_prefix
    }
  )
}

