"""
Error handling utilities for Databricks Terraform Pre-Check.

Provides common error handling patterns to reduce code duplication.
"""

from typing import Callable, Any, Optional, Tuple
from functools import wraps

from checkers.base import CheckResult, CheckStatus


class CloudAuthError(Exception):
    """Exception raised for cloud authentication failures."""
    pass


class PermissionDeniedError(Exception):
    """Exception raised when a permission is denied."""
    pass


class QuotaExceededError(Exception):
    """Exception raised when a quota is exceeded."""
    pass


class ResourceNotFoundError(Exception):
    """Exception raised when a resource is not found."""
    pass


def parse_aws_error(error: Exception) -> Tuple[str, str]:
    """
    Parse an AWS error and return (error_type, message).
    
    Returns:
        Tuple of (error_type, user_friendly_message)
    """
    error_str = str(error)
    
    if "InvalidClientTokenId" in error_str:
        return ("auth", "Invalid AWS Access Key ID")
    
    if "SignatureDoesNotMatch" in error_str:
        return ("auth", "Invalid AWS Secret Access Key")
    
    if "ExpiredToken" in error_str:
        return ("auth", "AWS session token has expired")
    
    if "AccessDenied" in error_str or "UnauthorizedOperation" in error_str:
        return ("permission", "Access denied - missing IAM permission")
    
    if "DryRunOperation" in error_str:
        return ("success", "Permission verified (dry-run)")
    
    if "LimitExceededException" in error_str:
        return ("quota", "Service limit exceeded")
    
    if "ResourceNotFoundException" in error_str:
        return ("not_found", "Resource not found")
    
    return ("unknown", error_str[:100])


def parse_azure_error(error: Exception) -> Tuple[str, str]:
    """
    Parse an Azure error and return (error_type, message).
    
    Returns:
        Tuple of (error_type, user_friendly_message)
    """
    error_str = str(error)
    
    if "AADSTS" in error_str:
        return ("auth", "Azure AD authentication failed - run: az login")
    
    if "EnvironmentCredential" in error_str or "DefaultAzureCredential" in error_str:
        return ("auth", "No Azure credentials found - run: az login")
    
    if "Invalid client secret" in error_str:
        return ("auth", "Invalid client secret")
    
    if "AuthorizationFailed" in error_str:
        return ("permission", "Authorization failed - missing RBAC permission")
    
    if "does not have authorization" in error_str:
        return ("permission", "Missing RBAC permission")
    
    if "ResourceNotFound" in error_str:
        return ("not_found", "Resource not found")
    
    if "QuotaExceeded" in error_str or "MaxStorageAccountsCountPerSubscriptionExceeded" in error_str:
        return ("quota", "Quota exceeded")
    
    if "ResourceProviderNotRegistered" in error_str:
        return ("config", "Resource provider not registered")
    
    return ("unknown", error_str[:100])


def parse_gcp_error(error: Exception) -> Tuple[str, str]:
    """
    Parse a GCP error and return (error_type, message).
    
    Returns:
        Tuple of (error_type, user_friendly_message)
    """
    error_str = str(error)
    
    if "Could not automatically determine credentials" in error_str:
        return ("auth", "No GCP credentials - run: gcloud auth application-default login")
    
    if "invalid_grant" in error_str or "Token has been expired" in error_str:
        return ("auth", "GCP credentials expired - run: gcloud auth application-default login")
    
    if "Permission" in error_str and "denied" in error_str.lower():
        return ("permission", "Permission denied")
    
    if "Quota" in error_str:
        return ("quota", "Quota exceeded")
    
    if "not found" in error_str.lower():
        return ("not_found", "Resource not found")
    
    if "API" in error_str and "not enabled" in error_str:
        return ("config", "Required API not enabled")
    
    return ("unknown", error_str[:100])


def handle_cloud_error(
    cloud: str,
    error: Exception,
    action_name: str,
    success_on_dryrun: bool = True
) -> CheckResult:
    """
    Handle a cloud API error and return a CheckResult.
    
    Args:
        cloud: Cloud provider ('aws', 'azure', 'gcp')
        error: The exception that was raised
        action_name: Name of the action being tested
        success_on_dryrun: For AWS, treat DryRunOperation as success
    
    Returns:
        CheckResult with appropriate status and message
    """
    parsers = {
        'aws': parse_aws_error,
        'azure': parse_azure_error,
        'gcp': parse_gcp_error,
    }
    
    parser = parsers.get(cloud, lambda e: ("unknown", str(e)[:100]))
    error_type, message = parser(error)
    
    if error_type == "success":
        return CheckResult(
            name=action_name,
            status=CheckStatus.OK,
            message=message
        )
    
    if error_type == "auth":
        return CheckResult(
            name=action_name,
            status=CheckStatus.NOT_OK,
            message=f"AUTH ERROR: {message}"
        )
    
    if error_type == "permission":
        return CheckResult(
            name=action_name,
            status=CheckStatus.NOT_OK,
            message=f"DENIED: {message}"
        )
    
    if error_type == "quota":
        return CheckResult(
            name=action_name,
            status=CheckStatus.WARNING,
            message=f"QUOTA: {message}"
        )
    
    if error_type == "not_found":
        return CheckResult(
            name=action_name,
            status=CheckStatus.WARNING,
            message=f"NOT FOUND: {message}"
        )
    
    if error_type == "config":
        return CheckResult(
            name=action_name,
            status=CheckStatus.WARNING,
            message=f"CONFIG: {message}"
        )
    
    return CheckResult(
        name=action_name,
        status=CheckStatus.WARNING,
        message=f"Error: {message}"
    )


def safe_api_call(
    cloud: str,
    action_name: str,
    func: Callable,
    *args,
    success_message: str = "OK",
    **kwargs
) -> CheckResult:
    """
    Safely execute an API call and return a CheckResult.
    
    Args:
        cloud: Cloud provider
        action_name: Name of the action for the result
        func: Function to call
        *args: Positional arguments for the function
        success_message: Message to use on success
        **kwargs: Keyword arguments for the function
    
    Returns:
        CheckResult with appropriate status
    """
    try:
        result = func(*args, **kwargs)
        return CheckResult(
            name=action_name,
            status=CheckStatus.OK,
            message=success_message
        )
    except Exception as e:
        return handle_cloud_error(cloud, e, action_name)


def with_error_handling(cloud: str, action_name: str):
    """
    Decorator for methods that make cloud API calls.
    
    Usage:
        @with_error_handling('aws', 'iam:CreateRole')
        def create_role(self):
            # API call here
            pass
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                return handle_cloud_error(cloud, e, action_name)
        return wrapper
    return decorator

