# Who can use which system.ai model service.
#
# New setup: edit this file by hand.
# Existing setup: generate it from a snapshot of today's grants, so the first apply changes nothing:
#   python3 scripts/gen_grants_config.py --snapshot snapshot/grants.json --out grants/access.tf
#
# List EVERY model service in system.ai, with a fixed list. Do not build it from the
# databricks_ai_gateway_model_services data source: the list API can return an empty result,
# and an empty map makes Terraform revoke every grant.
# A model with {} gets only the break-glass group (databricks_grants needs at least one grant).
locals {
  # account users keep these on the schema. Never add EXECUTE: every model inherits it.
  account_users_schema_privileges = ["READ_VOLUME", "SELECT", "USE_SCHEMA"]

  model_grants = {
    "claude-haiku-4-5" = {
      "data-scientists" = ["EXECUTE"]
      "ml-engineers"    = ["EXECUTE"]
    }
    "claude-sonnet-4-6" = {
      "data-scientists" = ["EXECUTE"]
      "ml-engineers"    = ["EXECUTE"]
    }
    "claude-opus-4-7" = {
      "genai-power-users" = ["EXECUTE"]
    }
    "gemma-3-12b"      = {} # locked
    "gpt-oss-120b"     = {} # locked
    "llama-4-maverick" = {} # locked
  }
}
