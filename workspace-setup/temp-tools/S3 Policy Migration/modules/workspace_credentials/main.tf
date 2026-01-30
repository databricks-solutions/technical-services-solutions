# Get all external locations
data "databricks_external_locations" "all" {
  provider = databricks.workspace
}

data "databricks_current_metastore" "this" {
  provider = databricks.workspace
}

# Query individual external locations to get their storage URLs
locals {
  external_location_names = coalesce(try(data.databricks_external_locations.all.names, []), [])
}

data "databricks_external_location" "by_name" {
  provider = databricks.workspace
  for_each = toset(local.external_location_names)
  name     = each.value
}

locals {
  # Resolve storage URLs from the provider schema (external_location_info[0].url).
  # Short-circuit to an empty map when there are no external locations so we do
  # not even attempt to read attributes off non-existent resources.
  external_location_urls = length(local.external_location_names) == 0 ? {} : {
    for name, location in data.databricks_external_location.by_name :
    name => try(location.external_location_info[0].url, null)
  }

  external_location_bucket_arns = length(local.external_location_names) == 0 ? {} : {
    for name, url in local.external_location_urls :
    name => (
      url != null && (startswith(lower(url), "s3://") || startswith(lower(url), "s3a://")) ?
      "arn:aws:s3:::${split("/", replace(replace(url, "s3a://", ""), "s3://", ""))[0]}" :
      null
    )
  }
}
