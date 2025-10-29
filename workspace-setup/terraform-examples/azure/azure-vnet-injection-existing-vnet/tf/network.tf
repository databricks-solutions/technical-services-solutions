locals {
    network_prefix = var.workspace_name
}

data "azurerm_virtual_network" "existing" {
  name                = var.vnet_name
  resource_group_name = var.vnet_resource_group_name
}

data "azurerm_resource_group" "vnet_resource_group" {
  name = var.vnet_resource_group_name
}


resource "azurerm_network_security_group" "this" {
  name                = "${local.network_prefix}-nsg"
  location            = data.azurerm_resource_group.vnet_resource_group.location
  resource_group_name = data.azurerm_resource_group.vnet_resource_group.name
  tags                = var.tags
}

resource "azurerm_subnet" "public" {
  name                 = "${local.network_prefix}-public-subnet"
  resource_group_name  = data.azurerm_resource_group.vnet_resource_group.name
  virtual_network_name = data.azurerm_virtual_network.existing.name
  address_prefixes     = [var.subnet_public_cidr]

  delegation {
    name = "databricks"
    service_delegation {
      name = "Microsoft.Databricks/workspaces"
      actions = [
        "Microsoft.Network/virtualNetworks/subnets/join/action",
        "Microsoft.Network/virtualNetworks/subnets/prepareNetworkPolicies/action",
        "Microsoft.Network/virtualNetworks/subnets/unprepareNetworkPolicies/action"]
    }
  }
}

resource "azurerm_subnet_network_security_group_association" "public" {
  subnet_id                 = azurerm_subnet.public.id
  network_security_group_id = azurerm_network_security_group.this.id
}

resource "azurerm_subnet" "private" {
  name                 = "${local.network_prefix}-private-subnet"
  resource_group_name  = data.azurerm_resource_group.vnet_resource_group.name
  virtual_network_name = data.azurerm_virtual_network.existing.name
  address_prefixes     = [var.subnet_private_cidr]

  delegation {
    name = "databricks"
    service_delegation {
      name = "Microsoft.Databricks/workspaces"
      actions = [
        "Microsoft.Network/virtualNetworks/subnets/join/action",
        "Microsoft.Network/virtualNetworks/subnets/prepareNetworkPolicies/action",
        "Microsoft.Network/virtualNetworks/subnets/unprepareNetworkPolicies/action"]
    }
  }
}

resource "azurerm_subnet_network_security_group_association" "private" {
  subnet_id                 = azurerm_subnet.private.id
  network_security_group_id = azurerm_network_security_group.this.id
}