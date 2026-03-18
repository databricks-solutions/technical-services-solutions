# S3 gateway + STS and Kinesis interface endpoints. Not created in custom mode.
module "vpc_endpoints" {
  count   = var.network_configuration != "custom" ? 1 : 0
  source  = "terraform-aws-modules/vpc/aws//modules/vpc-endpoints"
  version = "3.11.0"

  vpc_id = module.vpc[0].vpc_id

  # Standard: STS/Kinesis use workspace SG in workspace subnets. Fully_private: use aws_endpoints SG in dedicated endpoint subnet.
  security_group_ids = var.network_configuration == "fully_private" ? [aws_security_group.aws_endpoints[0].id] : [aws_security_group.sg[0].id]

  endpoints = {
    s3 = {
      service         = "s3"
      service_type    = "Gateway"
      route_table_ids = module.vpc[0].private_route_table_ids
    }

    sts = {
      service            = "sts"
      private_dns_enabled = true
      subnet_ids         = var.network_configuration == "fully_private" ? [aws_subnet.endpoint[0].id] : module.vpc[0].private_subnets
    }

    kinesis-streams = {
      service            = "kinesis-streams"
      private_dns_enabled = true
      subnet_ids         = var.network_configuration == "fully_private" ? [aws_subnet.endpoint[0].id] : module.vpc[0].private_subnets
    }
  }
}
