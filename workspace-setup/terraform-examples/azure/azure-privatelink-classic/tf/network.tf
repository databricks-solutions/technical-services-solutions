# =============================================================================
# network.tf - Data plane VNet, NAT gateway, NSG, and subnets
# =============================================================================
# Creates the workspace VNet with three subnets: public and private (Databricks
# delegated, with optional NAT gateway and NSG) and a dedicated Private Link subnet
# for control plane and DBFS private endpoints. Includes outbound NSG rules for
# AAD and Azure Front Door.
# =============================================================================

# -----------------------------------------------------------------------------
# Virtual network
# -----------------------------------------------------------------------------
locals {
  # Networking lives in the workspace resource group unless vnet_resource_group_name names a different one.
  separate_vnet_rg = var.vnet_resource_group_name != "" && var.vnet_resource_group_name != var.resource_group_name
  vnet_rg_name = (
    !local.separate_vnet_rg ? local.dp_rg_name :
    var.create_new_vnet ? azurerm_resource_group.vnet_rg[0].name : var.vnet_resource_group_name
  )
  vnet_name     = var.create_new_vnet ? azurerm_virtual_network.dp_vnet[0].name : data.azurerm_virtual_network.existing[0].name
  vnet_id       = var.create_new_vnet ? azurerm_virtual_network.dp_vnet[0].id : data.azurerm_virtual_network.existing[0].id
  vnet_location = var.create_new_vnet ? local.dp_rg_location : data.azurerm_virtual_network.existing[0].location
}

# Separate resource group for the VNet, only when vnet_resource_group_name names a group other than the workspace one.
resource "azurerm_resource_group" "vnet_rg" {
  count    = var.create_new_vnet && local.separate_vnet_rg ? 1 : 0
  name     = var.vnet_resource_group_name
  location = local.dp_rg_location
  tags     = local.tags
}

# Existing VNet, when create_new_vnet is false.
data "azurerm_virtual_network" "existing" {
  count               = var.create_new_vnet ? 0 : 1
  name                = var.vnet_name
  resource_group_name = local.vnet_rg_name
}

resource "azurerm_virtual_network" "dp_vnet" {
  count               = var.create_new_vnet ? 1 : 0
  name                = "vnet-${local.prefix}"
  location            = local.vnet_location
  resource_group_name = local.vnet_rg_name
  address_space       = [var.vnet_cidr]
  tags                = local.tags
}

# -----------------------------------------------------------------------------
# NAT Gateway - optional outbound internet for public and private workspace subnets
# -----------------------------------------------------------------------------
# Omit (create_nat_gateway = false) when service endpoints cover all required Azure
# traffic and no general internet egress is needed (fully private or NVA-routed).
# Static public IP used by the NAT gateway for SNAT.
resource "azurerm_public_ip" "dp_nat" {
  count               = var.create_nat_gateway ? 1 : 0
  name                = "pip-${local.prefix}-nat"
  location            = local.vnet_location
  resource_group_name = local.vnet_rg_name
  allocation_method   = "Static"
  sku                 = "Standard"
  # [] = non-zonal (default); must match the NAT gateway. `zones` is ForceNew.
  zones = var.nat_gateway_zones
  tags  = local.tags
}

# NAT gateway; associated with public IP below and with subnets via subnet_nat_gateway_association.
resource "azurerm_nat_gateway" "dp_nat" {
  count                   = var.create_nat_gateway ? 1 : 0
  name                    = "ng-${local.prefix}-nat"
  location                = local.vnet_location
  resource_group_name     = local.vnet_rg_name
  sku_name                = "Standard"
  idle_timeout_in_minutes = 10
  # [] = non-zonal (default); a single zone pins the NAT gateway.
  zones = var.nat_gateway_zones
  tags  = local.tags
}

resource "azurerm_nat_gateway_public_ip_association" "dp_nat" {
  count                = var.create_nat_gateway ? 1 : 0
  nat_gateway_id       = azurerm_nat_gateway.dp_nat[0].id
  public_ip_address_id = azurerm_public_ip.dp_nat[0].id
}

# -----------------------------------------------------------------------------
# Network security group and rules
# -----------------------------------------------------------------------------
# NSG attached to public and private subnets. Allows outbound HTTPS to AAD and Front Door only.
resource "azurerm_network_security_group" "dp_sg" {
  name                = "nsg-${local.prefix}"
  location            = local.vnet_location
  resource_group_name = local.vnet_rg_name
  tags                = local.tags
}

