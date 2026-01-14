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


resource "aws_security_group_rule" "default_sg_self_ingress" {
  count             = var.vpc_id == "" ? 1 : 0
  type              = "ingress"
  from_port         = 0
  to_port           = 65535
  protocol          = "-1"
  self              = true
  security_group_id = module.vpc[0].default_security_group_id
  description       = "Allow all inbound traffic from self"
}

resource "aws_security_group_rule" "default_sg_self_egress" {
  count             = var.vpc_id == "" ? 1 : 0
  type              = "egress"
  from_port         = 0
  to_port           = 65535
  protocol          = "-1"
  self              = true
  security_group_id = module.vpc[0].default_security_group_id
  description       = "Allow all outbound traffic to self"
}