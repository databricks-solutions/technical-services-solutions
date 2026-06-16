"""
Shared configuration constants and client factories for the PBI-to-AIBI converter.

Provides authenticated clients for:
  - Databricks workspace operations (via service principal in the app environment)
  - LLM inference via Databricks Model Serving (OpenAI-compatible)
"""

import os
from pathlib import Path

from openai import OpenAI
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config

MODEL = os.getenv("LLM_MODEL", "databricks-claude-opus-4-6")
# Max output tokens per completion. Some serving endpoints (e.g. Qwen) cap this
# at 8192 and reject larger requests with HTTP 400. Override via env if the
# configured model supports a higher ceiling.
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "8192"))
KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"
STATIC_DIR = Path(__file__).parent / "static"
GRID_COLUMNS = 6

VALID_WIDGET_VERSIONS = {
    "counter": 2,
    "table": 2,
    "filter-multi-select": 2,
    "filter-single-select": 2,
    "filter-date-range-picker": 2,
    "bar": 3,
    "line": 3,
    "pie": 3,
    "area": 3,
    "pivot": 3,
    "scatter": 3,
}


def get_workspace_client() -> WorkspaceClient:
    """Return a WorkspaceClient.

    Inside a Databricks App, this picks up the app's service principal
    automatically from injected env vars. Locally it falls back to
    whatever the default Databricks SDK auth chain resolves to (PAT,
    profile, etc.).
    """
    return WorkspaceClient()


def get_llm_client() -> OpenAI:
    """Return an OpenAI-compatible client pointed at the Databricks Model Serving endpoint."""
    cfg = Config()
    host = cfg.host.rstrip("/")
    token = os.getenv("DATABRICKS_TOKEN") or cfg.authenticate().get("Authorization", "").replace("Bearer ", "")

    if not token:
        cfg_obj = cfg.authenticate()
        if isinstance(cfg_obj, dict):
            token = cfg_obj.get("Authorization", "").replace("Bearer ", "")
        else:
            token = cfg_obj

    return OpenAI(
        base_url=f"{host}/serving-endpoints",
        api_key=token,
    )
