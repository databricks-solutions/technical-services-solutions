# module "prod_environment" {
#   source = "./environment"
#   aws_account_id = var.aws_account_id
#   providers = {
#     databricks = databricks.prod_workspace
#   }
#   catalogs = {
#     prod = {
#       name = "prod"
#       bucket_name = "prod-bucket"
#       owner = "uc-governance-admins-group"
#       permissions = [
#         {
#             principal = "uc-service-principals-group"
#             privileges = [
#                 "USE CATALOG", "USE SCHEMA",
#                 "SELECT", "EXECUTE", "READ VOLUME",
#                 "MODIFY", "REFRESH", "WRITE VOLUME",
#                 "CREATE SCHEMA", "CREATE TABLE", "CREATE FUNCTION", "CREATE MATERIALIZED VIEW", "CREATE MATERIALIZED VIEW", "CREATE MODEL",
#                 "MANAGE", "BROWSE"
#             ]
#         }
#       ]
#     }
#   }
#   tags = {
#     environment = "prod"
#     owner = ""
#   }
# }