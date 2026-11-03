# Your own services: a model provider service, a model service that routes to it, and an MCP service.
# Delete this file if you manage only the Databricks-provided system.ai services.
#
# Security: only the Terraform service principal should own these services and hold MANAGE on their
# schema and catalog. Anyone with MANAGE can point the provider service at another URL, and the
# gateway then sends the provider key to that URL.

variable "catalog" {
  description = "Catalog that holds the services. Callers need USE CATALOG on it."
  type        = string
}

variable "schema" {
  description = "Schema that holds the services. Callers need USE SCHEMA on it."
  type        = string
  default     = "ai_services"
}

variable "provider_base_url" {
  description = "Full HTTPS URL of the provider's OpenAI-compatible chat completions endpoint, for example https://api.example.com/v1/chat/completions. Unity Gateway adds no path to it."
  type        = string

  validation {
    condition     = startswith(var.provider_base_url, "https://")
    error_message = "Use an https:// URL: the gateway sends the provider key to it."
  }
}

variable "provider_api_key_secret" {
  description = "Full name <catalog>.<schema>.<secret> of the Unity Catalog secret that holds the provider API key. Create the secret outside Terraform, so that the key is not in the Terraform state or plan. The owner of the provider service (the Terraform service principal) needs READ SECRET on it."
  type        = string
}

variable "ai_users_group" {
  description = "Group that can call the model service and the MCP service."
  type        = string
}

variable "mcp_server_url" {
  description = "HTTPS host of an MCP server that you trust, for example https://mcp.example.com. The server gets the tool calls and their arguments."
  type        = string

  validation {
    condition     = startswith(var.mcp_server_url, "https://")
    error_message = "Use an https:// URL."
  }
}

variable "mcp_server_base_path" {
  description = "Path of the MCP endpoint on the server."
  type        = string
  default     = "/mcp"
}

variable "mcp_bearer_token" {
  description = "Bearer token for the MCP server. Pass it with TF_VAR_mcp_bearer_token. It is stored in the connection and in the Terraform state."
  type        = string
  sensitive   = true
}

variable "mcp_tools" {
  description = "Names or prefix patterns (for example read_*) of the MCP tools to expose. Expose only the tools that you need."
  type        = list(string)

  validation {
    condition     = length(var.mcp_tools) > 0
    error_message = "List the tools to expose: an empty list exposes all tools of the server."
  }
}

locals {
  parent = "schemas/${var.catalog}.${var.schema}"
  prefix = "${var.catalog}.${var.schema}"
}

# Model provider service: it reads the provider key from a Unity Catalog secret at request time.
# Callers never see the key, and Terraform never has it.
resource "databricks_ai_gateway_model_provider_service" "chat_provider" {
  parent                    = local.parent
  model_provider_service_id = "chat_provider"
  comment                   = "Managed by Terraform"
  config = {
    provider_type = "EXTERNAL_MODEL_PROVIDER_TYPE_CUSTOM"
    targets = [{
      model            = "chat-model"
      native_api_types = ["openai/v1/chat/completions"]
    }]
    custom = {
      direct = {
        base_url = var.provider_base_url # full endpoint URL
        api_key  = { secret_reference = { name = "secrets/${var.provider_api_key_secret}" } }
      }
    }
  }
}

# Model service: the stable name that clients call. Routes 100% of traffic to the provider.
resource "databricks_ai_gateway_model_service" "chat" {
  parent           = local.parent
  model_service_id = "chat"
  comment          = "Managed by Terraform"
  config = {
    routing = {
      destinations = [{
        name               = "primary"
        destination_type   = "DESTINATION_TYPE_EXTERNAL_FOUNDATION_MODEL"
        traffic_percentage = 100
        external_model_config = {
          model_provider_service = "model-provider-services/${local.prefix}.${databricks_ai_gateway_model_provider_service.chat_provider.model_provider_service_id}"
          target = {
            model            = "chat-model"
            native_api_types = ["openai/v1/chat/completions"]
          }
        }
      }]
    }
  }
}

# MCP service: a schema-level HTTP connection to the MCP server, then the service on top.
resource "databricks_connection" "docs_mcp" {
  name            = "docs_mcp"
  connection_type = "HTTP"
  parent          = local.parent
  options = {
    host         = var.mcp_server_url
    port         = "443"
    base_path    = var.mcp_server_base_path
    bearer_token = var.mcp_bearer_token
    # Do not set is_mcp_connection: schema-level connections reject it.
    # Do not set auth_scheme: the API rejects it on create, but adds it on read.
  }

  lifecycle {
    ignore_changes = [options["auth_scheme"]] # else every plan shows a change; the other options keep drift detection
  }
}

resource "databricks_ai_gateway_mcp_service" "docs" {
  parent         = local.parent
  mcp_service_id = "docs"
  comment        = "Managed by Terraform"
  config = {
    source_connection = {
      name = "connections/${local.prefix}.${databricks_connection.docs_mcp.name}"
    }
    include_tool_selectors = var.mcp_tools # an empty list would expose all tools
  }
}

# Access: EXECUTE on the model service and the MCP service. Callers also need USE CATALOG and
# USE SCHEMA. Do not grant EXECUTE on the provider service: callers would then skip the model
# service and its rate limits. Do not grant USE CONNECTION: callers would then use the MCP
# token directly, without the MCP service.
resource "databricks_grants" "chat" {
  model_service = "${local.prefix}.${databricks_ai_gateway_model_service.chat.model_service_id}"
  grant {
    principal  = var.ai_users_group
    privileges = ["EXECUTE"]
  }
}

resource "databricks_grants" "docs_mcp" {
  mcp_service = "${local.prefix}.${databricks_ai_gateway_mcp_service.docs.mcp_service_id}"
  grant {
    principal  = var.ai_users_group
    privileges = ["EXECUTE"]
  }
}
