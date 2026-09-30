resource "databricks_mws_workspaces" "this" {
  provider       = databricks.mws
  account_id     = var.databricks_account_id
  aws_region     = var.region
  workspace_name = var.prefix
  compute_mode   = "SERVERLESS"
}

resource "time_sleep" "wait_2_minutes" {
  depends_on      = [databricks_mws_workspaces.this]
  create_duration = "120s"
}
