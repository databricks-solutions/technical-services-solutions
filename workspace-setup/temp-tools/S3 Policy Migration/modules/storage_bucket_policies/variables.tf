variable "bucket_arns" {
  description = "Map of identifiers to S3 bucket ARNs"
  type        = map(string)
}

# No longer used; retained for backward compatibility.
variable "aws_region" {
  description = "AWS region (ignored)"
  type        = string
  default     = "us-east-1"
}
