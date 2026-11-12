# =============================================================================
# unity_catalog.tf - User-defined Unity Catalog catalog (new_catalog = true)
# =============================================================================
# Creates a dedicated ADLS Gen2 storage account for a catalog, plus the access
# connector, storage credential, external location and catalog on top of it. A
# metastore must be assigned to the workspace (var.metastore_id or
# var.new_metastore_name, see databricks.tf).
# =============================================================================

locals {
  # Names fall back to values derived from resource_prefix when the optional variables are empty.
  uc_storage_account_name    = var.uc_storage_account_name != "" ? var.uc_storage_account_name : "uc${substr(join("", regexall("[a-z0-9]", lower(var.resource_prefix))), 0, 22)}"
  uc_catalog_name            = var.catalog_name != "" ? var.catalog_name : "${replace(replace(local.prefix, "-", "_"), ".", "_")}_catalog"
  uc_storage_credential_name = var.storage_credential_name != "" ? var.storage_credential_name : "${local.prefix}-storage-credential"
  uc_external_location_name  = var.external_location_name != "" ? var.external_location_name : "${local.prefix}-external-location"
}

// Create azure managed identity to be used by Databricks storage credential
resource "azurerm_databricks_access_connector" "db_mi" {
  count               = var.new_catalog ? 1 : 0
  name                = "dbac-${local.prefix}-uc"
  resource_group_name = local.resource_group_name
  location            = local.resource_group_location
  tags                = var.tags
  identity {
    type = "SystemAssigned"
  }

  lifecycle {
    precondition {
      condition     = local.assign_metastore
      error_message = "new_catalog = true needs a Unity Catalog metastore: set metastore_id (existing) or new_metastore_name (create)."
    }
  }
}

// Create a storage account to be used by catalog
resource "azurerm_storage_account" "db_uc_catalog" {
  count                    = var.new_catalog ? 1 : 0
  name                     = local.uc_storage_account_name
  resource_group_name      = local.resource_group_name
  location                 = local.resource_group_location
  tags                     = var.tags
  account_tier             = "Standard"
  account_replication_type = "LRS"
  is_hns_enabled           = true

  // Security hardening (infrastructure_encryption_enabled is create-time only).
  min_tls_version                   = "TLS1_2"
  allow_nested_items_to_be_public   = false
  infrastructure_encryption_enabled = true
}

// Create a container in storage account to be used by unity catalog metastore as root storage
resource "azurerm_storage_container" "db_uc_catalog" {
  count                 = var.new_catalog ? 1 : 0
  name                  = var.uc_container_name
  storage_account_id    = azurerm_storage_account.db_uc_catalog[0].id
  container_access_type = "private"
}

// Assign the Storage Blob Data Contributor role to managed identity to allow unity catalog to access the storage
resource "azurerm_role_assignment" "db_mi_data_contributor" {
  count                = var.new_catalog ? 1 : 0
  scope                = azurerm_storage_account.db_uc_catalog[0].id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_databricks_access_connector.db_mi[0].identity[0].principal_id
}

// Create Databricks Storage Credential
resource "databricks_storage_credential" "db_uc_storage_cred" {
  count = var.new_catalog ? 1 : 0
  name  = local.uc_storage_credential_name
  azure_managed_identity {
    access_connector_id = azurerm_databricks_access_connector.db_mi[0].id
  }
  comment = "Managed identity credential managed by TF"
  depends_on = [
    azurerm_role_assignment.db_mi_data_contributor,
    databricks_metastore_assignment.this,
    databricks_mws_permission_assignment.workspace_access,
  ]
}

// Create Databricks External Location
resource "databricks_external_location" "db_ext_loc" {
  count = var.new_catalog ? 1 : 0
  name  = local.uc_external_location_name
  url = format("abfss://%s@%s.dfs.core.windows.net",
    azurerm_storage_container.db_uc_catalog[0].name,
  azurerm_storage_account.db_uc_catalog[0].name)
  credential_name = databricks_storage_credential.db_uc_storage_cred[0].id
  comment         = "Managed by TF"
  depends_on = [
    databricks_storage_credential.db_uc_storage_cred,
    azurerm_role_assignment.db_mi_data_contributor
  ]
  force_destroy = false
}

// Create Databricks Catalog
resource "databricks_catalog" "uc_quickstart_sandbox" {
  count = var.new_catalog ? 1 : 0
  name  = local.uc_catalog_name
  storage_root = format(
    "abfss://%s@%s.dfs.core.windows.net",
    azurerm_storage_container.db_uc_catalog[0].name,
    azurerm_storage_account.db_uc_catalog[0].name
  )
  depends_on = [
    databricks_external_location.db_ext_loc
  ]
  force_destroy = false
}

# The Terraform principal stays the owner of these objects (it needs access to refresh them on later runs); the admin
# user gets ALL PRIVILEGES so they can see and manage them. Non-authoritative: other grants are kept.
resource "databricks_grant" "catalog_admin" {
  count      = var.new_catalog && var.admin_user != "" ? 1 : 0
  catalog    = databricks_catalog.uc_quickstart_sandbox[0].name
  principal  = var.admin_user
  privileges = ["ALL_PRIVILEGES"]
  depends_on = [databricks_mws_permission_assignment.workspace_access]
}

resource "databricks_grant" "external_location_admin" {
  count             = var.new_catalog && var.admin_user != "" ? 1 : 0
  external_location = databricks_external_location.db_ext_loc[0].name
  principal         = var.admin_user
  privileges        = ["ALL_PRIVILEGES"]
  depends_on        = [databricks_mws_permission_assignment.workspace_access]
}

resource "databricks_grant" "storage_credential_admin" {
  count              = var.new_catalog && var.admin_user != "" ? 1 : 0
  storage_credential = databricks_storage_credential.db_uc_storage_cred[0].name
  principal          = var.admin_user
  privileges         = ["ALL_PRIVILEGES"]
  depends_on         = [databricks_mws_permission_assignment.workspace_access]
}
