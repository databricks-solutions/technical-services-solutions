resource "aws_security_group" "privatelink" {
  name   = "${var.resource_prefix}-privatelink-sg"
  vpc_id = var.vpc_id == "" ? module.vpc[0].vpc_id : var.vpc_id

  ingress {
    description     = "Databricks - PrivateLink Endpoint SG - REST API"
       from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.sg.id] 
  }

  ingress {
      description     = "Databricks - PrivateLink Endpoint SG - Secure Cluster Connectivity"
      from_port       = 6666
      to_port         = 6666
      protocol        = "tcp"
      security_groups = [aws_security_group.sg.id]
  }

  ingress {
    description     = "Databricks - PrivateLink Endpoint SG - Secure Cluster Connectivity - Compliance Security Profile"
    from_port       = 2443
    to_port         = 2443
    protocol        = "tcp"
    security_groups = [aws_security_group.sg.id]
  }

  ingress {
    description     = "Databricks - PrivateLink Endpoint SG - PostgreSQL - Lakebase"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.sg.id]
  }

  ingress {
    description     = "Databricks - Internal calls from the Databricks compute plane to the Databricks control plane API"
    from_port       = 8443
    to_port         = 8443
    protocol        = "tcp"
    security_groups = [aws_security_group.sg.id]
  }

  ingress {
    description     = "Databricks - Unity Catalog logging and lineage data streaming into Databricks"
    from_port       = 8444
    to_port         = 8444
    protocol        = "tcp"
    security_groups = [aws_security_group.sg.id]
  }

  ingress {
    description     = "Databricks - PrivateLink Endpoint SG - Future Extendability"
    from_port       = 8445
    to_port         = 8451
    protocol        = "tcp"
    security_groups = [aws_security_group.sg.id]
  }

}

# Databricks REST endpoint
resource "aws_vpc_endpoint" "backend_rest" {
  vpc_id              = var.vpc_id == "" ? module.vpc[0].vpc_id : var.vpc_id
  service_name        = var.workspace_config[var.region].primary_endpoint
  vpc_endpoint_type   = "Interface"
  security_group_ids  = [aws_security_group.privatelink.id]
  subnet_ids          = length(var.subnet_ids) > 0 ? var.subnet_ids : module.vpc[0].private_subnets
  private_dns_enabled = true
}

# Databricks SCC endpoint
resource "aws_vpc_endpoint" "backend_relay" {
  vpc_id              = var.vpc_id == "" ? module.vpc[0].vpc_id : var.vpc_id
  service_name        = var.scc_relay_config[var.region].primary_endpoint
  vpc_endpoint_type   = "Interface"
  security_group_ids  = [aws_security_group.privatelink.id]
  subnet_ids          = length(var.subnet_ids) > 0 ? var.subnet_ids : module.vpc[0].private_subnets
  private_dns_enabled = true
}
