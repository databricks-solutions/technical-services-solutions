locals {
  parent = "schemas/${var.catalog}.${var.schema}"
  prefix = "${var.catalog}.${var.schema}"
}

# Model provider service: stores the provider credential. Callers never see it.
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
        api_key  = { plaintext = var.provider_api_key }
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
    host         = "https://mcp.deepwiki.com" # example: a public MCP server without auth
    port         = "443"
    base_path    = "/mcp"
    bearer_token = "unused"
    auth_scheme  = "bearer" # set it: the API adds it, and without it every plan shows a diff
    # Do not set is_mcp_connection: schema-level connections reject it.
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
  }
}

# Access: EXECUTE on each service. Callers also need USE CATALOG and USE SCHEMA.
# End users do not need USE CONNECTION on the MCP connection.
resource "databricks_grants" "chat_provider" {
  model_provider_service = "${local.prefix}.${databricks_ai_gateway_model_provider_service.chat_provider.model_provider_service_id}"
  grant {
    principal  = var.ai_users_group
    privileges = ["EXECUTE"]
  }
}

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
