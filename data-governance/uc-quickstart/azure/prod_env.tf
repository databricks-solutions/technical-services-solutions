module "prod_environment" {
  source = "./environment"
  providers = {
    databricks.workspace = databricks.prod_workspace
    databricks.account   = databricks.account
  }
  storage_account_resource_group = "<RESOURCE_GROUP>"
  storage_account_name = "<STORAGE_ACCOUNT_NAME>"
  location = "<LOCATION>"
  catalogs = {
    prod = {
      name = "prod"
      owner = "uc-governance-admins-group"
      permissions = [
        {
            principal = "uc-service-principals-group"
            privileges = [
                "USE CATALOG", "USE SCHEMA",
                "SELECT", "EXECUTE", "READ VOLUME",
                "MODIFY", "REFRESH", "WRITE VOLUME",
                "CREATE SCHEMA", "CREATE TABLE", "CREATE FUNCTION", "CREATE MATERIALIZED VIEW", "CREATE MATERIALIZED VIEW", "CREATE MODEL",
                "MANAGE", "BROWSE"
            ]
        }
      ]
    }
  }
  tags = {
    environment = "prod"
    owner = ""
  }
}