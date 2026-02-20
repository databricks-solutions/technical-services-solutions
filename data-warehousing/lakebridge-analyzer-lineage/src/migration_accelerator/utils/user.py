"""User service for Databricks user operations."""

import os

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.iam import User


def get_ws_client() -> WorkspaceClient:
    """Get the workspace client."""
    return WorkspaceClient(
        client_id=os.environ.get("DATABRICKS_CLIENT_ID"),
        client_secret=os.environ.get("DATABRICKS_CLIENT_SECRET"),
    )


class UserService:
    """Service for managing Databricks user operations."""

    def __init__(self) -> None:
        """Initialize the user service with Databricks workspace client."""
        self.client = get_ws_client()

    def get_current_user(self) -> User:
        """Get the current authenticated user."""
        return self.client.current_user.me()  # type: ignore[no-any-return]

    def get_user_info(self) -> dict:
        """Get formatted user information."""
        user = self.get_current_user()
        return {
            "userName": user.user_name or "unknown",
            "displayName": user.display_name,
            "active": user.active or False,
            "emails": [email.value for email in (user.emails or [])],
            "groups": [group.display for group in (user.groups or [])],
        }

    def get_user_workspace_info(self) -> dict:
        """Get user workspace information."""
        user = self.get_current_user()

        # Get workspace URL from the client
        workspace_url = self.client.config.host

        return {
            "user": {
                "userName": user.user_name or "unknown",
                "displayName": user.display_name,
                "active": user.active or False,
            },
            "workspace": {
                "url": workspace_url,
                "deployment_name": (
                    workspace_url.split("//")[1].split(".")[0]
                    if workspace_url
                    else None
                ),
            },
        }
