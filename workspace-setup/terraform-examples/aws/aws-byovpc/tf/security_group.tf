resource "aws_vpc_security_group_egress_rule" "default_sg_egress_ports" {
  for_each          = var.vpc_id == "" ? { for port in var.sg_egress_ports : tostring(port) => port } : {}
  security_group_id = module.vpc[0].default_security_group_id
  from_port         = each.value
  to_port           = each.value
  ip_protocol       = "tcp"
  cidr_ipv4         = "0.0.0.0/0"
  description       = "Allow outbound TCP traffic on port ${each.value}"
  depends_on        = [module.vpc]
}

resource "aws_vpc_security_group_egress_rule" "default_sg_internal_tcp_egress" {
  count                        = var.vpc_id == "" ? 1 : 0
  security_group_id            = module.vpc[0].default_security_group_id
  referenced_security_group_id = module.vpc[0].default_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 0
  to_port                      = 65535
  description                  = "Allow all internal TCP egress traffic"
  depends_on                   = [module.vpc]
}

resource "aws_vpc_security_group_egress_rule" "default_sg_internal_udp_egress" {
  count                        = var.vpc_id == "" ? 1 : 0
  security_group_id            = module.vpc[0].default_security_group_id
  referenced_security_group_id = module.vpc[0].default_security_group_id
  ip_protocol                  = "udp"
  from_port                    = 0
  to_port                      = 65535
  description                  = "Allow all internal UDP egress traffic"
  depends_on                   = [module.vpc]
}

resource "aws_vpc_security_group_ingress_rule" "default_sg_self_ingress" {
  count                        = var.vpc_id == "" ? 1 : 0
  security_group_id            = module.vpc[0].default_security_group_id
  referenced_security_group_id = module.vpc[0].default_security_group_id
  ip_protocol                  = "-1"
  description                  = "Allow all traffic from self"
  depends_on                   = [module.vpc]
}
