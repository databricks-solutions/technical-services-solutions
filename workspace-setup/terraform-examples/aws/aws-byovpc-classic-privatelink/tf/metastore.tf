data "databricks_metastore" "existing" {
  count        = var.metastore_id != "" ? 1 : 0
  provider     = databricks.mws
  metastore_id = var.metastore_id
}

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
  depends_on   = [data.databricks_metastore.existing, databricks_mws_workspaces.this, time_sleep.wait_2_minutes]

  lifecycle {
    precondition {
      condition     = var.metastore_id == "" ? true : data.databricks_metastore.existing[0].region == var.region
      error_message = "Workspace region should match metastore region."
    }
  }
}

# Unity Catalog only: classic compute here cannot reach the legacy Hive metastore (no egress on 3306), so disable
# direct Hive metastore access. Matches the Databricks SRA template. Permanent after 30 days.
# Set the default catalog first (when a catalog is created): with legacy access disabled, the default cannot stay hive_metastore.
resource "databricks_default_namespace_setting" "this" {
  count    = var.new_catalog ? 1 : 0
  provider = databricks.workspace
  namespace {
    value = databricks_catalog.uc_quickstart[0].name
  }
}

resource "databricks_disable_legacy_access_setting" "this" {
  provider = databricks.workspace
  disable_legacy_access {
    value = true
  }
  depends_on = [databricks_metastore_assignment.this, databricks_default_namespace_setting.this]
}
