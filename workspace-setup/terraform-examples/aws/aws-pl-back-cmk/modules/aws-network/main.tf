data "aws_availability_zones" "azs" { state = "available" }

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "${var.project}-vpc" }
}

resource "aws_internet_gateway" "igw" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${var.project}-igw" }
}

resource "aws_subnet" "private" {
  count                   = 2
  vpc_id                  = aws_vpc.this.id
  cidr_block              = var.private_subnet_cidrs[count.index]
  availability_zone       = data.aws_availability_zones.azs.names[count.index]
  map_public_ip_on_launch = false
  tags                    = { Name = "${var.project}-private-${count.index}" }
}

# Route tables for private subnets (allow local only; egress via endpoints/NAT if added)
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${var.project}-rt-private" }
}

resource "aws_route_table_association" "a" {
  count          = length(aws_subnet.private)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# Security group for workspace nodes <-> endpoints
resource "aws_security_group" "workspace" {
  name        = "${var.project}-workspace-sg"
  description = "Databricks workspace SG"
  vpc_id      = aws_vpc.this.id

  # Egress all (fine-tune if needed)
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-workspace-sg" }
}

# SG for VPC interface endpoints
resource "aws_security_group" "vpce" {
  name        = "${var.project}-vpce-sg"
  description = "Security group for VPC endpoints (PL back-end)"
  vpc_id      = aws_vpc.this.id

  ingress {
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.workspace.id]
  }

  # SCC relay port 6666
  ingress {
    from_port       = 6666
    to_port         = 6666
    protocol        = "tcp"
    security_groups = [aws_security_group.workspace.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-vpce-sg" }
}

# VPC Interface Endpoint - Databricks Workspace (REST APIs) for back-end
resource "aws_vpc_endpoint" "workspace" {
  vpc_id              = aws_vpc.this.id
  service_name        = var.pl_service_names.workspace
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private[0].id]
  security_group_ids  = [aws_security_group.vpce.id]
  private_dns_enabled = true
  tags                = { Name = "${var.project}-vpce-workspace" }
}

# VPC Interface Endpoint - Secure Cluster Connectivity Relay
resource "aws_vpc_endpoint" "scc" {
  vpc_id              = aws_vpc.this.id
  service_name        = var.pl_service_names.scc
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private[1].id]
  security_group_ids  = [aws_security_group.vpce.id]
  private_dns_enabled = true
  tags                = { Name = "${var.project}-vpce-scc" }
}

# Extra endpoints recommended by Databricks
resource "aws_vpc_endpoint" "sts" {
  count               = var.enable_extra_endpoints ? 1 : 0
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.region}.sts"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [for s in aws_subnet.private : s.id]
  security_group_ids  = [aws_security_group.vpce.id]
  private_dns_enabled = true
  tags                = { Name = "${var.project}-vpce-sts" }
}

resource "aws_vpc_endpoint" "kinesis" {
  count               = var.enable_extra_endpoints ? 1 : 0
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.region}.kinesis-streams"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [for s in aws_subnet.private : s.id]
  security_group_ids  = [aws_security_group.vpce.id]
  private_dns_enabled = true
  tags                = { Name = "${var.project}-vpce-kinesis" }
}

resource "aws_vpc_endpoint" "s3" {
  count             = var.enable_extra_endpoints ? 1 : 0
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
  tags              = { Name = "${var.project}-vpce-s3" }
}

output "vpc_id" { value = aws_vpc.this.id }
output "subnet_ids" { value = [for s in aws_subnet.private : s.id] }
output "workspace_sg_id" { value = aws_security_group.workspace.id }
output "vpce_workspace_id" { value = aws_vpc_endpoint.workspace.id }
output "vpce_scc_id" { value = aws_vpc_endpoint.scc.id }
