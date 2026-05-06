# Data source for S3 Prefix List
data "aws_prefix_list" "s3" {
  name = "com.amazonaws.${var.region}.s3"
}


module "vpc" {
  count   = var.network_configuration != "custom" ? 1 : 0
  source  = "terraform-aws-modules/vpc/aws"
  version = "5.1.1"

  name = "${var.resource_prefix}-classic-compute-plane-vpc"
  cidr = var.vpc_cidr_range
  azs  = var.availability_zones

  enable_dns_hostnames   = true
  enable_nat_gateway     = var.network_configuration == "standard"
  single_nat_gateway     = true
  one_nat_gateway_per_az = false
  create_igw             = var.network_configuration == "standard"

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

# Dedicated subnet for AWS service endpoints (STS, Kinesis) in fully_private mode only
resource "aws_subnet" "endpoint" {
  count             = var.network_configuration == "fully_private" ? 1 : 0
  vpc_id            = module.vpc[0].vpc_id
  cidr_block        = var.endpoint_subnet_cidr
  availability_zone = var.availability_zones[0]
  tags = merge(
    var.tags,
    {
      Name = "${var.resource_prefix}-endpoints-subnet"
    }
  )
}

# Route table for endpoint subnet: local VPC only (no NAT/IGW)
resource "aws_route_table" "endpoint" {
  count  = var.network_configuration == "fully_private" ? 1 : 0
  vpc_id = module.vpc[0].vpc_id
  tags = merge(
    var.tags,
    {
      Name = "${var.resource_prefix}-endpoints-rt"
    }
  )
}

resource "aws_route_table_association" "endpoint" {
  count          = var.network_configuration == "fully_private" ? 1 : 0
  subnet_id      = aws_subnet.endpoint[0].id
  route_table_id = aws_route_table.endpoint[0].id
}

resource "aws_security_group" "sg" {
  count    = var.network_configuration != "custom" ? 1 : 0
  name     = "${var.resource_prefix}-workspace-sg"
  vpc_id   = module.vpc[0].vpc_id

  dynamic "ingress" {
    for_each = ["tcp", "udp"]
    content {
      description = "Databricks - Workspace SG - Internode Communication"
      from_port   = 0
      to_port     = 65535
      protocol    = ingress.value
      self        = true
    }
  }

  dynamic "egress" {
    for_each = ["tcp", "udp"]
    content {
      description = "Databricks - Workspace SG - Internode Communication"
      from_port   = 0
      to_port     = 65535
      protocol    = egress.value
      self        = true
    }
  }

  ### Example of restrictive egress policies
  dynamic "egress" {
    for_each = var.sg_egress_ports
    content {
      description = "Databricks - Workspace SG - REST (443), Secure Cluster Connectivity (2443/6666), Lakebase PostgreSQL (5432), Compute Plane to Control Plane Internal Calls (8443), Unity Catalog Logging and Lineage Data Streaming (8444), Future Extendability (8445-8451)"
      from_port   = egress.value
      to_port     = egress.value
      protocol    = "tcp"
      cidr_blocks = [var.vpc_cidr_range]
    }
  }

  dynamic "egress" {
   for_each = var.additional_egress_ips  # This should be a list of IP CIDR strings, e.g., ["198.51.100.5/32", "203.0.113.0/24"]
    content {
      description = "Databricks - Egress to specific external IP"
      from_port   = 0         # Or the specific port required
      to_port     = 65535     # Or the specific port required
      protocol    = "tcp"     # Or "udp" or other, as needed
      cidr_blocks = [egress.value]
    }
  }

  dynamic "egress" {
    for_each = var.network_configuration != "custom" ? [1] : []
    content {
      description     = "S3 Gateway Endpoint - SG"
      from_port       = 443
      to_port         = 443
      protocol        = "tcp"
      prefix_list_ids = [data.aws_prefix_list.s3.id]
    }
  }

###Example of permissive egress

/*  dynamic "egress" {
    for_each = var.sg_egress_ports
    content {
      description = "Databricks - Workspace SG - REST (443), Secure Cluster Connectivity (2443/6666), Lakebase PostgreSQL (5432), Compute Plane to Control Plane Internal Calls (8443), Unity Catalog Logging and Lineage Data Streaming (8444), Future Extendability (8445-8451)"
      from_port   = egress.value
      to_port     = egress.value
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
    }
  }*/

}
