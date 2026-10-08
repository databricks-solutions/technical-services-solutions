# =============================================================================
# service_endpoint_policy.tf - Storage service endpoint policy
# =============================================================================
# Restricts Microsoft.Storage traffic from the workspace subnets to only
# Databricks-managed storage (artifact Blob storage, system tables, log storage).
# Prevents data exfiltration to unauthorized storage accounts.
# Note: DBFS root storage is reached via private endpoints (pe_dbfs.tf) and is
# not subject to this policy — private endpoint traffic bypasses service endpoints.
#
# Requires: "Microsoft.Storage" in var.subnets_service_endpoints.
# Supported by default for workspaces created on or after July 14, 2025;
# for older workspaces, contact your Databricks account team to enable.
#
# To allow additional storage accounts (e.g. Unity Catalog external locations),
# add a second definition block with service = "Global" and the full resource IDs
# under service_resources.
# =============================================================================

resource "azurerm_subnet_service_endpoint_storage_policy" "dp" {
  name                = "sep-${local.prefix}-dp"
  resource_group_name = local.dp_rg_name
  location            = local.dp_rg_location
  tags                = local.tags

  definition {
    name              = "databricks-managed"
    description       = "Databricks-managed storage: artifact Blob storage, system tables, log storage (DBFS root uses private endpoints)"
    service           = "Global"
    service_resources = ["/services/Azure/Databricks"]
  }

  dynamic "definition" {
    for_each = length(var.service_endpoint_policy_storage_accounts) > 0 ? [1] : []
    content {
      name              = "customer-storage"
      description       = "Additional customer-managed storage accounts (e.g. Unity Catalog external locations, data lake accounts)"
      service           = "Microsoft.Storage"
      service_resources = var.service_endpoint_policy_storage_accounts
    }
  }
}
