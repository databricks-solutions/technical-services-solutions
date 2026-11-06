// Latest LTS Databricks Runtime.
data "databricks_spark_version" "latest_lts" {
  count             = var.create_cluster ? 1 : 0
  long_term_support = true
  latest            = true

  depends_on = [
    databricks_metastore_assignment.this,
    databricks_mws_permission_assignment.workspace_access,
  ]
}

// UC-compatible single-node cluster in standard (shared) access mode, so workspace users can attach to it.
// No cluster policy: the settings the built-in Personal Compute policy would enforce are set explicitly.
resource "databricks_cluster" "uc_single_node" {
  count                   = var.create_cluster ? 1 : 0
  cluster_name            = "${var.workspace_name}-uc-cluster"
  spark_version           = data.databricks_spark_version.latest_lts[0].id
  node_type_id            = var.node_type_id
  autotermination_minutes = var.cluster_autotermination_minutes
  data_security_mode      = "USER_ISOLATION"
  # Single node: Databricks sets num_workers and the single-node spark_conf itself.
  is_single_node = true
  kind           = "CLASSIC_PREVIEW"

  custom_tags = {
    "ClusterType" = "TerraformDeploymentTesting"
  }

  depends_on = [
    databricks_metastore_assignment.this,
    databricks_mws_permission_assignment.workspace_access,
  ]
}
