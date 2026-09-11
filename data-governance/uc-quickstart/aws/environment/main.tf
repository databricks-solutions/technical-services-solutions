module "catalog" {
  for_each = var.catalogs
  source = "./create_catalog"
  # providers = {
  #   databricks = databricks.workspace
  # }
  aws_account_id = var.aws_account_id
  bucket_name = each.value.bucket_name
  catalog_name = each.value.name
  force_destroy_s3_bucket = false
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
  #provider   = databricks.workspace
  for_each   = { for perm in local.catalog_permissions : perm.key => perm }
  catalog    = module.catalog[each.value.catalog].catalog_name
  principal  = each.value.principal
  privileges = each.value.privileges
}