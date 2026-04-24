// Latest LTS Databricks Runtime.
data "databricks_spark_version" "latest_lts" {
  long_term_support = true
  latest            = true
}

// Built-in Personal Compute policy enforces SINGLE_USER access mode, the
// single-node cluster profile, and other UC-compatible defaults.
data "databricks_cluster_policy" "personal" {
  name = "Personal Compute"
}

// UC-compatible single-node cluster governed by the Personal Compute policy.
resource "databricks_cluster" "uc_single_node" {
  cluster_name            = "${var.workspace_name}-uc-cluster"
  policy_id               = data.databricks_cluster_policy.personal.id
  spark_version           = data.databricks_spark_version.latest_lts.id
  node_type_id            = var.node_type_id
  autotermination_minutes = var.autotermination_minutes

  custom_tags = {
    "ClusterType" = "TerraformDeploymentTesting"
  }

  depends_on = [
    databricks_metastore_assignment.this,
    databricks_mws_permission_assignment.workspace_access,
  ]
}
