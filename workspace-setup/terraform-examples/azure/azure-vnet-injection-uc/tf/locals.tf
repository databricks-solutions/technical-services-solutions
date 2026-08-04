resource "random_id" "suffix" {
  byte_length = 4
}

locals {
  name_suffix = random_id.suffix.hex

  workspace_name              = "${var.workspace_name}${local.name_suffix}"
  root_storage_name           = "${var.root_storage_name}${local.name_suffix}"
  catalog_name                = "${var.catalog_name}${local.name_suffix}"
  storage_credential_name     = "${var.storage_credential_name}${local.name_suffix}"
  external_location_name      = "${var.external_location_name}${local.name_suffix}"
  storage_account_name        = "${var.uc_storage_account_name}${local.name_suffix}"
  resource_group_name         = "${var.resource_group_name}${local.name_suffix}"
  managed_resource_group_name = var.managed_resource_group_name != null ? "${var.managed_resource_group_name}${local.name_suffix}" : null
  vnet_resource_group_name    = "${var.vnet_resource_group_name}${local.name_suffix}"

  # Suffix only when creating a new VNet; existing VNet lookups use var.vnet_name as-is.
  vnet_name              = var.vnet_name != "" ? "${var.vnet_name}${local.name_suffix}" : null
  vnet_name_for_creation = coalesce(local.vnet_name, "${local.workspace_name}-vnet")
}
