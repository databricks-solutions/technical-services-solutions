# =============================================================================
# ncc.tf - Network Connectivity Config (NCC) for serverless compute
# =============================================================================
# Creates an account-level NCC and attaches it to the workspace so serverless
# compute (SQL warehouses, serverless jobs, etc.) can reach DBFS over Private
# Link. Adds private endpoint rules for the workspace root storage (blob + dfs).
# Databricks creates private endpoint requests in Azure; this file auto-approves
# them via the azapi provider. Requires databricks_account_id.
# =============================================================================

locals {
  # DBFS storage account resource ID (same as used by pe_dbfs.tf).
  dbfs_storage_resource_id = "${azurerm_databricks_workspace.dp_workspace.managed_resource_group_id}/providers/Microsoft.Storage/storageAccounts/${local.dbfsname}"
  ncc_description         = "NCC: ${databricks_mws_network_connectivity_config.ncc.name} (${databricks_mws_network_connectivity_config.ncc.network_connectivity_config_id})"
  pe_approval_body = {
    properties = {
      privateLinkServiceConnectionState = {
        description = "Approved for Databricks ${local.ncc_description}"
        status      = "Approved"
      }
    }
  }
}

# -----------------------------------------------------------------------------
# Network Connectivity Configuration (NCC)
# -----------------------------------------------------------------------------
resource "databricks_mws_network_connectivity_config" "ncc" {
  provider = databricks.account
  name     = "ncc-${local.prefix}-dp"
  region   = local.dp_rg_location
}

# -----------------------------------------------------------------------------
# Attach NCC to this workspace
# -----------------------------------------------------------------------------
resource "databricks_mws_ncc_binding" "ncc_binding" {
  provider                      = databricks.account
  network_connectivity_config_id = databricks_mws_network_connectivity_config.ncc.network_connectivity_config_id
  workspace_id                  = azurerm_databricks_workspace.dp_workspace.workspace_id
}

# -----------------------------------------------------------------------------
# Private endpoint rule: DBFS Blob
# -----------------------------------------------------------------------------
resource "databricks_mws_ncc_private_endpoint_rule" "dbfs_blob" {
  provider                      = databricks.account
  network_connectivity_config_id = databricks_mws_network_connectivity_config.ncc.network_connectivity_config_id
  resource_id                   = local.dbfs_storage_resource_id
  group_id                      = "blob"
}

# Brief pause after blob rule so the dfs rule creation starts without overloading the account API.
resource "time_sleep" "after_ncc_blob_rule" {
  create_duration = "75s"
  depends_on      = [databricks_mws_ncc_private_endpoint_rule.dbfs_blob]
}

# -----------------------------------------------------------------------------
# Private endpoint rule: DBFS DFS
# -----------------------------------------------------------------------------
resource "databricks_mws_ncc_private_endpoint_rule" "dbfs_dfs" {
  provider                      = databricks.account
  network_connectivity_config_id = databricks_mws_network_connectivity_config.ncc.network_connectivity_config_id
  resource_id                   = local.dbfs_storage_resource_id
  group_id                      = "dfs"
  depends_on                    = [time_sleep.after_ncc_blob_rule]
}

# -----------------------------------------------------------------------------
# Auto-approve NCC private endpoint connections on the DBFS storage account
# -----------------------------------------------------------------------------
data "azapi_resource" "dbfs_storage" {
  type                   = "Microsoft.Storage/storageAccounts@2024-01-01"
  resource_id             = local.dbfs_storage_resource_id
  response_export_values  = ["properties.privateEndpointConnections"]
  depends_on = [
    databricks_mws_ncc_private_endpoint_rule.dbfs_blob,
    databricks_mws_ncc_private_endpoint_rule.dbfs_dfs
  ]
}

locals {
  # Storage account GET (2024-01-01) includes privateEndpointConnections. Handle output as object (azapi 2.x) or JSON string (azapi 1.x).
  dbfs_pe_connections = try(
    data.azapi_resource.dbfs_storage.output.properties.privateEndpointConnections,
    try(jsondecode(data.azapi_resource.dbfs_storage.output).properties.privateEndpointConnections, [])
  )
  blob_pe_name = [for pe in local.dbfs_pe_connections : pe.name if endswith(try(pe.properties.privateEndpoint.id, ""), databricks_mws_ncc_private_endpoint_rule.dbfs_blob.endpoint_name)][0]
  dfs_pe_name  = [for pe in local.dbfs_pe_connections : pe.name if endswith(try(pe.properties.privateEndpoint.id, ""), databricks_mws_ncc_private_endpoint_rule.dbfs_dfs.endpoint_name)][0]
}

resource "azapi_update_resource" "ncc_pe_approve_blob" {
  type       = "Microsoft.Storage/storageAccounts/privateEndpointConnections@2024-01-01"
  name       = local.blob_pe_name
  parent_id  = local.dbfs_storage_resource_id
  body       = local.pe_approval_body
  depends_on = [data.azapi_resource.dbfs_storage]
}

resource "azapi_update_resource" "ncc_pe_approve_dfs" {
  type       = "Microsoft.Storage/storageAccounts/privateEndpointConnections@2024-01-01"
  name       = local.dfs_pe_name
  parent_id  = local.dbfs_storage_resource_id
  body       = local.pe_approval_body
  depends_on = [data.azapi_resource.dbfs_storage]
}
