"""
Upload endpoints for file management.
"""

import asyncio
import io
import json
import os
import tempfile as tempfile_mod
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile

from migration_accelerator.app.api.dependencies import (
    get_analyzer_service,
    get_cache_service,
    get_current_user,
    get_lineage_merger,
    get_lineage_service,
    get_storage_service,
)
from migration_accelerator.app.services.cache_service import CacheService
from migration_accelerator.app.decorators import handle_errors
from migration_accelerator.app.config import settings
from migration_accelerator.app.models.responses import UploadResponse, UploadStatusResponse
from migration_accelerator.app.services import LineageService, StorageService
from migration_accelerator.app.services.lineage_merger import LineageMerger
from migration_accelerator.app.services.lineage_auto_generator import LineageAutoGenerator
from migration_accelerator.utils.logger import get_logger

log = get_logger()

router = APIRouter(prefix="/upload", tags=["upload"])

# Allowed file extensions
ALLOWED_EXTENSIONS = {".xlsx", ".xls"}
ALLOWED_DIALECTS = {"talend", "informatica", "sql", "datastage"}

# Cache key prefix and TTL for list_files (invalidate on upload/delete)
FILES_LIST_CACHE_KEY_PREFIX = "files:list:"
FILES_LIST_CACHE_TTL_SEC = 120

# In-memory processing status tracker
# Maps file_id -> {"status": "processing"|"complete"|"error", "error": str|None, "lineages": list, ...}
_processing_status: Dict[str, Dict] = {}

# Semaphore to serialize in-app background processing (in_memory backend only).
_processing_semaphore = threading.Semaphore(1)
_SEMAPHORE_TIMEOUT = 120  # seconds to wait before giving up

# Files currently being deleted in background; list_files excludes these so the UI doesn't show them
_pending_deletes: Dict[str, set] = {}  # user_id -> set of file_id


def _process_file_background(
    file_id: str,
    temp_file_path: str,
    original_filename: str,
    dialect: str,
    user_id: str,
    file_size: int,
    timestamp: str,
):
    """
    Background task to persist file to UC, analyze, and generate lineages.

    This is intentionally a sync function (not async) so that Starlette runs it
    in a thread pool. This prevents CPU-heavy Excel parsing from blocking the
    main event loop and causing timeouts on all other requests.

    Uses a semaphore with timeout to serialize processing — large Excel files
    consume significant CPU and memory, and concurrent processing causes 502/OOM.
    The timeout ensures the thread doesn't block forever during shutdown.
    """
    acquired = _processing_semaphore.acquire(timeout=_SEMAPHORE_TIMEOUT)
    if not acquired:
        log.warning(f"Semaphore timeout for {file_id} — another file is still processing")
        _processing_status[file_id] = {
            "status": "error",
            "lineages": [],
            "error": "Server busy processing another file. Please try again shortly.",
        }
        # Clean up temp file
        try:
            os.unlink(temp_file_path)
        except Exception:
            pass
        return
    try:
        asyncio.run(_process_file_background_async(
            file_id, temp_file_path, original_filename, dialect, user_id, file_size, timestamp,
        ))
    finally:
        _processing_semaphore.release()


