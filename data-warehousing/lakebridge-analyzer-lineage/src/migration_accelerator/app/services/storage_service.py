"""
Storage service for handling file uploads and persistence.

Supports both Unity Catalog (via Databricks SDK) and in-memory (local filesystem) backends.
"""

import io
import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import UploadFile

from migration_accelerator.app.config import StorageBackend, get_storage_path
from migration_accelerator.app import config
from migration_accelerator.utils.logger import get_logger

log = get_logger()


class StorageService:
    """Service for managing file storage with Unity Catalog and in-memory support."""

    def __init__(self):
        """Initialize storage service."""
        self.storage_backend = config.settings.storage_backend
        self.base_path = get_storage_path()
        self.databricks_client = None
        
        # Initialize based on storage backend
        if self.storage_backend == StorageBackend.UNITY_CATALOG:
            self._init_databricks_client()
        else:
            self._ensure_local_path()

    def _init_databricks_client(self) -> None:
        """Initialize Databricks client for Unity Catalog operations using service principal."""
        try:
            from databricks.sdk import WorkspaceClient
            
            # Use service principal credentials from environment
            # This will use DATABRICKS_HOST, DATABRICKS_CLIENT_ID, DATABRICKS_CLIENT_SECRET, etc.
            self.databricks_client = WorkspaceClient()
            
            # Verify UC volume path is accessible
            self._verify_uc_volume_access()
            log.info(f"Databricks client initialized with service principal for UC volume: {self.base_path}")
        except Exception as e:
            log.error(f"Failed to initialize Databricks client: {e}")
            raise ValueError(
                f"Cannot initialize Unity Catalog storage. "
                f"Ensure service principal credentials are properly configured. "
                f"Error: {e}"
            )

    def _verify_uc_volume_access(self) -> None:
        """Verify Unity Catalog volume path exists and is accessible."""
        try:
            # Try to list files in the base path to verify access
            # This validates permissions without creating anything
            try:
                list(self.databricks_client.files.list_directory_contents(self.base_path))
                log.info(f"Verified access to UC volume: {self.base_path}")
            except Exception:
                # Path might not exist yet - try to create it
                self.databricks_client.files.create_directory(self.base_path)
                log.info(f"Created UC volume directory: {self.base_path}")
        except Exception as e:
            log.error(f"Cannot access UC volume path {self.base_path}: {e}")
            raise ValueError(
                f"Unity Catalog volume path {self.base_path} is not accessible. "
                f"Verify the path exists in Unity Catalog and you have proper permissions. "
                f"Error: {e}"
            )

    def _ensure_local_path(self) -> None:
        """Ensure base storage path exists for in-memory backend."""
        try:
            Path(self.base_path).mkdir(parents=True, exist_ok=True)
            log.info(f"Local storage path ready: {self.base_path}")
        except Exception as e:
            log.warning(f"Could not create local path {self.base_path}: {e}")

    def _validate_user_path(self, user_id: str, operation: str = "access") -> None:
        """
        Validate user path to prevent security issues.
        
        Args:
            user_id: User identifier to validate
            operation: Operation being performed (for logging)
        
        Raises:
            ValueError: If user_id contains invalid characters or path traversal attempts
        """
        # Prevent path traversal attacks
        if ".." in user_id or "/" in user_id or "\\" in user_id:
            log.error(f"Path traversal attempt detected in user_id: {user_id}")
            raise ValueError(f"Invalid user_id: contains illegal path characters")
        
        # Validate user_id is not empty
        if not user_id or user_id.strip() == "":
            log.error(f"Empty user_id provided for operation: {operation}")
            raise ValueError("user_id cannot be empty")
        
        # Log access attempt for audit trail
        log.info(f"User path validated for {operation}: user={user_id}")

    async def save_uploaded_file(
        self, file: UploadFile, user_id: str, dialect: str
    ) -> dict:
        """
        Save uploaded file to storage.

        Args:
            file: Uploaded file
            user_id: User identifier
            dialect: Analyzer dialect

        Returns:
            Dictionary with file information
        """
        # Validate user path for security
        self._validate_user_path(user_id, "save_file")
        
        # Generate unique file ID
        file_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()

        # Read file content
        content = await file.read()
        file_size = len(content)

        # Construct paths
        if self.storage_backend == StorageBackend.UNITY_CATALOG:
            user_path = f"{self.base_path}/{user_id}"
            file_path = f"{user_path}/{file_id}/{file.filename}"
            metadata_path = f"{user_path}/{file_id}/metadata.json"
        else:
            user_path = Path(self.base_path) / user_id
            file_path = user_path / file_id / file.filename
            metadata_path = file_path.parent / "metadata.json"

        try:
            # Save file based on backend
            if self.storage_backend == StorageBackend.UNITY_CATALOG:
                await self._save_file_uc(file_path, content)
            else:
                await self._save_file_local(file_path, content)

            log.info(f"Saved file {file.filename} ({file_size} bytes) to {file_path}")

            # Save metadata
            metadata = {
                "file_id": file_id,
                "filename": file.filename,
                "dialect": dialect,
                "file_size": file_size,
                "user_id": user_id,
                "created_at": timestamp,
                "lineages": [],
            }
            
            if self.storage_backend == StorageBackend.UNITY_CATALOG:
                await self._save_metadata_uc(metadata_path, metadata)
            else:
                await self._save_metadata_local(metadata_path, metadata)

            return {
                "file_id": file_id,
                "filename": file.filename,
                "file_path": str(file_path),
                "file_size": file_size,
                "user_id": user_id,
                "dialect": dialect,
                "created_at": timestamp,
            }

        except Exception as e:
            log.error(f"Failed to save file: {e}")
            raise

    async def _save_file_uc(self, file_path: str, content: bytes) -> None:
        """Save file to Unity Catalog using Databricks SDK."""
        # Ensure parent directory exists
        parent_dir = "/".join(file_path.rsplit("/", 1)[:-1])
        try:
            self.databricks_client.files.create_directory(parent_dir)
        except Exception:
            pass  # Directory might already exist

        # Upload file to UC (SDK expects file-like object)
        file_obj = io.BytesIO(content)
        self.databricks_client.files.upload(file_path, file_obj, overwrite=True)

    async def _save_file_local(self, file_path: Path, content: bytes) -> None:
        """Save file to local filesystem."""
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(content)

    async def _save_metadata_uc(self, metadata_path: str, metadata: dict) -> None:
        """Save metadata to Unity Catalog."""
        metadata_content = json.dumps(metadata, indent=2).encode()
        try:
            # Wrap bytes in BytesIO for SDK
            metadata_obj = io.BytesIO(metadata_content)
            self.databricks_client.files.upload(metadata_path, metadata_obj, overwrite=True)
            log.info(f"Saved metadata to {metadata_path}")
        except Exception as e:
            log.warning(f"Failed to save metadata: {e}")

    async def _save_metadata_local(self, metadata_path: Path, metadata: dict) -> None:
        """Save metadata to local filesystem."""
        try:
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)
            log.info(f"Saved metadata to {metadata_path}")
        except Exception as e:
            log.warning(f"Failed to save metadata: {e}")

    def get_file_path(self, file_id: str, user_id: str) -> Optional[Path]:
        """
        Get file path for a given file ID.

        Args:
            file_id: File identifier
            user_id: User identifier

        Returns:
            Path object or None if not found
        """
        if self.storage_backend == StorageBackend.UNITY_CATALOG:
            return self._get_file_path_uc(file_id, user_id)
        else:
            return self._get_file_path_local(file_id, user_id)

    def _get_file_path_uc(self, file_id: str, user_id: str) -> Optional[Path]:
        """Get file path from Unity Catalog."""
        # Validate user path for security
        self._validate_user_path(user_id, "get_file_path")
        
        user_path = f"{self.base_path}/{user_id}/{file_id}"
        
        try:
            # List files in the directory
            files = list(self.databricks_client.files.list_directory_contents(user_path))
            # Find the first non-metadata file
            for file_info in files:
                if not file_info.path.endswith("metadata.json"):
                    # Return as Path for compatibility with existing code
                    # The actual file reading will be done with SDK
                    return Path(file_info.path)
            
            log.warning(f"No files found in {user_path}")
            return None
        except Exception as e:
            log.warning(f"File path not found in UC: {user_path}, error: {e}")
            return None

    def _get_file_path_local(self, file_id: str, user_id: str) -> Optional[Path]:
        """Get file path from local filesystem."""
        # Validate user path for security
        self._validate_user_path(user_id, "get_file_path")
        
        user_path = Path(self.base_path) / user_id / file_id

        if not user_path.exists():
            log.warning(f"File path not found: {user_path}")
            return None

        # Find the actual Excel file (exclude metadata.json)
        files = [f for f in user_path.glob("*") if f.name != "metadata.json" and f.is_file()]
        if not files:
            log.warning(f"No files found in {user_path}")
            return None

        return files[0]

    def file_exists(self, file_id: str, user_id: str) -> bool:
        """
        Check if file exists in storage (UC or local).
        
        Args:
            file_id: File identifier
            user_id: User identifier
            
        Returns:
            True if file exists
        """
        if self.storage_backend == StorageBackend.UNITY_CATALOG:
            # For UC, try to get the path. If it succeeds, file exists.
            return self.get_file_path(file_id, user_id) is not None
        else:
            # For local, check filesystem
            file_path = self.get_file_path(file_id, user_id)
            return file_path is not None and file_path.exists()

    def get_file_size(self, file_id: str, user_id: str) -> int:
        """
        Get file size in bytes.
        
        Args:
            file_id: File identifier
            user_id: User identifier
            
        Returns:
            File size in bytes, or 0 if not found
        """
        # Validate user path for security
        self._validate_user_path(user_id, "get_file_size")
        
        if self.storage_backend == StorageBackend.UNITY_CATALOG:
            user_path = f"{self.base_path}/{user_id}/{file_id}"
            try:
                files = list(self.databricks_client.files.list_directory_contents(user_path))
                for file_info in files:
                    if not file_info.path.endswith("metadata.json"):
                        return file_info.size if hasattr(file_info, 'size') else 0
            except Exception:
                return 0
        else:
            file_path = self.get_file_path(file_id, user_id)
            if file_path and file_path.exists():
                return file_path.stat().st_size
        return 0

    def delete_file(self, file_id: str, user_id: str) -> bool:
        """
        Delete a file from storage.

        Args:
            file_id: File identifier
            user_id: User identifier

        Returns:
            True if deleted successfully
        """
        if self.storage_backend == StorageBackend.UNITY_CATALOG:
            return self._delete_file_uc(file_id, user_id)
        else:
            return self._delete_file_local(file_id, user_id)

    def _delete_file_uc(self, file_id: str, user_id: str) -> bool:
        """Delete file from Unity Catalog."""
        # Validate user path for security
        self._validate_user_path(user_id, "delete_file")
        
        user_path = f"{self.base_path}/{user_id}/{file_id}"
        
        try:
            # Try to list files in directory
            try:
                files = list(self.databricks_client.files.list_directory_contents(user_path))
            except Exception as list_error:
                # Directory might not exist or is already deleted
                log.warning(f"Could not list directory {user_path}: {list_error}")
                # Try to get the file path to see if it exists in a different format
                file_path = self.get_file_path(file_id, user_id)
                if file_path:
                    # File exists, try to delete it directly
                    try:
                        self.databricks_client.files.delete(str(file_path))
                        log.info(f"Deleted file directly from UC: {file_path}")
                        return True
                    except Exception as delete_error:
                        log.error(f"Failed to delete file directly: {delete_error}")
                        return False
                else:
                    # File doesn't exist, consider it already deleted
                    log.info(f"File {file_id} for user {user_id} not found, considering it deleted")
                    return True
            
            # List succeeded, delete all files in directory
            for file_info in files:
                try:
                    self.databricks_client.files.delete(file_info.path)
                    log.debug(f"Deleted file: {file_info.path}")
                except Exception as delete_error:
                    log.warning(f"Failed to delete {file_info.path}: {delete_error}")
            
            # Now try to delete the directory itself
            try:
                self.databricks_client.files.delete(user_path)
                log.info(f"Deleted file directory from UC: {user_path}")
            except Exception as dir_delete_error:
                log.warning(f"Failed to delete directory {user_path}: {dir_delete_error}")
            
            return True
        except Exception as e:
            log.error(f"Failed to delete file from UC: {e}")
            return False

    def _delete_file_local(self, file_id: str, user_id: str) -> bool:
        """Delete file from local filesystem."""
        # Validate user path for security
        self._validate_user_path(user_id, "delete_file")
        
        user_path = Path(self.base_path) / user_id / file_id

        try:
            if user_path.exists():
                shutil.rmtree(user_path)
                log.info(f"Deleted file: {user_path}")
                return True
            return False
        except Exception as e:
            log.error(f"Failed to delete file: {e}")
            return False

    def list_user_files(self, user_id: str) -> list:
        """
        List all files for a user.

        Args:
            user_id: User identifier

        Returns:
            List of file information dictionaries
        """
        if self.storage_backend == StorageBackend.UNITY_CATALOG:
            return self._list_user_files_uc(user_id)
        else:
            return self._list_user_files_local(user_id)

    def _list_user_files_uc(self, user_id: str) -> list:
        """List files from Unity Catalog."""
        # Validate user path for security
        self._validate_user_path(user_id, "list_files")
        
        user_path = f"{self.base_path}/{user_id}"
        
        try:
            # List directories in user path (each directory is a file_id)
            file_dirs = list(self.databricks_client.files.list_directory_contents(user_path))
        except Exception:
            # User path doesn't exist yet
            return []

        files = []
        for file_dir in file_dirs:
            if file_dir.is_directory:
                file_id = file_dir.name
                metadata_path = f"{user_path}/{file_id}/metadata.json"
                
                # Try to read metadata
                try:
                    metadata_content = self.databricks_client.files.download(metadata_path).contents.read()
                    metadata = json.loads(metadata_content)
                    
                    files.append({
                        "file_id": metadata.get("file_id", file_id),
                        "filename": metadata.get("filename", "unknown"),
                        "dialect": metadata.get("dialect", "unknown"),
                        "file_size": metadata.get("file_size", 0),
                        "created_at": metadata.get("created_at", ""),
                        "lineages": metadata.get("lineages", []),
                    })
                except Exception as e:
                    log.warning(f"Failed to read metadata for {file_id}: {e}")
                    # Fallback: list files in directory
                    try:
                        dir_files = list(self.databricks_client.files.list_directory_contents(f"{user_path}/{file_id}"))
                        for f in dir_files:
                            if not f.path.endswith("metadata.json"):
                                files.append({
                                    "file_id": file_id,
                                    "filename": f.name,
                                    "dialect": "unknown",
                                    "file_size": f.file_size or 0,
                                    "created_at": "",
                                    "lineages": [],
                                })
                                break
                    except Exception:
                        pass

        return files

    def _list_user_files_local(self, user_id: str) -> list:
        """List files from local filesystem."""
        # Validate user path for security
        self._validate_user_path(user_id, "list_files")
        
        user_path = Path(self.base_path) / user_id

        if not user_path.exists():
            return []

        files = []
        for file_dir in user_path.iterdir():
            if file_dir.is_dir():
                # Try to get metadata from metadata.json
                metadata_path = file_dir / "metadata.json"
                if metadata_path.exists():
                    try:
                        with open(metadata_path, "r") as f:
                            metadata = json.load(f)
                        files.append({
                            "file_id": metadata.get("file_id", file_dir.name),
                            "filename": metadata.get("filename", "unknown"),
                            "dialect": metadata.get("dialect", "unknown"),
                            "file_size": metadata.get("file_size", 0),
                            "created_at": metadata.get("created_at", ""),
                            "lineages": metadata.get("lineages", []),
                        })
                        continue
                    except Exception as e:
                        log.warning(f"Failed to read metadata for {file_dir.name}: {e}")
                
                # Fallback: scan directory for files
                for file_path in file_dir.glob("*"):
                    if file_path.is_file() and file_path.name != "metadata.json":
                        stat = file_path.stat()
                        files.append({
                            "file_id": file_dir.name,
                            "filename": file_path.name,
                            "dialect": "unknown",
                            "file_size": stat.st_size,
                            "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                            "lineages": [],
                        })
                        break

        return files

    def get_file_metadata(self, file_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get metadata for a file.
        
        Args:
            file_id: File identifier
            user_id: User identifier
            
        Returns:
            Metadata dictionary or None if not found
        """
        if self.storage_backend == StorageBackend.UNITY_CATALOG:
            return self._get_file_metadata_uc(file_id, user_id)
        else:
            return self._get_file_metadata_local(file_id, user_id)

    def _get_file_metadata_uc(self, file_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Get metadata from Unity Catalog."""
        # Validate user path for security
        self._validate_user_path(user_id, "get_metadata")
        
        metadata_path = f"{self.base_path}/{user_id}/{file_id}/metadata.json"
        
        try:
            metadata_content = self.databricks_client.files.download(metadata_path).contents.read()
            metadata = json.loads(metadata_content)
            return metadata
        except Exception as e:
            log.warning(f"Metadata not found in UC: {metadata_path}, error: {e}")
            return None

    def _get_file_metadata_local(self, file_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Get metadata from local filesystem."""
        # Validate user path for security
        self._validate_user_path(user_id, "get_metadata")
        
        user_path = Path(self.base_path) / user_id / file_id
        metadata_path = user_path / "metadata.json"
        
        try:
            if metadata_path.exists():
                with open(metadata_path, "r") as f:
                    metadata = json.load(f)
                return metadata
            else:
                log.warning(f"Metadata not found: {metadata_path}")
                return None
        except Exception as e:
            log.error(f"Failed to read metadata: {e}")
            return None

    def update_file_metadata(
        self, file_id: str, user_id: str, updates: Dict[str, Any]
    ) -> bool:
        """
        Update metadata for a file.
        
        Args:
            file_id: File identifier
            user_id: User identifier
            updates: Dictionary of updates to apply
            
        Returns:
            True if updated successfully
        """
        if self.storage_backend == StorageBackend.UNITY_CATALOG:
            return self._update_file_metadata_uc(file_id, user_id, updates)
        else:
            return self._update_file_metadata_local(file_id, user_id, updates)

    def _update_file_metadata_uc(
        self, file_id: str, user_id: str, updates: Dict[str, Any]
    ) -> bool:
        """Update metadata in Unity Catalog."""
        # Validate user path for security
        self._validate_user_path(user_id, "update_metadata")
        
        metadata_path = f"{self.base_path}/{user_id}/{file_id}/metadata.json"
        
        try:
            # Read existing metadata
            try:
                metadata_content = self.databricks_client.files.download(metadata_path).contents.read()
                metadata = json.loads(metadata_content)
            except Exception:
                log.warning(f"Metadata not found, creating new: {metadata_path}")
                metadata = {
                    "file_id": file_id,
                    "user_id": user_id,
                    "lineages": [],
                }
            
            # Apply updates
            metadata.update(updates)
            
            # Write back
            metadata_content = json.dumps(metadata, indent=2).encode()
            metadata_obj = io.BytesIO(metadata_content)
            self.databricks_client.files.upload(metadata_path, metadata_obj, overwrite=True)
            
            log.info(f"Updated metadata for {file_id} in UC")
            return True
            
        except Exception as e:
            log.error(f"Failed to update metadata in UC: {e}")
            return False

    def _update_file_metadata_local(
        self, file_id: str, user_id: str, updates: Dict[str, Any]
    ) -> bool:
        """Update metadata in local filesystem."""
        # Validate user path for security
        self._validate_user_path(user_id, "update_metadata")
        
        user_path = Path(self.base_path) / user_id / file_id
        metadata_path = user_path / "metadata.json"
        
        try:
            # Read existing metadata
            if metadata_path.exists():
                with open(metadata_path, "r") as f:
                    metadata = json.load(f)
            else:
                log.warning(f"Metadata not found, creating new: {metadata_path}")
                metadata = {
                    "file_id": file_id,
                    "user_id": user_id,
                    "lineages": [],
                }
            
            # Apply updates
            metadata.update(updates)
            
            # Write back
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)
            
            log.info(f"Updated metadata for {file_id}")
            return True
            
        except Exception as e:
            log.error(f"Failed to update metadata: {e}")
            return False

    def get_storage_stats(self) -> dict:
        """Get storage statistics."""
        if self.storage_backend == StorageBackend.UNITY_CATALOG:
            return self._get_storage_stats_uc()
        else:
            return self._get_storage_stats_local()

    def _get_storage_stats_uc(self) -> dict:
        """Get storage statistics from Unity Catalog."""
        try:
            total_files = 0
            total_size = 0
            
            # Recursively count files and sizes
            def count_files(path: str) -> None:
                nonlocal total_files, total_size
                try:
                    items = list(self.databricks_client.files.list_directory_contents(path))
                    for item in items:
                        if item.is_directory:
                            count_files(item.path)
                        else:
                            total_files += 1
                            total_size += item.file_size or 0
                except Exception:
                    pass
            
            count_files(self.base_path)
            
            return {
                "total_files": total_files,
                "total_size": total_size,
                "storage_backend": self.storage_backend.value,
                "base_path": str(self.base_path),
            }
        except Exception as e:
            log.error(f"Failed to get UC storage stats: {e}")
            return {"error": str(e)}

    def _get_storage_stats_local(self) -> dict:
        """Get storage statistics from local filesystem."""
        try:
            base = Path(self.base_path)
            if not base.exists():
                return {"total_files": 0, "total_size": 0}

            total_files = 0
            total_size = 0

            for root, dirs, files in os.walk(base):
                total_files += len(files)
                for file in files:
                    file_path = Path(root) / file
                    total_size += file_path.stat().st_size

            return {
                "total_files": total_files,
                "total_size": total_size,
                "storage_backend": self.storage_backend.value,
                "base_path": str(self.base_path),
            }
        except Exception as e:
            log.error(f"Failed to get storage stats: {e}")
            return {"error": str(e)}
