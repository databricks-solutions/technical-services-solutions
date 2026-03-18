resource "databricks_metastore" "metastore" {
  count         = var.metastore_id == "" ? 1 : 0
  provider      = databricks.mws
  name          = var.metastore_name
  region        = var.region
  force_destroy = true # This is required to destroy the metastore if it has catalogs and workspaces attached to it
}

resource "databricks_metastore_assignment" "this" {
  metastore_id = var.metastore_id == "" ? databricks_metastore.metastore[0].id : var.metastore_id
  provider     = databricks.mws
  workspace_id = databricks_mws_workspaces.this.workspace_id
  depends_on   = [databricks_mws_workspaces.this, time_sleep.wait_2_minutes]
}
