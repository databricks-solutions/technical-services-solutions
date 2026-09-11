resource "databricks_catalog" "uc_catalog" {
  name    = var.catalog_name
  storage_root = databricks_external_location.uc_external_location.url
  comment = "this catalog is managed by Terraform"
  enable_predictive_optimization = "ENABLE"
  isolation_mode = "ISOLATED"
  owner = var.owner
  force_destroy = var.force_destroy_catalog
}