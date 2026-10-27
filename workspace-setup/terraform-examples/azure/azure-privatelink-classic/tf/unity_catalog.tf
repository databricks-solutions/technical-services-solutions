# =============================================================================
# unity_catalog.tf - User-defined Unity Catalog catalog on private storage
# =============================================================================
# Creates (when var.new_catalog is true) a dedicated ADLS Gen2 storage account for
# a Unity Catalog catalog, plus the access connector, storage credential, external
# location and catalog on top of it. A metastore must be assigned to the workspace
# (var.metastore_id or var.new_metastore_name, see databricks.tf).
#
# The storage account is locked down to match the rest of this Private Link setup:
#   - The access connector is added as a resource instance rule (as with "enabled from
#     selected networks"), then public network access is disabled. The rule stays in
#     place, so the Databricks control plane can still validate the storage credential /
#     external location and manage the catalog.
#   - Classic compute reaches it over private endpoints in the Private Link subnet
#     (pe_uc.tf, private DNS zones from dns_zones.tf).
#   - Serverless compute reaches it over NCC private endpoint rules (ncc_uc.tf).
# =============================================================================

locals {
  # Storage account: 3-24 chars, lowercase alphanumeric. Default is derived from resource_prefix.
  uc_storage_account_name = var.uc_storage_account_name != "" ? var.uc_storage_account_name : "uc${substr(join("", regexall("[a-z0-9]", lower(var.resource_prefix))), 0, 22)}"

  # Resolved UC object names (optional vars default to "" in variables.tf; prefix-based defaults cannot live in variable defaults).
  uc_catalog_name            = var.catalog_name != "" ? var.catalog_name : "${replace(replace(local.prefix, "-", "_"), ".", "_")}_catalog"
  uc_storage_credential_name = var.storage_credential_name != "" ? var.storage_credential_name : "${local.prefix}-storage-credential"
  uc_external_location_name  = var.external_location_name != "" ? var.external_location_name : "${local.prefix}-external-location"
}

