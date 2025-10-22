resource "aws_security_group_rule" "default_sg_egress_ports" {
  for_each          = var.vpc_id == "" ? { for port in var.sg_egress_ports : tostring(port) => port } : {}
  type              = "egress"
  from_port         = each.value
  to_port           = each.value
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = module.vpc[0].default_security_group_id
  description       = "Allow outbound TCP traffic on port ${each.value}"
  depends_on        = [module.vpc]
}

# Add egress rule for SQL Server connectivity (port 1433)
resource "aws_security_group_rule" "default_sg_egress_sql_server" {
  count             = var.vpc_id == "" ? 1 : 0
  type              = "egress"
  from_port         = 1433
  to_port           = 1433
  protocol          = "tcp"
  cidr_blocks       = [var.vpc_cidr_range]
  security_group_id = module.vpc[0].default_security_group_id
  description       = "Allow outbound TCP traffic to SQL Server on port 1433"
  depends_on        = [module.vpc]
}

