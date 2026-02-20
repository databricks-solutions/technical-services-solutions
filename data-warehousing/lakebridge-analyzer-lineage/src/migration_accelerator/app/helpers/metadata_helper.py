"""
Centralized metadata operations helper.

Eliminates duplicate metadata retrieval and dialect extraction patterns.
"""

from pathlib import Path
from typing import Any, Dict, Tuple

from migration_accelerator.app.constants import Dialect
from migration_accelerator.app.exceptions import AnalyzerNotFoundException
from migration_accelerator.app.services.storage_service import StorageService


class MetadataHelper:
    """
    Utility class for consistent metadata operations.
    
    Provides static methods for common metadata operations to eliminate
    duplication across route handlers and services.
    """
    
    @staticmethod
    def get_file_with_metadata(
        file_id: str,
        user_id: str,
        storage: StorageService
    ) -> Tuple[Path, Dict[str, Any]]:
        """
        Get file path and metadata together with fallback handling.
        
        Args:
            file_id: File identifier
            user_id: User identifier
            storage: Storage service instance
            
        Returns:
            Tuple of (file_path, metadata_dict)
            
        Raises:
            AnalyzerNotFoundException: If file not found
            
        Example:
            file_path, metadata = MetadataHelper.get_file_with_metadata(
                "file-123", "user-456", storage_service
            )
        """
        file_path = storage.get_file_path(file_id, user_id)
        if not file_path:
            raise AnalyzerNotFoundException(file_id)
        
        metadata = storage.get_file_metadata(file_id, user_id)
        if not metadata:
            # Create minimal metadata from file info for backwards compatibility
            # Use storage service method instead of Path operations
            file_size = storage.get_file_size(file_id, user_id)
            metadata = {
                "file_id": file_id,
                "dialect": Dialect.TALEND.value,  # Default fallback
                "filename": file_path.name,
                "lineages": [],
                "file_size": file_size,
            }
        
        return file_path, metadata
    
    @staticmethod
    def get_dialect(metadata: Dict[str, Any]) -> Dialect:
        """
        Extract dialect from metadata with fallback.
        
        Args:
            metadata: Metadata dictionary
            
        Returns:
            Dialect enum value
            
        Example:
            dialect = MetadataHelper.get_dialect(metadata)
            # Returns Dialect.SQL, Dialect.TALEND, etc.
        """
        dialect_str = metadata.get("dialect", "talend")
        try:
            return Dialect(dialect_str)
        except ValueError:
            # Invalid dialect string, return default
            return Dialect.TALEND
    
    @staticmethod
    def get_dialect_str(metadata: Dict[str, Any]) -> str:
        """
        Get dialect as string from metadata with fallback.
        
        Args:
            metadata: Metadata dictionary
            
        Returns:
            Dialect string value
        """
        return MetadataHelper.get_dialect(metadata).value




