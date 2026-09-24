"""
Environment detection utilities for Migration Accelerator
"""

import os
from pathlib import Path

from migration_accelerator.exceptions import MigrationAcceleratorEnvironmentException


def is_databricks_environment() -> bool:
    """
    Detect if we're running in a Databricks environment.

    Returns:
        bool: True if running on Databricks, False otherwise
    """
    # Check for Databricks-specific environment variables
    databricks_indicators = [
        "DATABRICKS_RUNTIME_VERSION",
        "DATABRICKS_WORKSPACE_URL",
        "SPARK_HOME",
    ]

    for indicator in databricks_indicators:
        if os.environ.get(indicator):
            return True

    # Check for Databricks file system structure
    if Path("/databricks").exists():
        return True

    # Check if current working directory is in workspace
    cwd = Path.cwd()
    if "/Workspace/" in str(cwd):
        return True

    return False


def get_databricks_user() -> str | None:
    """
    Get the current Databricks user.

    Returns:
        Optional[str]: The Databricks user email/name if available
    """
    try:
        from databricks.sdk import WorkspaceClient

        w = WorkspaceClient()
        me = w.current_user.me()
        return me.user_name
    except Exception as e:
        raise MigrationAcceleratorEnvironmentException(
            f"Could not determine Databricks user: {e}"
        )


def get_migration_accelerator_base_directory() -> Path:
    """
    Get the base directory for Migration Accelerator files based on environment.

    For local environments: ~/.migration_accelerator/
    For Databricks: /Workspace/Users/{user}/.migration_accelerator/

    Returns:
        Path: The base directory path
    """
    if is_databricks_environment():
        try:
            user = get_databricks_user()
        except Exception:
            user = None
        if user:
            base_dir = Path(f"/Workspace/Users/{user}/.migration_accelerator")
            return base_dir
        else:
            # Fallback to /tmp if user cannot be determined
            base_dir = Path("/tmp/.migration_accelerator")
            return base_dir
    else:
        base_dir = Path.home() / ".migration_accelerator"
        return base_dir


def get_config_directory() -> Path:
    """
    Get the configuration directory based on environment.

    Returns:
        Path: The configuration directory path
    """
    return get_migration_accelerator_base_directory()


def get_log_directory() -> Path:
    """
    Get the log directory based on environment.

    Returns:
        Path: The log directory path
    """
    return get_migration_accelerator_base_directory()
