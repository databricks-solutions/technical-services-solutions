# =============================================================================
# databricks.tf - Databricks workspace with VNet injection
# =============================================================================
# Creates a Premium Databricks workspace injected into the data plane VNet
# (public and private subnets). Root storage (DBFS) uses the derived storage
# account name. Public network access is always enabled (no front-end Private Link).
# Managed resource group named mrg-<workspace_name>.
#
# default_storage_firewall_enabled + access_connector_id restrict the workspace
# root storage account to private access (use with private endpoints in pe_dbfs.tf).
#
# Unity Catalog metastore (account API), pick at most one:
#   - var.metastore_id         : assign an existing metastore to the workspace
#   - var.new_metastore_name   : create a metastore (owned by a new admins group) and assign it
# Neither set = skip (attach in console). Catalog, storage credential and external
# location live in unity_catalog.tf.
# =============================================================================

# Access connector used with default_storage_firewall_enabled so DBFS storage can use private connectivity.
resource "azurerm_databricks_access_connector" "dbfs" {
  name                = "dbac-${local.prefix}-dbfs"
  resource_group_name = local.dp_rg_name
  location            = local.dp_rg_location
  tags                = local.tags

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_databricks_workspace" "dp_workspace" {
  name                                  = "dbw-${local.prefix}-dp"
  resource_group_name                   = local.dp_rg_name
  location                              = local.dp_rg_location
  sku                                   = "premium"
  tags                                  = local.tags
  public_network_access_enabled         = true
  network_security_group_rules_required = "NoAzureDatabricksRules"
  # Named MRG (e.g. mrg-dbw-ts-privatelink-test-dp). Changing this forces workspace replacement.
  managed_resource_group_name      = "mrg-dbw-${local.prefix}-dp"
  default_storage_firewall_enabled = true
  access_connector_id              = azurerm_databricks_access_connector.dbfs.id

  # VNet injection: use dp_public and dp_private subnets and their NSG associations.
  # storage_account_name is the workspace root (DBFS) storage; must be unique and alphanumeric.
  custom_parameters {
    virtual_network_id                                   = azurerm_virtual_network.dp_vnet.id
    private_subnet_name                                  = azurerm_subnet.dp_private.name
    public_subnet_name                                   = azurerm_subnet.dp_public.name
    public_subnet_network_security_group_association_id  = azurerm_subnet_network_security_group_association.dp_public.id
    private_subnet_network_security_group_association_id = azurerm_subnet_network_security_group_association.dp_private.id
    storage_account_name                                 = local.dbfsname
  }

  depends_on = [
    azurerm_subnet_network_security_group_association.dp_public,
    azurerm_subnet_network_security_group_association.dp_private,
    databricks_mws_network_connectivity_config.ncc
  ]
}

# -----------------------------------------------------------------------------
# Unity Catalog metastore: create (optional) and assign to the workspace
# -----------------------------------------------------------------------------
locals {
  create_metastore = var.new_metastore_name != ""
  assign_metastore = var.metastore_id != "" || local.create_metastore
  metastore_id     = local.create_metastore ? databricks_metastore.this[0].id : var.metastore_id
}

resource "databricks_group" "metastore_owner_group" {
  count        = local.create_metastore ? 1 : 0
  provider     = databricks.account
  display_name = "${var.new_metastore_name}-admins"
}

data "databricks_user" "metastore_owner" {
  count     = local.create_metastore ? 1 : 0
  provider  = databricks.account
  user_name = var.admin_user
}

resource "databricks_group_member" "metastore_owner" {
  count     = local.create_metastore ? 1 : 0
  provider  = databricks.account
  group_id  = databricks_group.metastore_owner_group[0].id
  member_id = data.databricks_user.metastore_owner[0].id
}

resource "databricks_metastore" "this" {
  count         = local.create_metastore ? 1 : 0
  provider      = databricks.account
  name          = var.new_metastore_name
  region        = local.dp_rg_location
  owner         = databricks_group.metastore_owner_group[0].display_name
  force_destroy = true # Required to destroy the metastore while it still has catalogs and workspaces attached.

  lifecycle {
    precondition {
      condition     = var.metastore_id == ""
      error_message = "Set at most one of metastore_id (assign existing) or new_metastore_name (create), not both."
    }
    precondition {
      condition     = var.admin_user != ""
      error_message = "admin_user is required when new_metastore_name is set (it becomes a member of the metastore admins group)."
    }
  }
}

resource "databricks_metastore_assignment" "dp_workspace" {
  count = local.assign_metastore ? 1 : 0

  provider     = databricks.account
  workspace_id = azurerm_databricks_workspace.dp_workspace.workspace_id
  metastore_id = local.metastore_id

  depends_on = [azurerm_databricks_workspace.dp_workspace, databricks_group_member.metastore_owner]
}

# Workspace admin for var.admin_user, so the user can use the workspace (and own the optional cluster).
data "databricks_user" "workspace_admin" {
  count     = var.admin_user != "" ? 1 : 0
  provider  = databricks.account
  user_name = var.admin_user
}

resource "databricks_mws_permission_assignment" "workspace_admin" {
  count        = var.admin_user != "" ? 1 : 0
  provider     = databricks.account
  workspace_id = azurerm_databricks_workspace.dp_workspace.workspace_id
  principal_id = data.databricks_user.workspace_admin[0].id
  permissions  = ["ADMIN"]

  depends_on = [databricks_metastore_assignment.dp_workspace]
}

# -----------------------------------------------------------------------------
# Unity Catalog only: disable direct access to the legacy Hive metastore
# -----------------------------------------------------------------------------
# Matches the Databricks SRA template. Created only when a metastore is assigned (without one the workspace has
# nothing else to fall back on). Permanent after 30 days: direct Hive metastore access cannot be re-enabled.
# With a catalog created here, set it as the default first: the default cannot stay hive_metastore.
resource "databricks_default_namespace_setting" "this" {
  count    = var.new_catalog ? 1 : 0
  provider = databricks.workspace
  namespace {
    value = databricks_catalog.uc[0].name
  }
}

resource "databricks_disable_legacy_access_setting" "this" {
  count    = local.assign_metastore ? 1 : 0
  provider = databricks.workspace
  disable_legacy_access {
    value = true
  }
  depends_on = [databricks_metastore_assignment.dp_workspace, databricks_default_namespace_setting.this]
}

