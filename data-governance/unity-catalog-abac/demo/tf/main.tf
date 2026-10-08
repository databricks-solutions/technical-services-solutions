## The automatic Data Classification Terraform resource contains a bug at the moment, so we are not using it for now. Manual assignment of the system tags are done in governed_tags.tf 


# resource "databricks_budget_policy" "this" {
#   policy_name = "abac_demo_budget_policy"
#   custom_tags = [{
#     key = "workload"
#     value = "data_classification"
#   }]
# }

# resource "databricks_data_classification_catalog_config" "data_classification_config" {
#   parent = "catalogs/${var.catalog_name}"

#   included_schemas = {
#     names = [var.schema_name]
#   }

#   auto_tag_configs = [
#     {
#       classification_tag = "class.email_address"
#       auto_tagging_mode  = "AUTO_TAGGING_ENABLED"
#     },
#     {
#       classification_tag = "class.age"
#       auto_tagging_mode  = "AUTO_TAGGING_ENABLED"
#     }
#   ]

# }