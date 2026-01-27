resource "azurerm_databricks_workspace" "this" {
  name                = var.workspace_name
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  sku                 = "premium"
  tags                = var.tags

  custom_parameters {
    virtual_network_id                                   = local.vnet.id
    private_subnet_name                                  = azurerm_subnet.private.name
    public_subnet_name                                   = azurerm_subnet.public.name
    public_subnet_network_security_group_association_id  = azurerm_subnet_network_security_group_association.public.id
    private_subnet_network_security_group_association_id = azurerm_subnet_network_security_group_association.private.id
    storage_account_name                                 = var.root_storage_name
    no_public_ip                                         = true
  }

  depends_on = [
    azurerm_subnet_network_security_group_association.public,
    azurerm_subnet_network_security_group_association.private
  ]
}

# assign admin access to the workspace

data "databricks_user" "workspace_access" {
  provider = databricks.accounts
  user_name = var.admin_user
}

resource "databricks_mws_permission_assignment" "workspace_access" {
  provider = databricks.accounts
  workspace_id = azurerm_databricks_workspace.this.workspace_id
  principal_id = data.databricks_user.workspace_access.id
  permissions  = ["ADMIN"]
  depends_on = [
    databricks_metastore_assignment.this
  ]
}

# metastore creation and assignment to the workspace

resource "databricks_metastore" "this" {
  count         = var.existing_metastore_id == "" ? 1 : 0
  provider      = databricks.accounts
  name          = var.new_metastore_name
  region        = var.location
  owner         = "${var.new_metastore_name}-admins"
  depends_on = [databricks_group.metastore_owner_group]
}

resource "databricks_group" "metastore_owner_group" {
    count = var.existing_metastore_id == "" ? 1 : 0
    provider = databricks.accounts
    display_name = "${var.new_metastore_name}-admins"
}

data "databricks_user" "metastore_owner" {
  count = var.existing_metastore_id == "" ? 1 : 0
  provider = databricks.accounts
  user_name = var.admin_user
}

resource "databricks_group_member" "metastore_owner" {
  count = var.existing_metastore_id == "" ? 1 : 0
  provider = databricks.accounts
  group_id  = databricks_group.metastore_owner_group[0].id
  member_id = data.databricks_user.metastore_owner[0].id
}

resource "databricks_metastore_assignment" "this" {
  provider     = databricks.accounts
  workspace_id = azurerm_databricks_workspace.this.workspace_id
  metastore_id = var.existing_metastore_id == "" ? databricks_metastore.this[0].id : var.existing_metastore_id
}

# catalog creation

module "connect_storage" {
  source = "./modules/connect_storage"
  create_storage_account = true
  resource_group = azurerm_resource_group.this.name
  location = azurerm_resource_group.this.location
  storage_account_name = "gergeljkissa"
  tags = var.tags
}

module "create_catalog" {
  source = "./modules/catalog"
  storage_account_id = module.connect_storage.storage_account_id
  storage_account_name = module.connect_storage.storage_account_name
  storage_credential_id = module.connect_storage.storage_credential_id
  catalog_name = "demo"
  storage_container_name = "demo"
  force_destroy_external_location = true
  force_destroy_catalog = true
}