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


