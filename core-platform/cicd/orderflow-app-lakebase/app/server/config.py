"""Environment detection + workspace client (dual-mode: local CLI vs Databricks App)."""
import os
from databricks.sdk import WorkspaceClient

IS_DATABRICKS_APP = bool(os.environ.get("DATABRICKS_APP_NAME"))


def get_workspace_client() -> WorkspaceClient:
    if IS_DATABRICKS_APP:
        # Auto-injected service principal credentials.
        return WorkspaceClient()
    profile = os.environ.get("DATABRICKS_PROFILE", "DEFAULT")
    return WorkspaceClient(profile=profile)
