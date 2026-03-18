# =============================================================================
# Endpoint ID locals (template-created vs user-provided)
# =============================================================================
locals {
  backend_rest_aws_vpce_id  = try(aws_vpc_endpoint.backend_rest[0].id, var.backend_rest_aws_vpce_id)
  backend_relay_aws_vpce_id = try(aws_vpc_endpoint.backend_relay[0].id, var.backend_relay_aws_vpce_id)
}
