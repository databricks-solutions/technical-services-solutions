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
# Optional: when var.metastore_id is set, assigns an existing Unity Catalog
# metastore to the workspace (account API). Empty = skip (attach in console).
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
  name                           = "dbw-${local.prefix}-dp"
  resource_group_name            = local.dp_rg_name
  location                       = local.dp_rg_location
  sku                            = "premium"
  tags                           = local.tags
  public_network_access_enabled  = true
  network_security_group_rules_required = "NoAzureDatabricksRules"
  customer_managed_key_enabled   = true
  # Named MRG (e.g. mrg-dbw-ts-privatelink-test-dp). Changing this forces workspace replacement.
  managed_resource_group_name    = "mrg-dbw-${local.prefix}-dp"
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

resource "databricks_metastore_assignment" "dp_workspace" {
  count = length(trimspace(var.metastore_id)) > 0 ? 1 : 0

  provider     = databricks.account
  workspace_id = azurerm_databricks_workspace.dp_workspace.workspace_id
  metastore_id = var.metastore_id

  depends_on = [azurerm_databricks_workspace.dp_workspace]
}
