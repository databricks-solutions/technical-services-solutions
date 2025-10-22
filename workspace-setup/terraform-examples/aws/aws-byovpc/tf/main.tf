# Databricks Workspace Deployment on AWS with BYOVPC
#
# This configuration creates a Databricks workspace with customer-managed VPC
# All resources are defined in separate files for better organization:
# - providers.tf: Provider configurations
# - versions.tf: Terraform and provider version constraints
# - variables.tf: Input variable definitions
# - network.tf: VPC and networking resources
# - security_group.tf: Security group rules
# - credential.tf: IAM roles and policies
# - root_s3_bucket.tf: S3 bucket for workspace root storage
# - workspace.tf: Databricks workspace resources
# - metastore.tf: Unity Catalog metastore configuration
# - outputs.tf: Output values

