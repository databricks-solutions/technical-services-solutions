resource "databricks_policy_info" "tenant_row_isolation" {
  on_securable_type     = "SCHEMA"
  on_securable_fullname = "${var.catalog_name}.${var.schema_name}"
  name                  = "tenant_row_isolation"
  comment = "Restrict rows by tenant membership using group mapping table"

  policy_type           = "POLICY_TYPE_ROW_FILTER"
  for_securable_type    = "TABLE"
  to_principals         = ["account users"]
  except_principals     = []

  match_columns = [
    {
      condition = "has_tag_value('${databricks_tag_policy.tag_rls.tag_key}', 'tenant')"
      alias     = "rls_col"
    }
  ]

  row_filter = {
    function_name = "${var.catalog_name}.${var.schema_name}.filter_users_rls"
    using = [
      {
        alias = "rls_col"
      }
    ]
  }
  depends_on = [ databricks_tag_policy.tag_rls ]
}

resource "databricks_policy_info" "mask_classified_emails" {
  on_securable_type     = "SCHEMA"
  on_securable_fullname = "${var.catalog_name}.${var.schema_name}"
  name                  = "mask_classified_emails"
  comment = "Mask email columns detected by Data Classification"

  policy_type           = "POLICY_TYPE_COLUMN_MASK"
  for_securable_type    = "TABLE"
  to_principals         = ["account users"]
  except_principals     = []

  match_columns = [
    {
      condition = "has_tag('class.email_address')"
      alias     = "email_col"
    }
  ]

  column_mask = {
    function_name = "${var.catalog_name}.${var.schema_name}.filter_email"
    on_column = "email_col"
  }
}

resource "databricks_policy_info" "mask_classified_ages" {
  on_securable_type     = "SCHEMA"
  on_securable_fullname = "${var.catalog_name}.${var.schema_name}"
  name                  = "mask_classified_ages"
  comment = "Mask age columns detected by Data Classification"

  policy_type           = "POLICY_TYPE_COLUMN_MASK"
  for_securable_type    = "TABLE"
  to_principals         = ["account users"]
  except_principals     = []

  match_columns = [
    {
      condition = "has_tag('class.age')"
      alias     = "age_col"
    }
  ]

  column_mask = {
    function_name = "${var.catalog_name}.${var.schema_name}.filter_age"
    on_column = "age_col"
  }
}