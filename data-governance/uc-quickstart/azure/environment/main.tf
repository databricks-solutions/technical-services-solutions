// CONNECT STORAGE TO UC
module "storage" {
  source = "./connect_storage"
  providers = {
    databricks = databricks.account
    databricks.workspace = databricks.workspace
  }
  storage_account_resource_group = var.storage_account_resource_group
  location = var.location
  storage_account_name = var.storage_account_name
  create_storage_account = true
  enable_file_events = true
  tags = var.tags
}

// CREATE CATALOG
module "catalog" {
  for_each = var.catalogs
  source = "./create_catalog"
  providers = {
    databricks = databricks.workspace
  }
  catalog_name = each.value.name
  storage_container_name = each.value.name
  storage_account_id = module.storage.storage_account_id
  storage_account_name = module.storage.storage_account_name
  storage_credential_id = module.storage.storage_credential_id
  force_destroy_external_location = false
  force_destroy_catalog = false
  owner = each.value.owner
}

// GRANT PRIVILEGES TO CATALOG
locals {
  # Flatten the catalogs and permissions into a map for for_each
  catalog_permissions = flatten([
    for catalog_name, catalog_config in var.catalogs : [
      for idx, permission in catalog_config.permissions : {
        key        = "${catalog_name}-${idx}"
        catalog    = catalog_name
        principal  = permission.principal
        privileges = permission.privileges
      }
    ]
  ])
}

resource "databricks_grant" "this" {
  provider   = databricks.workspace
  for_each   = { for perm in local.catalog_permissions : perm.key => perm }
  catalog    = module.catalog[each.value.catalog].catalog_name
  principal  = each.value.principal
  privileges = each.value.privileges
}