async def _process_file_background_async(
    file_id: str,
    temp_file_path: str,
    original_filename: str,
    dialect: str,
    user_id: str,
    file_size: int,
    timestamp: str,
):
    """Async implementation of background file processing.

    Handles:
    1. Uploading the file to persistent storage (UC or local) — moved here from
       the request handler so the upload POST returns instantly.
    2. Dialect detection, analysis, lineage generation.
    3. Cache pre-warming.
    """
    from migration_accelerator.app.services.dialect_detector import (
        detect_dialect_from_excel,
    )

    try:
        log.info(f"Background processing started for {file_id}")

        # Reuse singleton service instances from the dependency system
        analyzer = get_analyzer_service()
        auto_generator = LineageAutoGenerator()
        storage = get_storage_service()
        merger = get_lineage_merger()

        from migration_accelerator.app.config import StorageBackend
        from migration_accelerator.app import config

        # ── Step 1: Persist file to permanent storage (UC or local) ──
        # The upload handler saved the file to a local temp path to avoid
        # blocking the HTTP request with slow UC uploads.
        metadata = {
            "file_id": file_id,
            "filename": original_filename,
            "dialect": dialect,
            "file_size": file_size,
            "user_id": user_id,
            "created_at": timestamp,
            "lineages": [],
        }

        if config.settings.storage_backend == StorageBackend.UNITY_CATALOG:
            uc_dir = f"{storage.base_path}/{user_id}/{file_id}"
            uc_file_path = f"{uc_dir}/{original_filename}"
            uc_metadata_path = f"{uc_dir}/metadata.json"

            # Upload file + metadata to UC (stream file directly, no extra memory copy)
            try:
                storage.databricks_client.files.create_directory(uc_dir)
            except Exception:
                pass
            with open(temp_file_path, "rb") as f:
                storage.databricks_client.files.upload(
                    uc_file_path, f, overwrite=True,
                )
            storage.databricks_client.files.upload(
                uc_metadata_path,
                io.BytesIO(json.dumps(metadata, indent=2).encode()),
                overwrite=True,
            )
            # Update manifest for O(1) file listing
            try:
                storage._upsert_manifest(user_id, file_id, metadata)
            except Exception as e:
                log.warning(f"Failed to update manifest (non-fatal): {e}")
            log.info(f"Persisted file to UC: {uc_file_path}")
        else:
            # Local storage
            local_dir = Path(storage.base_path) / user_id / file_id
            local_dir.mkdir(parents=True, exist_ok=True)
            local_file_dest = local_dir / original_filename
            local_metadata_dest = local_dir / "metadata.json"

            with open(temp_file_path, "rb") as src, open(local_file_dest, "wb") as dst:
                dst.write(src.read())
            with open(local_metadata_dest, "w") as f:
                json.dump(metadata, f, indent=2)
            # Update manifest for O(1) file listing
            try:
                storage._upsert_manifest(user_id, file_id, metadata)
            except Exception as e:
                log.warning(f"Failed to update manifest (non-fatal): {e}")
            log.info(f"Persisted file to local: {local_file_dest}")

        # Invalidate files list cache so the file appears in list_files
        get_cache_service().delete(f"{FILES_LIST_CACHE_KEY_PREFIX}{user_id}")

        # ── Step 2: Detect dialect, analyze, generate lineages ──
        # Use the local temp file directly — no need to re-download from UC.
        local_file_path = temp_file_path

        # Resolve dialect when not provided
        if dialect in (None, "unknown"):
            detected_dialect = detect_dialect_from_excel(local_file_path)
            if not detected_dialect:
                merger.invalidate_cache_for_user(user_id)
                get_cache_service().delete(f"{FILES_LIST_CACHE_KEY_PREFIX}{user_id}")
                _processing_status[file_id] = {
                    "status": "error",
                    "lineages": [],
                    "error": "Could not auto-detect dialect. Please re-upload with dialect specified.",
                }
                log.warning(f"Dialect detection failed for {file_id}")
                return
            dialect = detected_dialect
            storage.update_file_metadata(file_id, user_id, {"dialect": dialect})
            log.info(f"Auto-detected dialect in background: {dialect}")

        analysis = await analyzer.analyze_file(local_file_path, dialect, user_id)

        lineages = await auto_generator.auto_generate_lineages(
            file_path=local_file_path,
            dialect=dialect,
            sheets=analysis.get("sheets", []),
            user_id=user_id,
            analyzer_id=file_id,
        )

        if lineages:
            storage.update_file_metadata(file_id, user_id, {"lineages": lineages})

        # Invalidate caches
        merger.invalidate_cache_for_user(user_id)
        get_cache_service().delete(f"{FILES_LIST_CACHE_KEY_PREFIX}{user_id}")

        # Pre-warm aggregate lineage cache so the frontend doesn't hit a 504
        # when loading insights/lineage tabs after upload.
        # Skip if this is the user's only file — no merge needed, and insights
        # will be computed on first tab visit. Saves 30-60s for first upload.
        try:
            all_files = await asyncio.to_thread(storage.list_user_files, user_id)
            if len(all_files) > 1:
                from migration_accelerator.app.api.dependencies import (
                    get_lineage_analyzer,
                    get_migration_planner,
                )
                log.info(f"Pre-warming aggregate lineage cache for user {user_id}")
                graph_data = await merger.merge_all_lineages(user_id, include_file_dependencies=True)

                analyzer_svc = get_lineage_analyzer()
                planner = get_migration_planner()
                await analyzer_svc.compute_insights(graph_data)
                await planner.compute_migration_order(graph_data)

                log.info(f"Cache pre-warming complete for user {user_id}")
            else:
                log.info(f"Skipping pre-warming for user {user_id} (single file, no merge needed)")
        except Exception as warm_err:
            log.warning(f"Cache pre-warming failed (non-fatal): {warm_err}")

        prev = _processing_status.get(file_id, {})
        _processing_status[file_id] = {
            "status": "complete",
            "lineages": lineages,
            "error": None,
            "metadata": prev.get("metadata", {}),
        }
        log.info(
            f"Background processing complete for {file_id}: "
            f"{len(lineages)} lineage(s) generated"
        )

    except Exception as e:
        log.error(f"Background processing failed for {file_id}: {e}")
        prev = _processing_status.get(file_id, {})
        _processing_status[file_id] = {
            "status": "error",
            "lineages": [],
            "error": str(e),
            "metadata": prev.get("metadata", {}),
        }
    finally:
        # Clean up temp file
        try:
            os.unlink(temp_file_path)
        except Exception:
            pass


