locals {
  bucket_name_map = {
    for name, arn in var.bucket_arns :
    name => (startswith(arn, "arn:aws:s3:::") ? replace(arn, "arn:aws:s3:::", "") : arn)
  }
}

locals {
  # We intentionally skip fetching bucket policies to avoid plan/apply failures
  # when a bucket has no policy. This returns an empty map instead of erroring.
  bucket_policies = {}
}
