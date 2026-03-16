# =============================================================================
# network.tf - Data plane VNet, NAT gateway, NSG, and subnets
# =============================================================================
# Creates the workspace VNet with three subnets: public and private (Databricks
# delegated, with NSG and NAT gateway) and a dedicated Private Link subnet for
# control plane and DBFS private endpoints. Includes outbound NSG rules for
# AAD and Azure Front Door.
# =============================================================================

# -----------------------------------------------------------------------------
# Virtual network
# -----------------------------------------------------------------------------
resource "azurerm_virtual_network" "dp_vnet" {
  name                = "vnet-${local.prefix}-dp"
  location            = local.dp_rg_location
  resource_group_name = local.dp_rg_name
  address_space       = [var.cidr_dp]
  tags                = local.tags
}

# -----------------------------------------------------------------------------
# NAT Gateway - outbound internet for public and private workspace subnets
# -----------------------------------------------------------------------------
# Static public IP used by the NAT gateway for SNAT.
resource "azurerm_public_ip" "dp_nat" {
  name                = "pip-${local.prefix}-dp-nat"
  location            = local.dp_rg_location
  resource_group_name = local.dp_rg_name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.tags
}

# NAT gateway; associated with public IP below and with subnets via subnet_nat_gateway_association.
resource "azurerm_nat_gateway" "dp_nat" {
  name                    = "ng-${local.prefix}-dp-nat"
  location                = local.dp_rg_location
  resource_group_name     = local.dp_rg_name
  sku_name                = "Standard"
  idle_timeout_in_minutes = 10
  tags                    = local.tags
}

resource "azurerm_nat_gateway_public_ip_association" "dp_nat" {
  nat_gateway_id       = azurerm_nat_gateway.dp_nat.id
  public_ip_address_id = azurerm_public_ip.dp_nat.id
}

# -----------------------------------------------------------------------------
# Network security group and rules
# -----------------------------------------------------------------------------
# NSG attached to public and private subnets. Allows outbound HTTPS to AAD and Front Door only.
resource "azurerm_network_security_group" "dp_sg" {
  name                = "nsg-${local.prefix}-dp"
  location            = local.dp_rg_location
  resource_group_name = local.dp_rg_name
  tags                = local.tags
}

# Outbound to Azure Active Directory (required for workspace auth).
resource "azurerm_network_security_rule" "dp_aad" {
  name                        = "nsgsr-${local.prefix}-dp-aad"
  priority                    = 200
  direction                   = "Outbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "443"
  source_address_prefix       = "VirtualNetwork"
  destination_address_prefix  = "AzureActiveDirectory"
  resource_group_name         = local.dp_rg_name
  network_security_group_name = azurerm_network_security_group.dp_sg.name
}

# Outbound to Azure Front Door (required for Databricks control plane).
resource "azurerm_network_security_rule" "dp_azfrontdoor" {
  name                        = "nsgsr-${local.prefix}-dp-afd"
  priority                    = 201
  direction                   = "Outbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "443"
  source_address_prefix       = "VirtualNetwork"
  destination_address_prefix  = "AzureFrontDoor.Frontend"
  resource_group_name         = local.dp_rg_name
  network_security_group_name = azurerm_network_security_group.dp_sg.name
}

# -----------------------------------------------------------------------------
# Public subnet - Databricks public cluster nodes
# -----------------------------------------------------------------------------
# CIDR from var.subnet_workspace_cidrs[0]. Delegation required for VNet injection.
# Service endpoints (e.g. Microsoft.Storage) via var.subnets_service_endpoints.
resource "azurerm_subnet" "dp_public" {
  name                 = "snet-${local.prefix}-dp-public"
  resource_group_name  = local.dp_rg_name
  virtual_network_name = azurerm_virtual_network.dp_vnet.name
  address_prefixes     = [var.subnet_workspace_cidrs[0]]

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

  service_endpoints = var.subnets_service_endpoints
}

resource "azurerm_subnet_network_security_group_association" "dp_public" {
  subnet_id                 = azurerm_subnet.dp_public.id
  network_security_group_id = azurerm_network_security_group.dp_sg.id
}

resource "azurerm_subnet_nat_gateway_association" "dp_public" {
  subnet_id      = azurerm_subnet.dp_public.id
  nat_gateway_id = azurerm_nat_gateway.dp_nat.id
}

# -----------------------------------------------------------------------------
# Private subnet - Databricks private cluster nodes
# -----------------------------------------------------------------------------
# CIDR from var.subnet_workspace_cidrs[1]. Service endpoints (e.g. Microsoft.Storage) via var.subnets_service_endpoints.
resource "azurerm_subnet" "dp_private" {
  name                 = "snet-${local.prefix}-dp-private"
  resource_group_name  = local.dp_rg_name
  virtual_network_name = azurerm_virtual_network.dp_vnet.name
  address_prefixes     = [var.subnet_workspace_cidrs[1]]

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

  service_endpoints = var.subnets_service_endpoints
}

resource "azurerm_subnet_network_security_group_association" "dp_private" {
  subnet_id                 = azurerm_subnet.dp_private.id
  network_security_group_id = azurerm_network_security_group.dp_sg.id
}

resource "azurerm_subnet_nat_gateway_association" "dp_private" {
  subnet_id      = azurerm_subnet.dp_private.id
  nat_gateway_id = azurerm_nat_gateway.dp_nat.id
}

# -----------------------------------------------------------------------------
# Private Link subnet - control plane and DBFS private endpoints only
# -----------------------------------------------------------------------------
# CIDR from var.subnet_private_endpoint_cidr. No delegation; used only for private endpoints (pe_backend.tf, pe_dbfs.tf).
resource "azurerm_subnet" "dp_plsubnet" {
  name                              = "snet-${local.prefix}-dp-privatelink"
  resource_group_name               = local.dp_rg_name
  virtual_network_name              = azurerm_virtual_network.dp_vnet.name
  address_prefixes                  = [var.subnet_private_endpoint_cidr]
  private_endpoint_network_policies = "Enabled"
}
