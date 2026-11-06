# =============================================================================
# ncc_uc.tf - NCC private endpoint rules for the Unity Catalog storage account
# =============================================================================
# Extends the NCC from ncc.tf so serverless compute (SQL warehouses, serverless
# jobs) can reach the catalog storage account over Private Link. Same flow as for
# DBFS: Databricks raises private endpoint requests on the storage account and
# this file auto-approves them via azapi. Rules are created one at a time with a
# delay to avoid account API timeouts, and after the DBFS rules.
# =============================================================================

resource "databricks_mws_ncc_private_endpoint_rule" "uc_blob" {
  count                          = var.new_catalog ? 1 : 0
  provider                       = databricks.account
  network_connectivity_config_id = databricks_mws_network_connectivity_config.ncc.network_connectivity_config_id
  resource_id                    = azurerm_storage_account.uc[0].id
  group_id                       = "blob"
  depends_on                     = [databricks_mws_ncc_private_endpoint_rule.dbfs_dfs]
}

resource "time_sleep" "after_ncc_uc_blob_rule" {
  count           = var.new_catalog ? 1 : 0
  create_duration = "75s"
  depends_on      = [databricks_mws_ncc_private_endpoint_rule.uc_blob]
}

resource "databricks_mws_ncc_private_endpoint_rule" "uc_dfs" {
  count                          = var.new_catalog ? 1 : 0
  provider                       = databricks.account
  network_connectivity_config_id = databricks_mws_network_connectivity_config.ncc.network_connectivity_config_id
  resource_id                    = azurerm_storage_account.uc[0].id
  group_id                       = "dfs"
  depends_on                     = [time_sleep.after_ncc_uc_blob_rule]
}

data "azapi_resource" "uc_storage" {
  count                  = var.new_catalog ? 1 : 0
  type                   = "Microsoft.Storage/storageAccounts@2024-01-01"
  resource_id            = azurerm_storage_account.uc[0].id
  response_export_values = ["properties.privateEndpointConnections"]
  depends_on = [
    databricks_mws_ncc_private_endpoint_rule.uc_blob,
    databricks_mws_ncc_private_endpoint_rule.uc_dfs
  ]
}

locals {
  # azapi 2.x returns output as a typed object; [] if no connections yet.
  uc_pe_connections = var.new_catalog ? try(data.azapi_resource.uc_storage[0].output.properties.privateEndpointConnections, []) : []
  uc_blob_pe_name   = var.new_catalog ? [for pe in local.uc_pe_connections : pe.name if endswith(try(pe.properties.privateEndpoint.id, ""), databricks_mws_ncc_private_endpoint_rule.uc_blob[0].endpoint_name)][0] : ""
  uc_dfs_pe_name    = var.new_catalog ? [for pe in local.uc_pe_connections : pe.name if endswith(try(pe.properties.privateEndpoint.id, ""), databricks_mws_ncc_private_endpoint_rule.uc_dfs[0].endpoint_name)][0] : ""
}

resource "azapi_update_resource" "ncc_pe_approve_uc_blob" {
  count      = var.new_catalog ? 1 : 0
  type       = "Microsoft.Storage/storageAccounts/privateEndpointConnections@2024-01-01"
  name       = local.uc_blob_pe_name
  parent_id  = azurerm_storage_account.uc[0].id
  body       = local.pe_approval_body
  depends_on = [data.azapi_resource.uc_storage]
}

resource "azapi_update_resource" "ncc_pe_approve_uc_dfs" {
  count     = var.new_catalog ? 1 : 0
  type      = "Microsoft.Storage/storageAccounts/privateEndpointConnections@2024-01-01"
  name      = local.uc_dfs_pe_name
  parent_id = azurerm_storage_account.uc[0].id
  body      = local.pe_approval_body
  # Storage returns 409 StorageAccountOperationInProgress if two PE connection updates run concurrently.
  depends_on = [
    data.azapi_resource.uc_storage,
    azapi_update_resource.ncc_pe_approve_uc_blob,
  ]
}
