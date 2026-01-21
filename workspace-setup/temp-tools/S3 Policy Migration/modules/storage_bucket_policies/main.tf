locals {
  bucket_name_map = {
    for name, arn in var.bucket_arns :
    name => (startswith(arn, "arn:aws:s3:::") ? replace(arn, "arn:aws:s3:::", "") : arn)
  }
}

data "aws_s3_bucket_policy" "this" {
  for_each = local.bucket_name_map

  bucket = each.value
}
