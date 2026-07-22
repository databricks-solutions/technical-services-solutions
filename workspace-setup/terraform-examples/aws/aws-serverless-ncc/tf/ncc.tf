################################################################################
# 3. Network Connectivity Configuration (NCC)
################################################################################

# The NCC routes serverless egress traffic privately. Each workspace can be
# bound to one NCC. Default name is "ncc-<prefix>" if ncc_name isn't set.
resource "databricks_mws_network_connectivity_config" "ncc" {
  provider = databricks.account
  name     = coalesce(var.ncc_name, "ncc-${var.prefix}")
  region   = var.region
}

# Sits between the NCC and its binding so that on destroy TF pauses for 30s
# after the binding is removed before deleting the NCC. Without this pause,
# the NCC delete can race the Databricks control plane's unbind propagation
# and fail with "unable to be deleted because it is attached to one or more
# workspaces" — requiring a manual `terraform destroy` rerun.
#
# Create order:  ncc → delay_before_ncc_delete → ncc_binding
# Destroy order: ncc_binding → delay_before_ncc_delete (30s) → ncc
resource "time_sleep" "delay_before_ncc_delete" {
  depends_on       = [databricks_mws_network_connectivity_config.ncc]
  destroy_duration = "30s"
}

# Bind the NCC to the workspace. Must succeed before metastore assignment +
# admin assignment are attempted.
resource "databricks_mws_ncc_binding" "ncc_binding" {
  provider = databricks.account

  network_connectivity_config_id = databricks_mws_network_connectivity_config.ncc.network_connectivity_config_id
  workspace_id                   = local.workspace_id

  depends_on = [time_sleep.delay_before_ncc_delete]

  lifecycle {
    precondition {
      condition     = local.workspace_id != null
      error_message = "workspace_id could not be resolved. Set create_new_workspace=true, or provide existing_workspace_id, or provide existing_workspace_name that matches an existing workspace in the Databricks account."
    }
  }
}

# Optional non-S3 NCC private endpoint rule (e.g. RDS, Kinesis, custom VPC
# endpoint service). Set create_private_endpoint_rule=true and supply
# endpoint_service + domain_names to use this. The S3-specific endpoint
# rule is handled in s3_endpoint.tf.
resource "databricks_mws_ncc_private_endpoint_rule" "aws_private_endpoint" {
  count    = var.create_private_endpoint_rule ? 1 : 0
  provider = databricks.account

  network_connectivity_config_id = databricks_mws_network_connectivity_config.ncc.network_connectivity_config_id
  endpoint_service               = var.endpoint_service
  domain_names                   = var.domain_names

  lifecycle {
    precondition {
      condition     = var.endpoint_service != null && length(var.domain_names) > 0
      error_message = "When create_private_endpoint_rule=true, you must set endpoint_service and at least one value in domain_names."
    }
  }
}