# Outbound to Azure Active Directory (required for workspace auth).
resource "azurerm_network_security_rule" "dp_aad" {
  name                        = "nsgsr-${local.prefix}-aad"
  priority                    = 200
  direction                   = "Outbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "443"
  source_address_prefix       = "VirtualNetwork"
  destination_address_prefix  = "AzureActiveDirectory"
  resource_group_name         = local.vnet_rg_name
  network_security_group_name = azurerm_network_security_group.dp_sg.name
}

# Outbound to Azure Front Door (required for Databricks control plane).
resource "azurerm_network_security_rule" "dp_azfrontdoor" {
  name                        = "nsgsr-${local.prefix}-afd"
  priority                    = 201
  direction                   = "Outbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "443"
  source_address_prefix       = "VirtualNetwork"
  destination_address_prefix  = "AzureFrontDoor.Frontend"
  resource_group_name         = local.vnet_rg_name
  network_security_group_name = azurerm_network_security_group.dp_sg.name
}

# -----------------------------------------------------------------------------
# Public subnet - Databricks public cluster nodes
# -----------------------------------------------------------------------------
# CIDR from var.subnet_public_cidr. Delegation required for VNet injection.
# Service endpoints (Microsoft.Storage, Microsoft.EventHub) via var.subnets_service_endpoints.
resource "azurerm_subnet" "dp_public" {
  name                            = "snet-${local.prefix}-public"
  resource_group_name             = local.vnet_rg_name
  virtual_network_name            = local.vnet_name
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

  service_endpoints           = ["Microsoft.Storage", "Microsoft.EventHub"]
  service_endpoint_policy_ids = [azurerm_subnet_service_endpoint_storage_policy.dp.id]
}

resource "azurerm_subnet_network_security_group_association" "dp_public" {
  subnet_id                 = azurerm_subnet.dp_public.id
  network_security_group_id = azurerm_network_security_group.dp_sg.id
}

resource "azurerm_subnet_nat_gateway_association" "dp_public" {
  count          = var.create_nat_gateway ? 1 : 0
  subnet_id      = azurerm_subnet.dp_public.id
  nat_gateway_id = azurerm_nat_gateway.dp_nat[0].id
}

# -----------------------------------------------------------------------------
# Private subnet - Databricks private cluster nodes
# -----------------------------------------------------------------------------
# CIDR from var.subnet_private_cidr. Service endpoints (Microsoft.Storage, Microsoft.EventHub) via var.subnets_service_endpoints.
resource "azurerm_subnet" "dp_private" {
  name                            = "snet-${local.prefix}-private"
  resource_group_name             = local.vnet_rg_name
  virtual_network_name            = local.vnet_name
  address_prefixes                = [var.subnet_private_cidr]
  default_outbound_access_enabled = false

  private_endpoint_network_policies = "Enabled"

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

  service_endpoints           = ["Microsoft.Storage", "Microsoft.EventHub"]
  service_endpoint_policy_ids = [azurerm_subnet_service_endpoint_storage_policy.dp.id]
}

resource "azurerm_subnet_network_security_group_association" "dp_private" {
  subnet_id                 = azurerm_subnet.dp_private.id
  network_security_group_id = azurerm_network_security_group.dp_sg.id
}

resource "azurerm_subnet_nat_gateway_association" "dp_private" {
  count          = var.create_nat_gateway ? 1 : 0
  subnet_id      = azurerm_subnet.dp_private.id
  nat_gateway_id = azurerm_nat_gateway.dp_nat[0].id
}

# -----------------------------------------------------------------------------
# Private Link subnet - control plane and DBFS private endpoints only
# -----------------------------------------------------------------------------
# CIDR from var.subnet_private_endpoint_cidr. No delegation; used only for private endpoints (pe_backend.tf, pe_dbfs.tf).
resource "azurerm_subnet" "dp_plsubnet" {
  name                              = "snet-${local.prefix}-privatelink"
  resource_group_name               = local.vnet_rg_name
  virtual_network_name              = local.vnet_name
  address_prefixes                  = [var.subnet_private_endpoint_cidr]
  default_outbound_access_enabled   = false
  private_endpoint_network_policies = "Enabled"
}

moved {
  from = azurerm_virtual_network.dp_vnet
  to   = azurerm_virtual_network.dp_vnet[0]
}