# Managed identity used by the Databricks storage credential.
resource "azurerm_databricks_access_connector" "uc" {
  count               = var.new_catalog ? 1 : 0
  name                = "dbac-${local.prefix}-uc"
  resource_group_name = local.dp_rg_name
  location            = local.dp_rg_location
  tags                = local.tags

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

resource "azurerm_storage_account" "uc" {
  count                    = var.new_catalog ? 1 : 0
  name                     = local.uc_storage_account_name
  resource_group_name      = local.dp_rg_name
  location                 = local.dp_rg_location
  tags                     = local.tags
  account_tier             = "Standard"
  account_replication_type = "LRS"
  is_hns_enabled           = true

  # Security hardening (infrastructure_encryption_enabled is create-time only).
  min_tls_version                   = "TLS1_2"
  allow_nested_items_to_be_public   = false
  infrastructure_encryption_enabled = true

  # Created as "enabled from selected networks" so the resource instance rule below can be set. Public network
  # access is then switched off by azapi_update_resource.uc_disable_public_access, which keeps the rule in place.
  public_network_access_enabled = true

  network_rules {
    default_action = "Deny"
    bypass         = ["AzureServices"]

    # Resource instance rule: lets this catalog's access connector (the Databricks control plane) reach the storage.
    private_link_access {
      endpoint_resource_id = azurerm_databricks_access_connector.uc[0].id
      endpoint_tenant_id   = data.azurerm_client_config.current.tenant_id
    }
  }

  lifecycle {
    # Public access is turned off out of band (azapi_update_resource.uc_disable_public_access); without this the
    # next plan would flip it back to enabled.
    ignore_changes = [public_network_access_enabled]
  }
}

# Step 2: disable public network access once the resource instance rule is in place. Data access is then only via
# private endpoints (classic compute) and NCC private endpoint rules (serverless); the access connector rule stays.
resource "azapi_update_resource" "uc_disable_public_access" {
  count       = var.new_catalog ? 1 : 0
  type        = "Microsoft.Storage/storageAccounts@2024-01-01"
  resource_id = azurerm_storage_account.uc[0].id

  body = {
    properties = {
      publicNetworkAccess = "Disabled"
    }
  }

  depends_on = [azurerm_storage_container.uc]
}

# Container used as the catalog's storage root.
resource "azurerm_storage_container" "uc" {
  count                 = var.new_catalog ? 1 : 0
  name                  = var.uc_container_name
  storage_account_id    = azurerm_storage_account.uc[0].id
  container_access_type = "private"
}

# Allow the access connector's managed identity to read/write the storage account.
resource "azurerm_role_assignment" "uc_data_contributor" {
  count                = var.new_catalog ? 1 : 0
  scope                = azurerm_storage_account.uc[0].id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_databricks_access_connector.uc[0].identity[0].principal_id
}

# Role assignments and the storage network changes take a while to propagate; without this delay the
# storage credential / external location validation can fail with a 403.
resource "time_sleep" "uc_storage_propagation" {
  count           = var.new_catalog ? 1 : 0
  create_duration = "60s"
  depends_on      = [azurerm_role_assignment.uc_data_contributor, azapi_update_resource.uc_disable_public_access]
}

resource "databricks_storage_credential" "uc" {
  count    = var.new_catalog ? 1 : 0
  provider = databricks.workspace
  name     = local.uc_storage_credential_name
  comment  = "Managed identity credential managed by TF"

  azure_managed_identity {
    access_connector_id = azurerm_databricks_access_connector.uc[0].id
  }

  depends_on = [
    databricks_metastore_assignment.dp_workspace,
    databricks_mws_permission_assignment.workspace_admin,
    time_sleep.uc_storage_propagation,
  ]
}

resource "databricks_external_location" "uc" {
  count           = var.new_catalog ? 1 : 0
  provider        = databricks.workspace
  name            = local.uc_external_location_name
  url             = "abfss://${azurerm_storage_container.uc[0].name}@${azurerm_storage_account.uc[0].name}.dfs.core.windows.net"
  credential_name = databricks_storage_credential.uc[0].id
  comment         = "Managed by TF"
  force_destroy   = false
}

resource "databricks_catalog" "uc" {
  count    = var.new_catalog ? 1 : 0
  provider = databricks.workspace
  name     = local.uc_catalog_name
  # Built from known names, with one trailing slash, instead of referencing the external location url: the provider
  # returns storage_root with a trailing slash, and the external location url changes after apply, so either
  # reference form ends in "Provider produced inconsistent final plan".
  storage_root  = "abfss://${azurerm_storage_container.uc[0].name}@${azurerm_storage_account.uc[0].name}.dfs.core.windows.net/"
  comment       = "This catalog is managed by Terraform"
  force_destroy = false

  depends_on = [databricks_external_location.uc]
}

# The Terraform principal stays the catalog owner (it needs USE CATALOG to refresh the catalog on later runs);
# the admin user gets ALL PRIVILEGES so they can see and manage it. Non-authoritative: other grants are kept.
resource "databricks_grant" "catalog_admin" {
  count      = var.new_catalog && var.admin_user != "" ? 1 : 0
  provider   = databricks.workspace
  catalog    = databricks_catalog.uc[0].name
  principal  = var.admin_user
  privileges = ["ALL_PRIVILEGES"]
  depends_on = [databricks_mws_permission_assignment.workspace_admin]
}

# Same for the external location and storage credential, so the admin user can see them too.
resource "databricks_grant" "external_location_admin" {
  count             = var.new_catalog && var.admin_user != "" ? 1 : 0
  provider          = databricks.workspace
  external_location = databricks_external_location.uc[0].name
  principal         = var.admin_user
  privileges        = ["ALL_PRIVILEGES"]
}

resource "databricks_grant" "storage_credential_admin" {
  count              = var.new_catalog && var.admin_user != "" ? 1 : 0
  provider           = databricks.workspace
  storage_credential = databricks_storage_credential.uc[0].name
  principal          = var.admin_user
  privileges         = ["ALL_PRIVILEGES"]
}
