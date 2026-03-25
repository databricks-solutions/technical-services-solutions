output "external_location_name" {
  description = "Name of the Unity Catalog external location"
  value       = databricks_external_location.db_ext_loc.name
}

output "catalog_name" {
  description = "Name of the default Unity Catalog catalog"
  value       = databricks_catalog.uc_quickstart_sandbox.name
}
