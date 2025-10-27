resource "azurerm_databricks_workspace" "this" {
  name                = var.workspace_name
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  sku                 = "premium"
  tags                = var.tags

#   Customer managed key (CMK) configuration
#   customer_managed_key_enabled          = true
#   managed_services_cmk_key_vault_id     = var.managed_services_cmk_key_vault_id
#   managed_services_cmk_key_vault_key_id = var.managed_services_cmk_key_vault_key_id
#   managed_disk_cmk_key_vault_id         = var.managed_disk_cmk_key_vault_id
#   managed_disk_cmk_key_vault_key_id     = var.managed_disk_cmk_key_vault_key_id

  custom_parameters {
    virtual_network_id                                   = azurerm_virtual_network.this.id
    private_subnet_name                                  = azurerm_subnet.private.name
    public_subnet_name                                   = azurerm_subnet.public.name
    public_subnet_network_security_group_association_id  = azurerm_subnet_network_security_group_association.public.id
    private_subnet_network_security_group_association_id = azurerm_subnet_network_security_group_association.private.id
    storage_account_name                                 = var.root_storage_name
  }

  depends_on = [
    azurerm_subnet_network_security_group_association.public,
    azurerm_subnet_network_security_group_association.private
  ]
}