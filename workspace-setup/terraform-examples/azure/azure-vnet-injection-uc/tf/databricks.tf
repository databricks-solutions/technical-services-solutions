resource "azurerm_databricks_workspace" "this" {
  name                        = local.workspace_name
  resource_group_name         = local.resource_group_name
  location                    = local.resource_group_location
  sku                         = "premium"
  tags                        = var.tags
  managed_resource_group_name = local.managed_resource_group_name

  custom_parameters {
    virtual_network_id                                   = local.vnet.id
    private_subnet_name                                  = azurerm_subnet.private.name
    public_subnet_name                                   = azurerm_subnet.public.name
    public_subnet_network_security_group_association_id  = azurerm_subnet_network_security_group_association.public.id
    private_subnet_network_security_group_association_id = azurerm_subnet_network_security_group_association.private.id
    storage_account_name                                 = local.dbfsname
    no_public_ip                                         = true
  }

  lifecycle {
    precondition {
      condition     = var.create_nat_gateway
      error_message = "create_nat_gateway = false is not supported by this template: without Private Link, clusters reach the Databricks control plane only through the NAT gateway and would not launch. Use the azure-privatelink-classic template to deploy without NAT."
    }
  }

  depends_on = [
    azurerm_subnet_network_security_group_association.public,
    azurerm_subnet_network_security_group_association.private
  ]
}

# assign admin access to the workspace (skipped when admin_user is empty)

data "databricks_user" "workspace_access" {
  count     = var.admin_user != "" ? 1 : 0
  provider  = databricks.accounts
  user_name = var.admin_user
}

resource "databricks_mws_permission_assignment" "workspace_access" {
  count        = var.admin_user != "" ? 1 : 0
  provider     = databricks.accounts
  workspace_id = azurerm_databricks_workspace.this.workspace_id
  principal_id = data.databricks_user.workspace_access[0].id
  permissions  = ["ADMIN"]
  depends_on = [
    databricks_metastore_assignment.this
  ]
}

moved {
  from = databricks_mws_permission_assignment.workspace_access
  to   = databricks_mws_permission_assignment.workspace_access[0]
}

# metastore: assign an existing one (metastore_id) or create one (new_metastore_name) and assign it to the workspace.
# Neither set = no metastore assignment here (attach one manually in the account console).

locals {
  create_metastore = var.new_metastore_name != ""
  assign_metastore = var.metastore_id != "" || local.create_metastore
  metastore_id     = local.create_metastore ? databricks_metastore.this[0].id : var.metastore_id
}

resource "databricks_metastore" "this" {
  count         = local.create_metastore ? 1 : 0
  provider      = databricks.accounts
  name          = var.new_metastore_name
  region        = local.resource_group_location
  owner         = "${var.new_metastore_name}-admins"
  force_destroy = true
  depends_on    = [databricks_group.metastore_owner_group]

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

resource "databricks_group" "metastore_owner_group" {
  count        = local.create_metastore ? 1 : 0
  provider     = databricks.accounts
  display_name = "${var.new_metastore_name}-admins"
}

data "databricks_user" "metastore_owner" {
  count     = local.create_metastore ? 1 : 0
  provider  = databricks.accounts
  user_name = var.admin_user
}

resource "databricks_group_member" "metastore_owner" {
  count     = local.create_metastore ? 1 : 0
  provider  = databricks.accounts
  group_id  = databricks_group.metastore_owner_group[0].id
  member_id = data.databricks_user.metastore_owner[0].id
}

resource "databricks_metastore_assignment" "this" {
  count        = local.assign_metastore ? 1 : 0
  provider     = databricks.accounts
  workspace_id = azurerm_databricks_workspace.this.workspace_id
  metastore_id = local.metastore_id

  depends_on = [databricks_group_member.metastore_owner]
}

moved {
  from = databricks_metastore_assignment.this
  to   = databricks_metastore_assignment.this[0]
}
