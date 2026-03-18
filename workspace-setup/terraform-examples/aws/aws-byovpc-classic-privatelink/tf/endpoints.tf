module "vpc_endpoints" {
  source  = "terraform-aws-modules/vpc/aws//modules/vpc-endpoints"
  version = "3.11.0"

  vpc_id             = var.vpc_id == "" ? module.vpc[0].vpc_id : var.vpc_id
  security_group_ids = [aws_security_group.privatelink.id]

  endpoints = {
    s3 = {
      service         = "s3"
      service_type    = "Gateway"
      route_table_ids = length(var.private_route_table_ids) > 0 ? var.private_route_table_ids : module.vpc[0].private_route_table_ids
    },

    sts = {
      service             = "sts"
      private_dns_enabled  = true
      subnet_ids          = length(var.subnet_ids) > 0 ? var.subnet_ids : module.vpc[0].private_subnets
    },
    kinesis-streams = {
      service             = "kinesis-streams"
      private_dns_enabled  = true
      subnet_ids          = length(var.subnet_ids) > 0 ? var.subnet_ids : module.vpc[0].private_subnets
    }
  }
}

