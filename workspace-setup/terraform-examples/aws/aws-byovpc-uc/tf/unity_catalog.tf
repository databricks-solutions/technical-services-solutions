# Delay after IAM policy is attached so AWS / UC propagation can settle before
# Databricks validates S3 read on external location creation.
resource "time_sleep" "wait_60_seconds" {
  count           = var.new_catalog ? 1 : 0
  depends_on      = [aws_iam_policy_attachment.unity_catalog_attach, aws_iam_role_policy.uc_file_events]
  create_duration = "60s"
}

locals {
  uc_iam_role         = "${var.resource_prefix}-catalog"
  uc_catalog_name_us  = replace(var.prefix, "-", "_")
  catalog_bucket_name = "${var.resource_prefix}-catalog-storage-${join("", random_string.catalog_bucket_suffix[*].result)}"

  # Resolved UC object names (optional vars default to "" in variables.tf; prefix-based defaults cannot live in variable defaults)
  uc_catalog_name            = var.catalog_name != "" ? var.catalog_name : "${var.prefix}-catalog"
  uc_external_location_name  = var.external_location_name != "" ? var.external_location_name : "${var.resource_prefix}-external-location"
  uc_storage_credential_name = var.storage_credential_name != "" ? var.storage_credential_name : "${var.resource_prefix}-storage-credential"

  # File events: in "provided" mode Terraform owns a tagged SQS queue instead of letting
  # Databricks auto-create untagged csms-* SNS/SQS resources (which tag-enforcing SCPs deny).
  uc_file_events_provided = var.new_catalog && var.uc_file_events_mode == "provided"
  uc_file_events_tags     = merge(var.tags, var.uc_file_events_tags)
}

resource "random_string" "catalog_bucket_suffix" {
  count   = var.new_catalog ? 1 : 0
  length  = 8
  special = false
  upper   = false
}

# Storage Credential (created before role): https://registry.terraform.io/providers/databricks/databricks/latest/docs/guides/unity-catalog#configure-external-locations-and-credentials
resource "databricks_storage_credential" "uc_storage_cred" {
  count    = var.new_catalog ? 1 : 0
  provider = databricks.workspace
  name     = local.uc_storage_credential_name
  aws_iam_role {
    role_arn = "arn:aws:iam::${var.aws_account_id}:role/${local.uc_iam_role}"
  }
  depends_on = [databricks_metastore_assignment.this]
}

# Unity Catalog Trust Policy - Data Source
data "databricks_aws_unity_catalog_assume_role_policy" "unity_catalog" {
  count                 = var.new_catalog ? 1 : 0
  provider              = databricks.workspace
  aws_account_id        = var.aws_account_id
  aws_partition         = "aws"
  role_name             = local.uc_iam_role
  unity_catalog_iam_arn = "arn:aws:iam::414351767826:role/unity-catalog-prod-UCMasterRole-14S5ZJVKOTYTL"
  external_id           = databricks_storage_credential.uc_storage_cred[0].aws_iam_role[0].external_id
}

# Unity Catalog Policy - Data Source
data "databricks_aws_unity_catalog_policy" "unity_catalog" {
  count          = var.new_catalog ? 1 : 0
  provider       = databricks.workspace
  aws_account_id = var.aws_account_id
  aws_partition  = "aws"
  bucket_name    = local.catalog_bucket_name
  role_name      = local.uc_iam_role
}

# Unity Catalog Policy
resource "aws_iam_policy" "unity_catalog" {
  count  = var.new_catalog ? 1 : 0
  name   = "${var.prefix}-catalog-policy"
  policy = data.databricks_aws_unity_catalog_policy.unity_catalog[0].json
}

# Unity Catalog Role
resource "aws_iam_role" "unity_catalog" {
  count              = var.new_catalog ? 1 : 0
  name               = local.uc_iam_role
  assume_role_policy = data.databricks_aws_unity_catalog_assume_role_policy.unity_catalog[0].json
}

# Unity Catalog Policy Attachment
resource "aws_iam_policy_attachment" "unity_catalog_attach" {
  count      = var.new_catalog ? 1 : 0
  name       = "${var.prefix}-unity_catalog_policy_attach"
  roles      = [aws_iam_role.unity_catalog[0].name]
  policy_arn = aws_iam_policy.unity_catalog[0].arn
}

# Unity Catalog S3
resource "aws_s3_bucket" "unity_catalog_bucket" {
  count         = var.new_catalog ? 1 : 0
  bucket        = local.catalog_bucket_name
  force_destroy = true
  tags          = var.tags
}

