locals {
    users_demo_table_name = "${var.catalog_name}.${var.schema_name}.user"
}

# RLS tenant tag assignment
resource "databricks_tag_policy" "tag_rls" {
  tag_key     = "abac_demo_rls"
  description = "Tag for Row Level Security"
  values = [
    {
      name = "tenant"
    }
  ]
}

resource "databricks_entity_tag_assignment" "tag_rls_assignment" {
  entity_type = "columns"
  entity_name = "${local.users_demo_table_name}.tenant_name"
  tag_key     = "${databricks_tag_policy.tag_rls.tag_key}"
  tag_value   = "tenant"
}

# Age tag assignment
data "databricks_tag_policy" "tag_age" {
  tag_key = "class.age"
}

resource "databricks_entity_tag_assignment" "tag_age_assignment" {
  entity_type = "columns"
  entity_name = "${local.users_demo_table_name}.age"
  tag_key     = "${data.databricks_tag_policy.tag_age.tag_key}"
  tag_value   = ""
}

# Email address tag assignment
data "databricks_tag_policy" "tag_email_address" {
  tag_key = "class.email_address"
}

resource "databricks_entity_tag_assignment" "tag_email_assignment" {
  entity_type = "columns"
  entity_name = "${local.users_demo_table_name}.email"
  tag_key     = "${data.databricks_tag_policy.tag_email_address.tag_key}"
  tag_value   = ""
}