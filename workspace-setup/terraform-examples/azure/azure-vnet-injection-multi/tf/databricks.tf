resource "azurerm_databricks_workspace" "this" {
  for_each = var.workspaces

  name                = each.value.workspace_name
  resource_group_name = local.rg.name
  location            = local.rg.location
  sku                 = "premium"
  tags                = var.tags

  managed_resource_group_name = try(each.value.managed_resource_group_name, null)

  custom_parameters {
    virtual_network_id                                   = local.vnet.id
    private_subnet_name                                  = azurerm_subnet.private[each.key].name
    public_subnet_name                                   = azurerm_subnet.public[each.key].name
    public_subnet_network_security_group_association_id  = azurerm_subnet_network_security_group_association.public[each.key].id
    private_subnet_network_security_group_association_id = azurerm_subnet_network_security_group_association.private[each.key].id
    storage_account_name                                 = each.value.root_storage_name
    no_public_ip                                         = true
  }

  depends_on = [
    azurerm_subnet_network_security_group_association.public,
    azurerm_subnet_network_security_group_association.private
  ]
}

# assign admin access to the workspace

data "databricks_user" "workspace_access" {
  provider  = databricks.accounts
  user_name = var.admin_user
}


# metastore creation and assignment to the workspace

resource "databricks_metastore" "this" {
  count      = var.existing_metastore_id == "" ? 1 : 0
  provider   = databricks.accounts
  name       = var.new_metastore_name
  region     = var.location
  owner      = "${var.new_metastore_name}-admins"
  depends_on = [databricks_group.metastore_owner_group]
}

resource "databricks_group" "metastore_owner_group" {
  count        = var.existing_metastore_id == "" ? 1 : 0
  provider     = databricks.accounts
  display_name = "${var.new_metastore_name}-admins"
}

data "databricks_user" "metastore_owner" {
  count     = var.existing_metastore_id == "" ? 1 : 0
  provider  = databricks.accounts
  user_name = var.admin_user
}

resource "databricks_group_member" "metastore_owner" {
  count     = var.existing_metastore_id == "" ? 1 : 0
  provider  = databricks.accounts
  group_id  = databricks_group.metastore_owner_group[0].id
  member_id = data.databricks_user.metastore_owner[0].id
}

resource "databricks_mws_permission_assignment" "workspace_access" {
  for_each     = var.workspaces
  provider     = databricks.accounts
  workspace_id = azurerm_databricks_workspace.this[each.key].workspace_id
  principal_id = data.databricks_user.workspace_access.id
  permissions  = ["ADMIN"]
}