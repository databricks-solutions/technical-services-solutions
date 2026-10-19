locals {
  # Option 3: existing VPC that only has the Databricks private subnets.
  create_network_in_existing_vpc = var.vpc_id != "" && var.create_network_in_existing_vpc

  vpc_id             = var.vpc_id == "" ? module.vpc[0].vpc_id : var.vpc_id
  security_group_ids = var.vpc_id != "" && length(var.security_group_ids) > 0 ? var.security_group_ids : aws_security_group.databricks[*].id

  # AZs that get a NAT gateway (and a private route table) in Option 3.
  nat_azs = local.create_network_in_existing_vpc ? (var.nat_gateway_mode == "single" ? [var.availability_zones[0]] : var.availability_zones) : []

  # Shared by module.vpc_endpoints for Option 1 and Option 3.
  private_route_table_ids = var.vpc_id == "" ? module.vpc[0].private_route_table_ids : [for rt in aws_route_table.private : rt.id]
  endpoint_subnet_ids     = var.vpc_id == "" ? module.vpc[0].intra_subnets : var.subnet_ids
}

module "vpc" {
  count   = var.vpc_id == "" ? 1 : 0
  source  = "terraform-aws-modules/vpc/aws"
  version = "5.1.1"

  name = "${var.resource_prefix}-classic-compute-plane-vpc"
  cidr = var.vpc_cidr_range
  azs  = var.availability_zones

  enable_dns_hostnames   = true
  enable_dns_support     = true
  enable_nat_gateway     = true
  single_nat_gateway     = var.nat_gateway_mode == "single"
  one_nat_gateway_per_az = var.nat_gateway_mode == "per_az"
  create_igw             = true

  private_subnet_names = [for az in var.availability_zones : format("%s-private-%s", var.resource_prefix, az)]
  private_subnets      = var.private_subnets_cidr

  public_subnet_names = [for az in var.availability_zones : format("%s-public-%s", var.resource_prefix, az)]
  public_subnets      = var.public_subnets_cidr

  intra_subnet_names = [for az in var.availability_zones : format("%s-intra-%s", var.resource_prefix, az)]
  intra_subnets      = var.intra_subnet_cidr

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

module "vpc_endpoints" {
  count   = var.vpc_id == "" || local.create_network_in_existing_vpc ? 1 : 0
  source  = "terraform-aws-modules/vpc/aws//modules/vpc-endpoints"
  version = "5.1.1"

  vpc_id = local.vpc_id

  security_group_ids = local.security_group_ids

  endpoints = {
    s3 = {
      service         = "s3"
      service_type    = "Gateway"
      route_table_ids = local.private_route_table_ids
      tags = {
        Name    = "${var.resource_prefix}-s3-vpc-endpoint"
        Project = var.resource_prefix
      }
    }
    sts = {
      service             = "sts"
      private_dns_enabled = true
      subnet_ids          = local.endpoint_subnet_ids
      tags = {
        Name    = "${var.resource_prefix}-sts-vpc-endpoint"
        Project = var.resource_prefix
      }
    }
    kinesis-streams = {
      service             = "kinesis-streams"
      private_dns_enabled = true
      subnet_ids          = local.endpoint_subnet_ids
      tags = {
        Name    = "${var.resource_prefix}-kinesis-vpc-endpoint"
        Project = var.resource_prefix
      }
    }
  }
}

# =============================================================================
# Option 3: add IGW, public subnets, NAT and private routing to an existing VPC
# (only when create_network_in_existing_vpc = true with vpc_id + subnet_ids)
# =============================================================================

data "aws_subnet" "databricks" {
  for_each = local.create_network_in_existing_vpc ? toset(var.subnet_ids) : toset([])
  id       = each.value
}

resource "aws_internet_gateway" "this" {
  count  = local.create_network_in_existing_vpc ? 1 : 0
  vpc_id = var.vpc_id

  tags = merge(
    var.tags,
    {
      Name    = "${var.resource_prefix}-igw"
      Project = var.resource_prefix
    }
  )
}

resource "aws_subnet" "public" {
  for_each          = local.create_network_in_existing_vpc ? zipmap(var.availability_zones, var.public_subnets_cidr) : {}
  vpc_id            = var.vpc_id
  availability_zone = each.key
  cidr_block        = each.value

  tags = merge(
    var.tags,
    {
      Name    = format("%s-public-%s", var.resource_prefix, each.key)
      Project = var.resource_prefix
    }
  )
}

resource "aws_route_table" "public" {
  count  = local.create_network_in_existing_vpc ? 1 : 0
  vpc_id = var.vpc_id

  tags = merge(
    var.tags,
    {
      Name    = "${var.resource_prefix}-public"
      Project = var.resource_prefix
    }
  )
}

resource "aws_route" "public_internet_gateway" {
  count                  = local.create_network_in_existing_vpc ? 1 : 0
  route_table_id         = aws_route_table.public[0].id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this[0].id
}

resource "aws_route_table_association" "public" {
  for_each       = aws_subnet.public
  subnet_id      = each.value.id
  route_table_id = aws_route_table.public[0].id
}

resource "aws_eip" "nat" {
  for_each = toset(local.nat_azs)
  domain   = "vpc"

  tags = merge(
    var.tags,
    {
      Name    = format("%s-nat-%s", var.resource_prefix, each.key)
      Project = var.resource_prefix
    }
  )

  depends_on = [aws_internet_gateway.this]
}

resource "aws_nat_gateway" "this" {
  for_each      = toset(local.nat_azs)
  allocation_id = aws_eip.nat[each.key].id
  subnet_id     = aws_subnet.public[each.key].id

  tags = merge(
    var.tags,
    {
      Name    = format("%s-nat-%s", var.resource_prefix, each.key)
      Project = var.resource_prefix
    }
  )

  depends_on = [aws_internet_gateway.this]
}

resource "aws_route_table" "private" {
  for_each = toset(local.nat_azs)
  vpc_id   = var.vpc_id

  tags = merge(
    var.tags,
    {
      Name    = var.nat_gateway_mode == "single" ? "${var.resource_prefix}-private" : format("%s-private-%s", var.resource_prefix, each.key)
      Project = var.resource_prefix
    }
  )
}

resource "aws_route" "private_nat_gateway" {
  for_each               = aws_route_table.private
  route_table_id         = each.value.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this[each.key].id
}

# Assumes the existing subnets are only on the VPC main route table; an explicit
# association to another route table makes this fail with Resource.AlreadyAssociated.
resource "aws_route_table_association" "private" {
  for_each       = data.aws_subnet.databricks
  subnet_id      = each.value.id
  route_table_id = aws_route_table.private[var.nat_gateway_mode == "single" ? local.nat_azs[0] : each.value.availability_zone].id

  lifecycle {
    precondition {
      condition     = each.value.vpc_id == var.vpc_id
      error_message = "Subnet ${each.key} is not in vpc_id ${var.vpc_id}."
    }
    precondition {
      condition     = var.nat_gateway_mode == "single" || contains(var.availability_zones, each.value.availability_zone)
      error_message = "With nat_gateway_mode = \"per_az\", availability_zones must include the AZ of subnet ${each.key} (${each.value.availability_zone})."
    }
  }
}
