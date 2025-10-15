variable "project" { type = string }
variable "region" { type = string }
variable "vpc_cidr" { type = string }
variable "private_subnet_cidrs" { type = list(string) }
variable "pl_service_names" {
  type = object({
    workspace = string
    scc       = string
  })
}
variable "enable_extra_endpoints" {
  type    = bool
  default = false
}