async def _delete_file_background_task(
    file_id: str,
    user_id: str,
    lineage_ids: List[str],
):
    """Run file and lineage deletion in the background so the delete API returns quickly."""
    try:
        lineage_service = get_lineage_service()
        storage = get_storage_service()
        merger = get_lineage_merger()
        lineages_deleted = 0
        if lineage_ids:
            log.info(f"Background: deleting {len(lineage_ids)} lineages for file {file_id}")
            # Run each lineage deletion in a thread to avoid blocking the event loop
            # (each call hits the synchronous Databricks SDK)
            delete_tasks = [
                asyncio.to_thread(lineage_service._delete_lineage_sync, lid, user_id)
                for lid in lineage_ids
            ]
            results = await asyncio.gather(*delete_tasks, return_exceptions=True)
            lineages_deleted = sum(1 for r in results if r is True)
        # storage.delete_file is synchronous (multiple blocking SDK calls) —
        # run in thread to avoid blocking the event loop
        success = await asyncio.to_thread(storage.delete_file, file_id, user_id)
        if not success:
            log.warning(f"Background delete: storage.delete_file returned False for {file_id}")
        merger.invalidate_cache_for_user(user_id)
        get_cache_service().delete(f"{FILES_LIST_CACHE_KEY_PREFIX}{user_id}")
        log.info(
            f"Background delete complete: file_id={file_id} user_id={user_id} "
            f"lineages_deleted={lineages_deleted}"
        )
    except Exception as e:
        log.error(f"Background delete failed for {file_id}: {e}")
    finally:
        _pending_deletes.setdefault(user_id, set()).discard(file_id)


