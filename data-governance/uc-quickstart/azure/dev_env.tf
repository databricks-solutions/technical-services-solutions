module "dev_environment" {
  source = "./environment"
  storage_account_resource_group = "<RESOURCE_GROUP>"
  storage_account_name = "<STORAGE_ACCOUNT_NAME>"
  location = "<LOCATION>"
  providers = {
    databricks.account = databricks.account
    databricks.workspace = databricks.dev_workspace
  }
  catalogs = {
    dev = {
      name = "dev"
      owner = "uc-governance-admins-group"
      permissions = [
        {
            principal = "uc-data-engineers-group"
            privileges = [
                "USE CATALOG", "USE SCHEMA",
                "SELECT", "EXECUTE", "READ VOLUME",
                "MODIFY", "REFRESH", "WRITE VOLUME",
                "CREATE SCHEMA", "CREATE TABLE", "CREATE FUNCTION", "CREATE MATERIALIZED VIEW", "CREATE MATERIALIZED VIEW", "CREATE MODEL",
                "MANAGE", "BROWSE"
            ]
        },
        {
            principal = "uc-data-analysts-group"
            privileges = [
                "USE CATALOG", "USE SCHEMA",
                "SELECT", "EXECUTE", "READ VOLUME",
                "BROWSE"
            ]
        }
      ]
    }
  }
  tags = {
    environment = "dev"
    owner = ""
  }
}