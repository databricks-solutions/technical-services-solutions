resource "aws_s3_bucket" "root" {
  bucket        = var.root_bucket_name
  force_destroy = true
}

resource "aws_s3_bucket_ownership_controls" "root" {
  bucket = aws_s3_bucket.root.id
  rule {
    object_ownership = "ObjectWriter"
  }
}

resource "aws_s3_bucket_versioning" "v" {
  bucket = aws_s3_bucket.root.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "sse" {
  bucket = aws_s3_bucket.root.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "root" {
  bucket                  = aws_s3_bucket.root.id
  block_public_acls       = true
  block_public_policy     = false
  ignore_public_acls      = true
  restrict_public_buckets = false
}

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "bucket_policy" {
  statement {
    sid    = "Grant Databricks Full Access"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListBucket",
      "s3:GetBucketLocation",
      "s3:PutObjectAcl"
    ]
    resources = [
      aws_s3_bucket.root.arn,
      "${aws_s3_bucket.root.arn}/*"
    ]
    principals {
      type = "AWS"
      identifiers = [
        var.cross_account_role_arn,
        "arn:aws:iam::414351767826:root"
      ]
    }
  }
}

resource "aws_s3_bucket_policy" "root" {
  bucket = aws_s3_bucket.root.id
  policy = data.aws_iam_policy_document.bucket_policy.json
}

output "root_bucket" { value = aws_s3_bucket.root.bucket }
output "root_bucket_arn" { value = aws_s3_bucket.root.arn }
