locals {
  external_location_name = "${var.catalog_name}_external_location"
}

// STORAGE CONTAINER
// Create a container in storage account to be used as catalog root storage
resource "azurerm_storage_container" "this" {
  name                  = var.storage_container_name
  storage_account_id    = var.storage_account_id
  container_access_type = "private"
}

// EXTERNAL LOCATION
// Create a external location in Unity Catalog
resource "databricks_external_location" "this" {
  name = local.external_location_name
  url = format("abfss://%s@%s.dfs.core.windows.net/",
    azurerm_storage_container.this.name,
  var.storage_account_name)
  credential_name = var.storage_credential_id
  comment         = "Managed by TF"
  # Made configurable to prevent accidental data loss in production
  force_destroy = var.force_destroy_external_location
}

// CATALOG
resource "databricks_catalog" "this" {
  name         = var.catalog_name
  storage_root = format(
    "abfss://%s@%s.dfs.core.windows.net/%s",
    azurerm_storage_container.this.name,
    var.storage_account_name,
    var.catalog_name
  )
  depends_on = [
    databricks_external_location.this
  ]
  enable_predictive_optimization = "ENABLE"
  isolation_mode = "ISOLATED"
  owner = var.owner
  # Made configurable to prevent accidental data loss in production
  # This setting controls whether the catalog and all its contents are deleted on terraform destroy
  force_destroy = var.force_destroy_catalog
}