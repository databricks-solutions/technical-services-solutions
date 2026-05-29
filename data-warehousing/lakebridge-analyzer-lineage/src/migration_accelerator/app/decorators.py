"""
Decorators for route handlers.

Provides standardized error handling and other cross-cutting concerns.
"""

from functools import wraps
from typing import Callable

from fastapi import HTTPException

from migration_accelerator.app.exceptions import AppException
from migration_accelerator.utils.logger import get_logger

log = get_logger()


def handle_errors(operation_name: str) -> Callable:
    """
    Decorator to standardize error handling in route handlers.
    
    Catches all exceptions and converts them to appropriate HTTP responses:
    - AppException -> 400 with structured error details
    - HTTPException -> pass through unchanged
    - Other exceptions -> 500 with generic error message
    
    Args:
        operation_name: Name of the operation for logging
        
    Returns:
        Decorator function
        
    Example:
        @router.get("/items/{item_id}")
        @handle_errors("get_item")
        async def get_item(item_id: str):
            # Your logic here
            pass
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except HTTPException:
                # Pass through FastAPI HTTPExceptions unchanged
                raise
            except AppException as e:
                # Convert app exceptions to 400 with structured details
                log.error(
                    f"{operation_name} failed: {e.message}",
                    extra={"details": e.details, "code": e.code}
                )
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": e.message,
                        "code": e.code,
                        "details": e.details
                    }
                )
            except Exception as e:
                # Catch-all for unexpected errors
                log.error(
                    f"{operation_name} unexpected error: {e}",
                    exc_info=True
                )
                raise HTTPException(
                    status_code=500,
                    detail={
                        "error": "Internal server error",
                        "code": "INTERNAL_ERROR",
                        "message": str(e)
                    }
                )
        return wrapper
    return decorator