@router.post("", response_model=UploadResponse)
@handle_errors("upload_file")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Excel analyzer file"),
    dialect: Optional[str] = Form(None, description="Analyzer dialect (optional, will auto-detect)"),
    user_id: str = Depends(get_current_user),
    storage: StorageService = Depends(get_storage_service),
):
    """
    Upload an analyzer Excel file for processing.

    Processing runs in a background task. Poll GET /upload/{file_id}/status for completion.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    file_ext = "." + file.filename.split(".")[-1].lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    if dialect and dialect not in ALLOWED_DIALECTS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid dialect. Must be one of: {', '.join(ALLOWED_DIALECTS)}",
        )

    content = await file.read()
    file_size = len(content)

    if file_size > settings.max_upload_size:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {settings.max_upload_size} bytes",
        )

    file_id = str(uuid.uuid4())
    timestamp = datetime.now().isoformat()
    response_dialect = dialect if dialect else "unknown"

    temp = tempfile_mod.NamedTemporaryFile(delete=False, suffix=file_ext)
    temp.write(content)
    temp.close()

    get_cache_service().delete(f"{FILES_LIST_CACHE_KEY_PREFIX}{user_id}")

    _processing_status[file_id] = {
        "status": "processing",
        "lineages": [],
        "error": None,
        "metadata": {
            "filename": file.filename,
            "dialect": response_dialect,
            "file_size": file_size,
            "created_at": timestamp,
        },
    }

    background_tasks.add_task(
        _process_file_background,
        file_id=file_id,
        temp_file_path=temp.name,
        original_filename=file.filename,
        dialect=response_dialect,
        user_id=user_id,
        file_size=file_size,
        timestamp=timestamp,
    )

    log.info(
        f"File uploaded: {file.filename} ({file_size} bytes) by user {user_id}. "
        f"Processing queued in background."
    )

    return UploadResponse(
        analyzer_id=file_id,
        filename=file.filename,
        dialect=response_dialect,
        file_size=file_size,
        sheets=[],
        created_at=timestamp,
        lineages=[],
    )


@router.get("/{file_id}/status", response_model=UploadStatusResponse)
@handle_errors("upload_status")
async def get_upload_status(
    file_id: str,
    user_id: str = Depends(get_current_user),
    storage: StorageService = Depends(get_storage_service),
):
    """
    Check the processing status of an uploaded file.

    Returns status: "processing", "complete", or "error".
    """
    if file_id in _processing_status:
        status_info = _processing_status[file_id]
        proc_metadata = status_info.get("metadata", {})

        if status_info["status"] in ("complete", "error"):
            uc_metadata = await asyncio.to_thread(
                storage.get_file_metadata, file_id, user_id
            ) or {}
            result = UploadStatusResponse(
                file_id=file_id,
                status=status_info["status"],
                filename=uc_metadata.get("filename", proc_metadata.get("filename", "")),
                dialect=uc_metadata.get("dialect", proc_metadata.get("dialect")),
                lineages=status_info["lineages"],
                error=status_info["error"],
            )
            del _processing_status[file_id]
            return result

        return UploadStatusResponse(
            file_id=file_id,
            status="processing",
            filename=proc_metadata.get("filename", ""),
            dialect=proc_metadata.get("dialect"),
        )

    file_path = await asyncio.to_thread(storage.get_file_path, file_id, user_id)
    if not file_path:
        raise HTTPException(status_code=404, detail="File not found")

    metadata = await asyncio.to_thread(storage.get_file_metadata, file_id, user_id) or {}
    lineages = metadata.get("lineages", [])
    processing_error = metadata.get("processing_error")

    if lineages:
        return UploadStatusResponse(
            file_id=file_id,
            status="complete",
            filename=metadata.get("filename", ""),
            dialect=metadata.get("dialect"),
            lineages=lineages,
        )

    if processing_error:
        return UploadStatusResponse(
            file_id=file_id,
            status="error",
            filename=metadata.get("filename", ""),
            dialect=metadata.get("dialect"),
            lineages=[],
            error=processing_error,
        )

    return UploadStatusResponse(
        file_id=file_id,
        status="complete",
        filename=metadata.get("filename", ""),
        dialect=metadata.get("dialect"),
        lineages=[],
    )


@router.get("/files")
@handle_errors("list_files")
async def list_files(
    user_id: str = Depends(get_current_user),
    storage: StorageService = Depends(get_storage_service),
    cache: CacheService = Depends(get_cache_service),
):
    """
    List all uploaded files for the current user.

    Results are cached per user with short TTL; cache is invalidated on upload/delete.
    """
    cache_key = f"{FILES_LIST_CACHE_KEY_PREFIX}{user_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        files = cached["files"]
    else:
        # list_user_files calls synchronous UC SDK methods — run in thread
        # to avoid blocking the event loop and causing 502/504 on concurrent requests.
        files = await asyncio.to_thread(storage.list_user_files, user_id)
        cache.set(cache_key, {"files": files, "count": len(files)}, ttl=FILES_LIST_CACHE_TTL_SEC)
    pending = _pending_deletes.get(user_id, set())
    files = [f for f in files if f["file_id"] not in pending]
    return {"files": files, "count": len(files)}


@router.delete("/{file_id}")
@handle_errors("delete_file")
async def delete_file(
    background_tasks: BackgroundTasks,
    file_id: str,
    user_id: str = Depends(get_current_user),
    storage: StorageService = Depends(get_storage_service),
):
    """
    Start deletion of an uploaded file and its lineage data.

    Returns immediately; deletion runs in the background. The file is hidden
    from list_files right away and removed from storage once the task completes.
    """
    # Run blocking UC SDK calls in a thread to avoid blocking the event loop.
    # get_file_path and get_file_metadata both call synchronous SDK methods.
    file_path = await asyncio.to_thread(storage.get_file_path, file_id, user_id)
    if not file_path:
        raise HTTPException(status_code=404, detail="File not found")

    metadata = await asyncio.to_thread(storage.get_file_metadata, file_id, user_id)
    lineage_ids = []
    if metadata and "lineages" in metadata:
        lineage_ids = [l.get("lineage_id") for l in metadata.get("lineages", []) if l.get("lineage_id")]

    # Hide from list immediately and run actual delete in background
    _pending_deletes.setdefault(user_id, set()).add(file_id)
    get_cache_service().delete(f"{FILES_LIST_CACHE_KEY_PREFIX}{user_id}")

    background_tasks.add_task(
        _delete_file_background_task,
        file_id=file_id,
        user_id=user_id,
        lineage_ids=lineage_ids,
    )

    log.info(f"File deletion started in background: {file_id} for user {user_id} ({len(lineage_ids)} lineages)")
    return {
        "message": "File deletion started. The file and its lineages will be removed shortly.",
        "file_id": file_id,
    }
