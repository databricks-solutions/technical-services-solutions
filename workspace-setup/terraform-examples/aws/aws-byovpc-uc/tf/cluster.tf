// Latest LTS Databricks Runtime.
data "databricks_spark_version" "latest_lts" {
  provider          = databricks.workspace
  long_term_support = true
  latest            = true

  depends_on = [
    databricks_metastore_assignment.this,
  ]
}

// UC-compatible single-node cluster (no cluster policy).
resource "databricks_cluster" "uc_single_node" {
  provider                = databricks.workspace
  count                   = var.new_cluster ? 1 : 0
  cluster_name            = "${var.prefix}-uc-cluster"
  spark_version           = data.databricks_spark_version.latest_lts.id
  node_type_id            = "r5d.large"
  autotermination_minutes = var.cluster_autotermination_minutes
  data_security_mode      = "SINGLE_USER"
  num_workers             = 0


  custom_tags = {
    "ResourceClass" = "SingleNode"
    "ClusterType"   = "TerraformDeploymentTesting"
  }

  depends_on = [
    databricks_metastore_assignment.this,
  ]
}
