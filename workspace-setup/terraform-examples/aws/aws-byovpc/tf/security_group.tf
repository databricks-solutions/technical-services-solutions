resource "aws_security_group" "databricks" {
  count = var.vpc_id == "" ? 1 : 0
  name        = var.new_security_group_name != "" ? var.new_security_group_name : "${var.resource_prefix}-databricks-sg"
  description = "Dedicated security group for Databricks workspace"
  vpc_id      = module.vpc[0].vpc_id

  dynamic "egress" {
    for_each = var.sg_egress_ports
    content {
      from_port   = egress.value
      to_port     = egress.value
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
      description = "Allow outbound TCP traffic on port ${egress.value}"
    }
  }

  egress {
    from_port   = 0
    to_port     = 65535
    protocol    = "tcp"
    self        = true
    description = "Allow all internal TCP egress traffic"
  }

  egress {
    from_port   = 0
    to_port     = 65535
    protocol    = "udp"
    self        = true
    description = "Allow all internal UDP egress traffic"
  }

  ingress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    self        = true
    description = "Allow all traffic from self"
  }

  tags = merge(
    var.tags,
    {
      Project = var.resource_prefix
    }
  )
}