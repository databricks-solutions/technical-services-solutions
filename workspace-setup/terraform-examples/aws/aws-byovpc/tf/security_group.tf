locals {
  # SG used for workspace when creating new VPC (either dedicated or default)
  workspace_sg_id = var.vpc_id == "" ? (var.use_dedicated_security_group ? aws_security_group.dedicated[0].id : module.vpc[0].default_security_group_id) : null
  # When existing VPC and creating a new SG instead of using default
  create_sg_for_existing_vpc = var.vpc_id != "" && length(var.security_group_ids) == 0 && var.create_workspace_sg_for_existing_vpc
}

resource "aws_security_group" "dedicated" {
  count       = var.vpc_id == "" && var.use_dedicated_security_group ? 1 : 0
  name        = "${var.resource_prefix}-workspace-sg"
  description = "Security group for Databricks workspace (dedicated, default VPC SG unchanged)"
  vpc_id      = module.vpc[0].vpc_id
  tags        = merge(var.tags, { Name = "${var.resource_prefix}-workspace-sg" })
  depends_on  = [module.vpc]
}

resource "aws_vpc_security_group_egress_rule" "default_sg_egress_ports" {
  for_each          = var.vpc_id == "" ? { for port in var.sg_egress_ports : tostring(port) => port } : {}
  security_group_id = local.workspace_sg_id
  from_port         = each.value
  to_port           = each.value
  ip_protocol       = "tcp"
  cidr_ipv4         = "0.0.0.0/0"
  description       = "Allow outbound TCP traffic on port ${each.value}"
  depends_on        = [module.vpc]
}

resource "aws_vpc_security_group_egress_rule" "default_sg_internal_tcp_egress" {
  count                        = var.vpc_id == "" ? 1 : 0
  security_group_id            = local.workspace_sg_id
  referenced_security_group_id = local.workspace_sg_id
  ip_protocol                  = "tcp"
  from_port                    = 0
  to_port                      = 65535
  description                  = "Allow all internal TCP egress traffic"
  depends_on                   = [module.vpc]
}

resource "aws_vpc_security_group_egress_rule" "default_sg_internal_udp_egress" {
  count                        = var.vpc_id == "" ? 1 : 0
  security_group_id            = local.workspace_sg_id
  referenced_security_group_id = local.workspace_sg_id
  ip_protocol                  = "udp"
  from_port                    = 0
  to_port                      = 65535
  description                  = "Allow all internal UDP egress traffic"
  depends_on                   = [module.vpc]
}

resource "aws_vpc_security_group_ingress_rule" "default_sg_self_ingress" {
  count                        = var.vpc_id == "" ? 1 : 0
  security_group_id            = local.workspace_sg_id
  referenced_security_group_id = local.workspace_sg_id
  ip_protocol                  = "-1"
  description                  = "Allow all traffic from self"
  depends_on                   = [module.vpc]
}

# Optional: new security group for existing VPC (leaves default SG unchanged)
resource "aws_security_group" "existing_vpc_workspace_sg" {
  count       = local.create_sg_for_existing_vpc ? 1 : 0
  name        = "${var.resource_prefix}-workspace-sg"
  description = "Security group for Databricks workspace (existing VPC, default SG unchanged)"
  vpc_id      = var.vpc_id
  tags        = merge(var.tags, { Name = "${var.resource_prefix}-workspace-sg" })
}

resource "aws_vpc_security_group_egress_rule" "existing_vpc_sg_egress_ports" {
  for_each          = local.create_sg_for_existing_vpc ? { for port in var.sg_egress_ports : tostring(port) => port } : {}
  security_group_id = aws_security_group.existing_vpc_workspace_sg[0].id
  from_port         = each.value
  to_port           = each.value
  ip_protocol       = "tcp"
  cidr_ipv4         = "0.0.0.0/0"
  description       = "Allow outbound TCP traffic on port ${each.value}"
}

resource "aws_vpc_security_group_egress_rule" "existing_vpc_sg_internal_tcp_egress" {
  count                        = local.create_sg_for_existing_vpc ? 1 : 0
  security_group_id            = aws_security_group.existing_vpc_workspace_sg[0].id
  referenced_security_group_id = aws_security_group.existing_vpc_workspace_sg[0].id
  ip_protocol                  = "tcp"
  from_port                    = 0
  to_port                      = 65535
  description                  = "Allow all internal TCP egress traffic"
}

resource "aws_vpc_security_group_egress_rule" "existing_vpc_sg_internal_udp_egress" {
  count                        = local.create_sg_for_existing_vpc ? 1 : 0
  security_group_id            = aws_security_group.existing_vpc_workspace_sg[0].id
  referenced_security_group_id = aws_security_group.existing_vpc_workspace_sg[0].id
  ip_protocol                  = "udp"
  from_port                    = 0
  to_port                      = 65535
  description                  = "Allow all internal UDP egress traffic"
}

resource "aws_vpc_security_group_ingress_rule" "existing_vpc_sg_self_ingress" {
  count                        = local.create_sg_for_existing_vpc ? 1 : 0
  security_group_id            = aws_security_group.existing_vpc_workspace_sg[0].id
  referenced_security_group_id = aws_security_group.existing_vpc_workspace_sg[0].id
  ip_protocol                  = "-1"
  description                  = "Allow all traffic from self"
}
