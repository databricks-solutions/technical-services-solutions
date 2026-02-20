"""
Upload endpoints for file management.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from migration_accelerator.app.api.dependencies import (
    get_analyzer_service,
    get_current_user,
    get_lineage_auto_generator,
    get_lineage_merger,
    get_lineage_service,
    get_storage_service,
)
from migration_accelerator.app.decorators import handle_errors
from migration_accelerator.app.helpers.metadata_helper import MetadataHelper
from migration_accelerator.app.config import settings
from migration_accelerator.app.models.responses import UploadResponse
from migration_accelerator.app.services import AnalyzerService, LineageService, StorageService
from migration_accelerator.app.services.lineage_merger import LineageMerger
from migration_accelerator.app.services.dialect_detector import (
    detect_dialect_from_excel_async,
)
from migration_accelerator.app.services.lineage_auto_generator import LineageAutoGenerator
from migration_accelerator.utils.logger import get_logger

log = get_logger()

router = APIRouter(prefix="/upload", tags=["upload"])

# Allowed file extensions
ALLOWED_EXTENSIONS = {".xlsx", ".xls"}
ALLOWED_DIALECTS = {"talend", "informatica", "sql", "datastage"}


@router.post("", response_model=UploadResponse)
@handle_errors("upload_file")
async def upload_file(
    file: UploadFile = File(..., description="Excel analyzer file"),
    dialect: Optional[str] = Form(None, description="Analyzer dialect (optional, will auto-detect)"),
    user_id: str = Depends(get_current_user),
    storage: StorageService = Depends(get_storage_service),
    analyzer: AnalyzerService = Depends(get_analyzer_service),
    auto_generator: LineageAutoGenerator = Depends(get_lineage_auto_generator),
    merger: LineageMerger = Depends(get_lineage_merger),
):
    """
    Upload an analyzer Excel file for processing.

    Args:
        file: Uploaded Excel file
        dialect: Analyzer dialect (optional, will be auto-detected if not provided)
        user_id: Current user ID
        storage: Storage service
        analyzer: Analyzer service
        auto_generator: Lineage auto-generator service

    Returns:
        Upload response with analyzer ID and metadata
    """
    # Validate file extension
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    file_ext = "." + file.filename.split(".")[-1].lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # Check file size (read content to check)
    content = await file.read()
    file_size = len(content)

    if file_size > settings.max_upload_size:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {settings.max_upload_size} bytes",
        )

    # Reset file pointer for storage
    await file.seek(0)

    # Save file temporarily to detect dialect if needed
    file_info = await storage.save_uploaded_file(file, user_id, dialect or "unknown")
    
    # Auto-detect dialect if not provided
    if not dialect:
        file_path = storage.get_file_path(file_info["file_id"], user_id)
        if file_path:
            detected_dialect = await detect_dialect_from_excel_async(str(file_path))
            if detected_dialect:
                dialect = detected_dialect
                # Update metadata with detected dialect
                storage.update_file_metadata(
                    file_info["file_id"], 
                    user_id, 
                    {"dialect": dialect}
                )
                file_info["dialect"] = dialect
                log.info(f"Auto-detected dialect: {dialect}")
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Could not auto-detect dialect. Please specify manually.",
                )
        else:
            raise HTTPException(status_code=500, detail="Failed to save file")
    
    # Validate dialect
    if dialect not in ALLOWED_DIALECTS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid dialect. Must be one of: {', '.join(ALLOWED_DIALECTS)}",
        )

    # Analyze file to get sheets
    file_path = storage.get_file_path(file_info["file_id"], user_id)
    if not file_path:
        raise HTTPException(status_code=500, detail="Failed to save file")

    analysis = await analyzer.analyze_file(str(file_path), dialect, user_id)

    # Auto-generate lineages using the service
    lineages = await auto_generator.auto_generate_lineages(
        file_path=str(file_path),
        dialect=dialect,
        sheets=analysis.get("sheets", []),
        user_id=user_id,
        analyzer_id=file_info["file_id"],
    )
    
    # Update metadata with lineages
    if lineages:
        storage.update_file_metadata(
            file_info["file_id"],
            user_id,
            {"lineages": lineages}
        )
    
    # Invalidate aggregate lineage cache since new file was added
    merger.invalidate_cache_for_user(user_id)

    log.info(
        f"File uploaded successfully: {file.filename} ({file_size} bytes) by user {user_id}. "
        f"Generated {len(lineages)} lineage(s)."
    )

    return UploadResponse(
        analyzer_id=file_info["file_id"],
        filename=file_info["filename"],
        dialect=dialect,
        file_size=file_size,
        sheets=analysis.get("sheets", []),
        created_at=file_info["created_at"],
        lineages=lineages,
    )


@router.get("/files")
@handle_errors("list_files")
async def list_files(
    user_id: str = Depends(get_current_user),
    storage: StorageService = Depends(get_storage_service),
):
    """
    List all uploaded files for the current user.

    Args:
        user_id: Current user ID
        storage: Storage service

    Returns:
        List of user files with metadata
    """
    files = storage.list_user_files(user_id)
    return {"files": files, "count": len(files)}


@router.delete("/{file_id}")
@handle_errors("delete_file")
async def delete_file(
    file_id: str,
    user_id: str = Depends(get_current_user),
    storage: StorageService = Depends(get_storage_service),
    lineage_service: LineageService = Depends(get_lineage_service),
    merger: LineageMerger = Depends(get_lineage_merger),
):
    """
    Delete an uploaded file and all associated lineage data.

    Args:
        file_id: File identifier
        user_id: Current user ID
        storage: Storage service
        lineage_service: Lineage service for cleanup

    Returns:
        Success message with cleanup details
    """
    # Verify file exists and belongs to user
    file_path = storage.get_file_path(file_id, user_id)
    if not file_path:
        raise HTTPException(status_code=404, detail="File not found")

    # Get file metadata to find associated lineages
    metadata = storage.get_file_metadata(file_id, user_id)
    lineage_ids = []
    if metadata and "lineages" in metadata:
        lineage_ids = [l.get("lineage_id") for l in metadata.get("lineages", []) if l.get("lineage_id")]

    # Delete associated lineages first
    lineages_deleted = 0
    if lineage_ids:
        log.info(f"Deleting {len(lineage_ids)} associated lineages for file {file_id}")
        deletion_results = await lineage_service.delete_lineages_batch(lineage_ids, user_id)
        lineages_deleted = sum(1 for success in deletion_results.values() if success)
        
        if lineages_deleted < len(lineage_ids):
            log.warning(
                f"Only {lineages_deleted}/{len(lineage_ids)} lineages deleted successfully for file {file_id}"
            )

    # Delete file
    success = storage.delete_file(file_id, user_id)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete file")
    
    # Invalidate aggregate lineage cache since file was removed
    merger.invalidate_cache_for_user(user_id)

    log.info(
        f"File deleted: {file_id} by user {user_id} "
        f"(cleaned up {lineages_deleted} lineages)"
    )

    return {
        "message": "File deleted successfully",
        "file_id": file_id,
        "lineages_deleted": lineages_deleted,
    }