resource "aws_s3_bucket_versioning" "unity_catalog_versioning" {
  count  = var.new_catalog ? 1 : 0
  bucket = aws_s3_bucket.unity_catalog_bucket[0].id
  versioning_configuration {
    status = "Disabled"
  }
}

resource "aws_s3_bucket_public_access_block" "unity_catalog" {
  count                   = var.new_catalog ? 1 : 0
  bucket                  = aws_s3_bucket.unity_catalog_bucket[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
  depends_on              = [aws_s3_bucket.unity_catalog_bucket]
}

# File events (Provided mode): tagged SQS queue fed by S3 notifications on the catalog bucket.
# Tags are set on the resource itself so they are sent with the CreateQueue request.
resource "aws_sqs_queue" "uc_file_events" {
  count                     = local.uc_file_events_provided ? 1 : 0
  name                      = "${var.resource_prefix}-uc-file-events"
  message_retention_seconds = 1209600 # 14 days
  sqs_managed_sse_enabled   = true
  tags                      = local.uc_file_events_tags
}

resource "aws_sqs_queue_policy" "uc_file_events" {
  count     = local.uc_file_events_provided ? 1 : 0
  queue_url = aws_sqs_queue.uc_file_events[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowS3SendMessage"
        Effect    = "Allow"
        Principal = { Service = "s3.amazonaws.com" }
        Action    = "sqs:SendMessage"
        Resource  = aws_sqs_queue.uc_file_events[0].arn
        Condition = {
          ArnEquals    = { "aws:SourceArn" = aws_s3_bucket.unity_catalog_bucket[0].arn }
          StringEquals = { "aws:SourceAccount" = var.aws_account_id }
        }
      }
    ]
  })
}

# NOTE: aws_s3_bucket_notification owns the bucket's ENTIRE notification configuration;
# any other notifications on this bucket not declared here will be removed.
resource "aws_s3_bucket_notification" "uc_file_events" {
  count  = local.uc_file_events_provided ? 1 : 0
  bucket = aws_s3_bucket.unity_catalog_bucket[0].id

  queue {
    queue_arn = aws_sqs_queue.uc_file_events[0].arn
    events    = ["s3:ObjectCreated:*", "s3:ObjectRemoved:*"]
  }

  depends_on = [aws_sqs_queue_policy.uc_file_events]
}

# The stock databricks_aws_unity_catalog_policy only grants SQS access to csms-* queues,
# so grant the UC role access to the Terraform-managed queue.
resource "aws_iam_role_policy" "uc_file_events" {
  count = local.uc_file_events_provided ? 1 : 0
  name  = "${var.prefix}-uc-file-events-policy"
  role  = aws_iam_role.unity_catalog[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "UCFileEventsQueueAccess"
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:PurgeQueue",
          "sqs:GetQueueAttributes",
          "sqs:GetQueueUrl",
          "sqs:ChangeMessageVisibility",
        ]
        Resource = aws_sqs_queue.uc_file_events[0].arn
      }
    ]
  })
}

# External Location
resource "databricks_external_location" "uc_external_location" {
  count              = var.new_catalog ? 1 : 0
  provider           = databricks.workspace
  name               = local.uc_external_location_name
  url                = "s3://${aws_s3_bucket.unity_catalog_bucket[0].id}"
  credential_name    = databricks_storage_credential.uc_storage_cred[0].id
  force_destroy      = true
  enable_file_events = local.uc_file_events_provided

  # Provided mode only; omitting the block with enable_file_events = false disables file events.
  dynamic "file_event_queue" {
    for_each = local.uc_file_events_provided ? [1] : []
    content {
      provided_sqs {
        queue_url = aws_sqs_queue.uc_file_events[0].url
      }
    }
  }

  depends_on = [
    time_sleep.wait_60_seconds,
    aws_s3_bucket_notification.uc_file_events,
    aws_iam_role_policy.uc_file_events,
  ]
}
resource "databricks_catalog" "uc_quickstart" {
  count         = var.new_catalog ? 1 : 0
  provider      = databricks.workspace
  name          = local.uc_catalog_name
  storage_root  = databricks_external_location.uc_external_location[0].url
  comment       = "this catalog is managed by terraform"
  force_destroy = true
  # enable_predictive_optimization = "ENABLE"
  # isolation_mode = "OPEN"
  # properties = {
  #   purpose = "development"
  # }
}
