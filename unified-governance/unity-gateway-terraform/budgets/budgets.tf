# AI Gateway budgets. For budgets that exist today, import them instead of creating new ones
# (see the README), so that nobody gets two budgets that both block usage.

variable "budget_alert_email" {
  type    = string
  default = "platform-team@example.com"
}

# Account-level group that gets a higher per-user limit.
data "databricks_group" "genai_power_users" {
  display_name = "genai-power-users"
}

# 1. Shared monthly budget for all spend through Unity Gateway. Email only.
resource "databricks_budget" "ai_gateway_shared" {
  display_name  = "ai-gateway-monthly-shared"
  resource_type = "BUDGET_RESOURCE_TYPE_UNITY_AI_GATEWAY"

  alert_configurations {
    time_period        = "MONTH"
    trigger_type       = "CUMULATIVE_SPENDING_EXCEEDED"
    quantity_type      = "LIST_PRICE_DOLLARS_USD"
    quantity_threshold = "5000"
    scope_type         = "ALERT_CONFIGURATION_SCOPE_TYPE_SHARED"

    action_configurations {
      action_type = "EMAIL_NOTIFICATION"
      target      = var.budget_alert_email
    }
  }
}

# 2. Per-user monthly cap: each user is blocked at $100 list price per month,
#    except members of genai-power-users, who are blocked at $300.
resource "databricks_budget" "ai_gateway_per_user" {
  display_name  = "ai-gateway-monthly-per-user"
  resource_type = "BUDGET_RESOURCE_TYPE_UNITY_AI_GATEWAY"

  alert_configurations {
    time_period        = "MONTH"
    trigger_type       = "CUMULATIVE_SPENDING_EXCEEDED"
    quantity_type      = "LIST_PRICE_DOLLARS_USD"
    quantity_threshold = "100"
    scope_type         = "ALERT_CONFIGURATION_SCOPE_TYPE_PER_USER"

    principal_overrides {
      principal_id       = data.databricks_group.genai_power_users.id
      override_threshold = "300.00" # two decimals, as the API returns it: "300" shows a diff on every plan
    }

    action_configurations {
      action_type = "BLOCK_USAGE"
    }
  }
}
