"""
Standardized exit codes for Databricks Terraform Pre-Check.

Exit codes follow common conventions:
- 0: Success
- 1: General error
- 2-10: Specific operational errors

This allows CI/CD pipelines to distinguish between different failure modes.
"""

from enum import IntEnum


class ExitCode(IntEnum):
    """Standardized exit codes for the CLI."""
    
    # Success
    SUCCESS = 0
    
    # Permission/Authorization issues (most common)
    PERMISSION_DENIED = 2
    
    # Configuration issues
    CONFIG_INVALID = 3
    
    # Runtime/Provider errors
    PROVIDER_ERROR = 4
    
    # Authentication failures
    AUTH_FAILED = 5
    
    # Quota exceeded
    QUOTA_EXCEEDED = 6
    
    # General/Unknown error
    GENERAL_ERROR = 1


# Human-readable descriptions
EXIT_CODE_DESCRIPTIONS = {
    ExitCode.SUCCESS: "All checks passed successfully",
    ExitCode.PERMISSION_DENIED: "Missing required permissions",
    ExitCode.CONFIG_INVALID: "Invalid configuration file",
    ExitCode.PROVIDER_ERROR: "Cloud provider API error",
    ExitCode.AUTH_FAILED: "Authentication failed",
    ExitCode.QUOTA_EXCEEDED: "Quota limit would be exceeded",
    ExitCode.GENERAL_ERROR: "General error occurred",
}


def get_exit_code_description(code: ExitCode) -> str:
    """Get human-readable description for an exit code."""
    return EXIT_CODE_DESCRIPTIONS.get(code, "Unknown exit code")

