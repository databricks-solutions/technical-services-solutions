"""
Custom exceptions with structured error codes.

Provides application-specific exceptions with error codes and details
for better error handling and API responses.
"""

from typing import Any, Dict, Optional


class AppException(Exception):
    """
    Base exception with error codes and details.
    
    All application-specific exceptions should inherit from this.
    """
    
    def __init__(self, message: str, code: str, details: Optional[Dict[str, Any]] = None):
        """
        Initialize exception.
        
        Args:
            message: Human-readable error message
            code: Error code for programmatic handling
            details: Additional context about the error
        """
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(message)


class AnalyzerNotFoundException(AppException):
    """Raised when an analyzer file is not found."""
    
    def __init__(self, analyzer_id: str):
        super().__init__(
            message=f"Analyzer {analyzer_id} not found",
            code="ANALYZER_NOT_FOUND",
            details={"analyzer_id": analyzer_id}
        )


class LineageNotFoundException(AppException):
    """Raised when a lineage is not found."""
    
    def __init__(self, lineage_id: str):
        super().__init__(
            message=f"Lineage {lineage_id} not found",
            code="LINEAGE_NOT_FOUND",
            details={"lineage_id": lineage_id}
        )


class DialectDetectionException(AppException):
    """Raised when dialect auto-detection fails."""
    
    def __init__(self, file_path: str):
        super().__init__(
            message="Could not auto-detect dialect. Please specify manually.",
            code="DIALECT_DETECTION_FAILED",
            details={"file_path": file_path}
        )


class InvalidFileFormatException(AppException):
    """Raised when an uploaded file has an invalid format."""
    
    def __init__(self, filename: str, allowed_formats: list):
        super().__init__(
            message=f"Invalid file format for {filename}",
            code="INVALID_FILE_FORMAT",
            details={"filename": filename, "allowed": allowed_formats}
        )


class FileAccessDeniedException(AppException):
    """Raised when user doesn't have access to a file."""
    
    def __init__(self, file_id: str, user_id: str):
        super().__init__(
            message=f"Access denied to file {file_id}",
            code="FILE_ACCESS_DENIED",
            details={"file_id": file_id, "user_id": user_id}
        )




