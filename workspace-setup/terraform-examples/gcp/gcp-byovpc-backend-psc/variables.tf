######################################################
# Authentication / Project
######################################################
variable "google_service_account_email" {
  description = "Email of the Google Service Account used by the providers (must be an account admin in Databricks and hold the customer-managed VPC role requirements)."
  type        = string
}

variable "google_project_name" {
  description = "GCP project ID where the Databricks workspace data plane (GCE) will be created (service / consumer project)."
  type        = string
}

variable "google_region" {
  description = "GCP region for all resources (e.g., us-central1). Backend PSC requires every component to be in the same region."
  type        = string
}

######################################################
# Existing (BYO) Network
######################################################
variable "vpc_network_project_id" {
  description = "GCP project ID where the existing VPC resides (host project). Set equal to google_project_name if the VPC is in the same project as the workspace."
  type        = string
}

variable "vpc_name" {
  description = "Name of the existing VPC network to attach the workspace to."
  type        = string
}

variable "subnet_name" {
  description = "Name of the existing subnet used by the Databricks GCE nodes (the workspace 'node' subnet)."
  type        = string
}

variable "psc_subnet_name" {
  description = "Name of the existing subnet in which the two backend PSC endpoint IP addresses are allocated. May be the same as subnet_name."
  type        = string
}

######################################################
# Databricks Account / Workspace
######################################################
variable "databricks_account_id" {
  description = "Databricks Account ID."
  type        = string
}

variable "databricks_workspace_name" {
  description = "Name for the Databricks workspace."
  type        = string
}

variable "databricks_admin_user" {
  description = "Admin user email to add to the workspace (must exist at the Databricks Account level)."
  type        = string
}

variable "metastore_id" {
  description = "Existing Unity Catalog metastore ID. If empty, no metastore assignment is made (Databricks auto-creates one for the first workspace in a region). If provided, the existing metastore is assigned to the workspace."
  type        = string
  default     = ""
}

######################################################
# Backend Private Service Connect
######################################################
variable "workspace_service_attachment" {
  description = "Region-specific Databricks PSC service attachment URI for the workspace / control plane REST API (plproxy-psc-endpoint-all-ports). See the region table in the README."
  type        = string
}

variable "relay_service_attachment" {
  description = "Region-specific Databricks PSC service attachment URI for the secure cluster connectivity (SCC) relay (ngrok-psc-endpoint). See the region table in the README."
  type        = string
}

variable "workspace_pe_name" {
  description = "Name for the backend REST API PSC endpoint (forwarding rule) that targets the workspace service attachment."
  type        = string
  default     = "dbx-backend-rest-ep"
}

variable "relay_pe_name" {
  description = "Name for the backend SCC relay PSC endpoint (forwarding rule) that targets the relay service attachment."
  type        = string
  default     = "dbx-backend-relay-ep"
}

variable "public_access_enabled" {
  description = "Whether the workspace remains reachable from the public internet. For a backend-only PSC deployment this is typically true (front-end/user access is not restricted by PSC here). Cannot be changed after the private access settings object is created."
  type        = bool
  default     = true
}

######################################################
# Private DNS
######################################################
variable "create_private_dns" {
  description = "Whether to create a private Cloud DNS zone and the A records that point the classic compute plane at the PSC endpoint IPs. Set to false if you manage DNS elsewhere."
  type        = bool
  default     = true
}

variable "private_zone_name" {
  description = "Name of the private Cloud DNS managed zone to create for gcp.databricks.com."
  type        = string
  default     = "databricks-psc"
}

variable "dns_name" {
  description = "DNS name for the private managed zone. Must be 'gcp.databricks.com.' (trailing dot required)."
  type        = string
  default     = "gcp.databricks.com."
}
