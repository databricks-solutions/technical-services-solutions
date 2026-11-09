locals {
  # Networking lives in the workspace resource group unless vnet_resource_group_name names a different one.
  separate_vnet_rg = var.vnet_resource_group_name != "" && var.vnet_resource_group_name != var.resource_group_name
  vnet_resource_group_name = (
    !local.separate_vnet_rg ? local.resource_group_name :
    var.create_new_vnet ? azurerm_resource_group.vnet_resource_group[0].name : var.vnet_resource_group_name
  )
  vnet = var.create_new_vnet ? azurerm_virtual_network.this[0] : data.azurerm_virtual_network.existing[0]
}

# new VNet resources
resource "azurerm_virtual_network" "this" {
  count               = var.create_new_vnet ? 1 : 0
  name                = "vnet-${local.prefix}"
  location            = local.resource_group_location
  resource_group_name = local.vnet_resource_group_name
  address_space       = [var.vnet_cidr]
  tags                = var.tags
}

# Separate resource group for the VNet, only when vnet_resource_group_name names a group other than the workspace one.
resource "azurerm_resource_group" "vnet_resource_group" {
  count    = var.create_new_vnet && local.separate_vnet_rg ? 1 : 0
  name     = var.vnet_resource_group_name
  location = local.resource_group_location
  tags     = var.tags
}

# existing VNet resources
data "azurerm_virtual_network" "existing" {
  count               = var.create_new_vnet ? 0 : 1
  name                = var.vnet_name
  resource_group_name = local.vnet_resource_group_name
}

# other network resources

resource "azurerm_network_security_group" "this" {
  name                = "nsg-${local.prefix}"
  location            = local.vnet.location
  resource_group_name = local.vnet_resource_group_name
  tags                = var.tags
}

resource "azurerm_subnet" "public" {
  name                            = "snet-${local.prefix}-public"
  resource_group_name             = local.vnet_resource_group_name
  virtual_network_name            = local.vnet.name
  address_prefixes                = [var.subnet_public_cidr]
  default_outbound_access_enabled = false

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
  name                            = "snet-${local.prefix}-private"
  resource_group_name             = local.vnet_resource_group_name
  virtual_network_name            = local.vnet.name
  address_prefixes                = [var.subnet_private_cidr]
  default_outbound_access_enabled = false

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

# NAT Gateway resources (create_nat_gateway)

resource "azurerm_public_ip" "this" {
  count               = var.create_nat_gateway ? 1 : 0
  name                = "pip-${local.prefix}-nat"
  resource_group_name = local.vnet_resource_group_name
  location            = local.vnet.location
  allocation_method   = "Static"
  sku                 = "Standard"
  zones               = var.nat_gateway_zones
  tags                = var.tags
}

resource "azurerm_nat_gateway" "this" {
  count                   = var.create_nat_gateway ? 1 : 0
  name                    = "ng-${local.prefix}-nat"
  resource_group_name     = local.vnet_resource_group_name
  location                = local.vnet.location
  sku_name                = "Standard"
  idle_timeout_in_minutes = 10
  zones                   = var.nat_gateway_zones
  tags                    = var.tags
}

resource "azurerm_nat_gateway_public_ip_association" "this" {
  count                = var.create_nat_gateway ? 1 : 0
  nat_gateway_id       = azurerm_nat_gateway.this[0].id
  public_ip_address_id = azurerm_public_ip.this[0].id
}

resource "azurerm_subnet_nat_gateway_association" "public_nat_gateway_association" {
  count          = var.create_nat_gateway ? 1 : 0
  subnet_id      = azurerm_subnet.public.id
  nat_gateway_id = azurerm_nat_gateway.this[0].id
}

resource "azurerm_subnet_nat_gateway_association" "private_nat_gateway_association" {
  count          = var.create_nat_gateway ? 1 : 0
  subnet_id      = azurerm_subnet.private.id
  nat_gateway_id = azurerm_nat_gateway.this[0].id
}

# These resources now have count (create_nat_gateway). Keep existing deployments from replacing them.
moved {
  from = azurerm_public_ip.this
  to   = azurerm_public_ip.this[0]
}

moved {
  from = azurerm_nat_gateway.this
  to   = azurerm_nat_gateway.this[0]
}

moved {
  from = azurerm_nat_gateway_public_ip_association.this
  to   = azurerm_nat_gateway_public_ip_association.this[0]
}

moved {
  from = azurerm_subnet_nat_gateway_association.public_nat_gateway_association
  to   = azurerm_subnet_nat_gateway_association.public_nat_gateway_association[0]
}

moved {
  from = azurerm_subnet_nat_gateway_association.private_nat_gateway_association
  to   = azurerm_subnet_nat_gateway_association.private_nat_gateway_association[0]
}
