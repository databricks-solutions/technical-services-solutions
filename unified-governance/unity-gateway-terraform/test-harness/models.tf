# Fixed list of system.ai model services (captured 2026-10-13). Add new models here on purpose.
locals {
  models = [
    "system.ai.claude-haiku-4-5",
    "system.ai.claude-haiku-5-5",
    "system.ai.claude-opus-4-5",
    "system.ai.claude-opus-4-6",
    "system.ai.claude-opus-4-7",
    "system.ai.claude-opus-4-8",
    "system.ai.claude-opus-5",
    "system.ai.claude-opus-5-5",
    "system.ai.claude-sonnet-4-5",
    "system.ai.claude-sonnet-4-6",
    "system.ai.claude-sonnet-5",
    "system.ai.claude-sonnet-5-5",
    "system.ai.gemma-3-12b",
    "system.ai.gpt-oss-120b",
    "system.ai.gpt-oss-20b",
    "system.ai.gte-large-en",
    "system.ai.llama-4-maverick",
    "system.ai.meta-llama-3-1-8b-instruct",
    "system.ai.meta-llama-3-3-70b-instruct",
    "system.ai.qwen3-embedding-0-6b",
    "system.ai.qwen35-122b-a10b",
  ]
}
