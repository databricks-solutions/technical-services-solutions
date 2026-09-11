module "dev_environment" {
  source = "./environment"
  aws_account_id = var.aws_account_id
  providers = {
    databricks = databricks.dev_workspace
  }
  catalogs = {
    dev = {
      name = "dev"
      bucket_name = "dev-bucket-dfghjgifnddgu"
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