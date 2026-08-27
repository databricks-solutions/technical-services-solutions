# Unity Catalog metastore bucket
resource "aws_s3_bucket" "metastore" {
  bucket        = "${var.prefix}-unity-catalog-${var.region}"
  force_destroy = true
}

resource "aws_s3_bucket_ownership_controls" "metastore" {
  bucket = aws_s3_bucket.metastore.id
  rule {
    object_ownership = "BucketOwnerPreferred"
  }
}

resource "aws_s3_bucket_versioning" "metastore" {
  bucket = aws_s3_bucket.metastore.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "metastore" {
  bucket = aws_s3_bucket.metastore.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "metastore" {
  bucket                  = aws_s3_bucket.metastore.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_caller_identity" "current" {}

# IAM role for Unity Catalog to access the metastore bucket
# Trust policy: Databricks can assume this role
# Self-assuming is added after role creation to avoid circular dependency
resource "aws_iam_role" "unity_catalog" {
  name = "${var.prefix}-unity-catalog-role"

  # Initial trust policy - only Databricks
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::414351767826:root"
        }
        Action = "sts:AssumeRole"
        Condition = {
          StringEquals = {
            "sts:ExternalId" = var.databricks_account_id
          }
        }
      }
    ]
  })

  # Lifecycle to ignore changes after self-assume is added
  lifecycle {
    ignore_changes = [assume_role_policy]
  }
}

# Wait for role to be created and propagated
resource "time_sleep" "wait_for_role" {
  create_duration = "10s"
  depends_on      = [aws_iam_role.unity_catalog]
}

# Update trust policy to add self-assuming capability
# This must happen AFTER the role exists
resource "null_resource" "add_self_assume_to_trust_policy" {
  triggers = {
    role_arn = aws_iam_role.unity_catalog.arn
  }

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-c"]
    command     = <<-EOT
      # Create trust policy with both Databricks and self-assume
      cat > /tmp/trust_policy_${var.prefix}.json <<'EOF'
      {
        "Version": "2012-10-17",
        "Statement": [
          {
            "Effect": "Allow",
            "Principal": {
              "AWS": "arn:aws:iam::414351767826:root"
            },
            "Action": "sts:AssumeRole",
            "Condition": {
              "StringEquals": {
                "sts:ExternalId": "${var.databricks_account_id}"
              }
            }
          },
          {
            "Effect": "Allow",
            "Principal": {
              "AWS": "${aws_iam_role.unity_catalog.arn}"
            },
            "Action": "sts:AssumeRole"
          }
        ]
      }
      EOF

      # Update the trust policy
      export AWS_PAGER=""
      aws iam update-assume-role-policy \
        --role-name ${aws_iam_role.unity_catalog.name} \
        --policy-document file:///tmp/trust_policy_${var.prefix}.json
      
      # Clean up
      rm -f /tmp/trust_policy_${var.prefix}.json
      
      echo "✅ Trust policy updated with self-assuming capability"
    EOT
  }

  depends_on = [time_sleep.wait_for_role]
}

resource "aws_iam_role_policy" "unity_catalog" {
  name = "${var.prefix}-unity-catalog-policy"
  role = aws_iam_role.unity_catalog.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion",
          "s3:PutObject",
          "s3:PutObjectAcl",
          "s3:DeleteObject",
          "s3:ListBucket",
          "s3:GetBucketLocation"
        ]
        Resource = [
          aws_s3_bucket.metastore.arn,
          "${aws_s3_bucket.metastore.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:Encrypt",
          "kms:GenerateDataKey"
        ]
        Resource = [
          var.kms_key_arn
        ]
      },
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.prefix}-unity-catalog-role"
      }
    ]
  })
}

# Bucket policy for Unity Catalog
data "aws_iam_policy_document" "metastore_bucket_policy" {
  statement {
    sid    = "Grant Unity Catalog Access"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:PutObject",
      "s3:PutObjectAcl",
      "s3:DeleteObject",
      "s3:ListBucket",
      "s3:GetBucketLocation"
    ]
    resources = [
      aws_s3_bucket.metastore.arn,
      "${aws_s3_bucket.metastore.arn}/*"
    ]
    principals {
      type = "AWS"
      identifiers = [
        aws_iam_role.unity_catalog.arn
      ]
    }
  }
}

resource "aws_s3_bucket_policy" "metastore" {
  bucket = aws_s3_bucket.metastore.id
  policy = data.aws_iam_policy_document.metastore_bucket_policy.json
}

