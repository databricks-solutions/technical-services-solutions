resource "azurerm_resource_group" "vnet_resource_group" {
  count    = var.vnet_resource_group_name != var.resource_group_name ? 1 : 0
  name     = var.vnet_resource_group_name
  location = local.rg.location
}

locals {
  vnet_resource_group = (
    var.vnet_resource_group_name == var.resource_group_name
    ? local.rg
    : azurerm_resource_group.vnet_resource_group[0]
  )
}

resource "azurerm_virtual_network" "this" {
  name                = var.vnet_name
  location            = local.rg.location
  resource_group_name = local.vnet_resource_group.name
  address_space       = [var.cidr]
  tags                = var.tags
}

locals {
  vnet = azurerm_virtual_network.this
}

resource "azurerm_network_security_group" "this" {
  for_each            = var.workspaces
  name                = "${each.value.workspace_name}-nsg"
  location            = local.vnet.location
  resource_group_name = local.vnet_resource_group.name
  tags                = var.tags
}

resource "azurerm_subnet" "public" {
  for_each                        = var.workspaces
  name                            = "${each.value.workspace_name}-public-subnet"
  resource_group_name             = local.vnet_resource_group.name
  virtual_network_name            = local.vnet.name
  address_prefixes                = [each.value.subnet_public_cidr]
  default_outbound_access_enabled = false

  delegation {
    name = "databricks"
    service_delegation {
      name = "Microsoft.Databricks/workspaces"
      actions = [
        "Microsoft.Network/virtualNetworks/subnets/join/action",
        "Microsoft.Network/virtualNetworks/subnets/prepareNetworkPolicies/action",
        "Microsoft.Network/virtualNetworks/subnets/unprepareNetworkPolicies/action"
      ]
    }
  }
}

resource "azurerm_subnet_network_security_group_association" "public" {
  for_each                  = var.workspaces
  subnet_id                 = azurerm_subnet.public[each.key].id
  network_security_group_id = azurerm_network_security_group.this[each.key].id
}

resource "azurerm_subnet" "private" {
  for_each                        = var.workspaces
  name                            = "${each.value.workspace_name}-private-subnet"
  resource_group_name             = local.vnet_resource_group.name
  virtual_network_name            = local.vnet.name
  address_prefixes                = [each.value.subnet_private_cidr]
  default_outbound_access_enabled = false

  delegation {
    name = "databricks"
    service_delegation {
      name = "Microsoft.Databricks/workspaces"
      actions = [
        "Microsoft.Network/virtualNetworks/subnets/join/action",
        "Microsoft.Network/virtualNetworks/subnets/prepareNetworkPolicies/action",
        "Microsoft.Network/virtualNetworks/subnets/unprepareNetworkPolicies/action"
      ]
    }
  }
}

resource "azurerm_subnet_network_security_group_association" "private" {
  for_each                  = var.workspaces
  subnet_id                 = azurerm_subnet.private[each.key].id
  network_security_group_id = azurerm_network_security_group.this[each.key].id
}

resource "azurerm_public_ip" "this" {
  for_each            = var.workspaces
  name                = "${each.value.workspace_name}-public-ip"
  resource_group_name = local.vnet_resource_group.name
  location            = local.vnet.location
  allocation_method   = "Static"
  zones               = ["1"]
  tags                = var.tags
}

resource "azurerm_nat_gateway" "this" {
  for_each                = var.workspaces
  name                    = "${each.value.workspace_name}-nat-gateway"
  resource_group_name     = local.vnet_resource_group.name
  location                = local.vnet.location
  sku_name                = "Standard"
  idle_timeout_in_minutes = 10
  zones                   = ["1"]
  tags                    = var.tags
}

resource "azurerm_nat_gateway_public_ip_association" "this" {
  for_each             = var.workspaces
  nat_gateway_id       = azurerm_nat_gateway.this[each.key].id
  public_ip_address_id = azurerm_public_ip.this[each.key].id
}

resource "azurerm_subnet_nat_gateway_association" "public_nat_gateway_association" {
  for_each       = var.workspaces
  subnet_id      = azurerm_subnet.public[each.key].id
  nat_gateway_id = azurerm_nat_gateway.this[each.key].id
}

resource "azurerm_subnet_nat_gateway_association" "private_nat_gateway_association" {
  for_each       = var.workspaces
  subnet_id      = azurerm_subnet.private[each.key].id
  nat_gateway_id = azurerm_nat_gateway.this[each.key].id
}