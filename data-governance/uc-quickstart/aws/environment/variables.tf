variable "aws_account_id" {
  type        = string
  description = "AWS account ID"
}

variable "catalogs" {
    type = map(object({
        name = string
        bucket_name = string
        owner = string
        permissions = list(object({
            principal = string
            privileges = list(string)
        }))
    }))
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to the storage resources"
  default     = {}
}
