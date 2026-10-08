################################################################################
# 4. Unity Catalog Metastore
################################################################################

# Three optional lookups for an existing metastore. Used in priority order:
# explicit ID, then by name, then any metastore in the same region.
data "databricks_metastore" "existing_by_id" {
  count    = var.use_existing_metastore && var.existing_metastore_id != null ? 1 : 0
  provider = databricks.account

  metastore_id = var.existing_metastore_id
}

data "databricks_metastore" "existing_by_name" {
  count    = var.use_existing_metastore && var.existing_metastore_id == null && var.existing_metastore_name != null ? 1 : 0
  provider = databricks.account

  name = var.existing_metastore_name
}

data "databricks_metastore" "existing_by_region" {
  count    = var.use_existing_metastore && var.existing_metastore_id == null && var.existing_metastore_name == null ? 1 : 0
  provider = databricks.account

  region = var.region
}

# Create a new metastore.
#
# We intentionally do NOT set owner = workspace_admin_email here. The deployment
# SP needs to remain metastore owner during the apply so it can create the
# storage credential and external location below. The user gets equivalent
# admin-level access via databricks_grants.metastore_for_admin further down.
#
# lifecycle.ignore_changes=[owner] lets a human transfer ownership in the UI
# later without Terraform reverting it on the next apply.
resource "databricks_metastore" "this" {
  count    = var.use_existing_metastore ? 0 : 1
  provider = databricks.account

  name          = var.metastore_name != null ? var.metastore_name : "${var.prefix}-${var.region}-metastore"
  region        = var.region
  force_destroy = true

  lifecycle {
    ignore_changes = [owner]
  }
}

# Resolve metastore_id from whichever path was used (existing or new).
locals {
  resolved_metastore_id = var.use_existing_metastore ? coalesce(
    try(data.databricks_metastore.existing_by_id[0].id, null),
    try(data.databricks_metastore.existing_by_name[0].id, null),
    try(data.databricks_metastore.existing_by_region[0].id, null)
  ) : databricks_metastore.this[0].id
}

# Assign the metastore to the workspace. Required before any UC objects can be
# created in the workspace.
resource "databricks_metastore_assignment" "this" {
  provider = databricks.account

  workspace_id = local.workspace_id
  metastore_id = local.resolved_metastore_id

  depends_on = [
    databricks_mws_ncc_binding.ncc_binding
  ]

  lifecycle {
    precondition {
      condition     = local.resolved_metastore_id != null
      error_message = "Metastore ID could not be resolved. If using an existing metastore, provide existing_metastore_id or existing_metastore_name, or ensure a metastore exists in the same region."
    }
  }
}

# Grant the workspace admin user admin-level privileges on the metastore.
# Only applied when we created the metastore — for existing metastores you
# manage grants separately.
#
# Uses the workspace provider (not account) because metastore-level grants
# require workspace context in the current Databricks Terraform provider.
resource "databricks_grants" "metastore_for_admin" {
  count    = var.use_existing_metastore ? 0 : 1
  provider = databricks.workspace

  metastore = local.resolved_metastore_id

  grant {
    principal = var.workspace_admin_email
    privileges = [
      "CREATE_CATALOG",
      "CREATE_EXTERNAL_LOCATION",
      "CREATE_STORAGE_CREDENTIAL",
      "CREATE_PROVIDER",
      "CREATE_RECIPIENT",
      "CREATE_SHARE",
      "USE_PROVIDER",
      "USE_RECIPIENT",
      "USE_SHARE",
    ]
  }

  depends_on = [
    databricks_metastore.this,
    databricks_metastore_assignment.this,
  ]
}
