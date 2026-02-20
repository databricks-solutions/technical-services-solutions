"""
LLM query endpoints.
"""

from fastapi import APIRouter, Body, Depends, HTTPException

from migration_accelerator.app.api.dependencies import (
    get_analyzer_query_service,
    get_current_user,
    get_storage_service,
    verify_file_access,
)
from migration_accelerator.app.decorators import handle_errors
from migration_accelerator.app.helpers.metadata_helper import MetadataHelper
from migration_accelerator.app.models.requests import QueryRequest
from migration_accelerator.app.models.responses import QueryResponse
from migration_accelerator.app.services import StorageService
from migration_accelerator.app.services.analyzer_query_service import AnalyzerQueryService
from migration_accelerator.utils.logger import get_logger

log = get_logger()

router = APIRouter(prefix="/query", tags=["query"])


@router.post("", response_model=QueryResponse)
@handle_errors("query_analyzer")
async def query_analyzer(
    request: QueryRequest = Body(...),
    user_id: str = Depends(get_current_user),
    storage: StorageService = Depends(get_storage_service),
    query_service: AnalyzerQueryService = Depends(get_analyzer_query_service),
):
    """
    Query analyzer data using natural language.

    Args:
        request: Query request
        user_id: Current user ID
        storage: Storage service
        query_service: Analyzer query service

    Returns:
        Query response with LLM answer
    """
    # Determine which files to query
    file_ids_to_query = []
    
    if request.scope == "all":
        # Query all user files
        all_files = storage.list_user_files(user_id)
        file_ids_to_query = [f["file_id"] for f in all_files]
    elif request.scope == "multiple" and request.analyzer_ids:
        # Query specific files
        file_ids_to_query = request.analyzer_ids
    else:
        # Query single file (default)
        file_ids_to_query = [request.analyzer_id]
    
    # Verify access to all files
    for file_id in file_ids_to_query:
        await verify_file_access(file_id, user_id, storage)
    
    # Get file paths and dialects using MetadataHelper
    file_data = []
    for file_id in file_ids_to_query:
        try:
            file_path, metadata = MetadataHelper.get_file_with_metadata(
                file_id, user_id, storage
            )
            dialect = MetadataHelper.get_dialect_str(metadata)
            
            file_data.append({
                "file_id": file_id,
                "file_path": str(file_path),
                "dialect": dialect,
                "filename": metadata.get("filename", "")
            })
        except HTTPException:
            # Skip files that don't exist
            continue
    
    if not file_data:
        raise HTTPException(status_code=404, detail="No valid files found")
    
    # Query using the service
    if len(file_data) == 1:
        # Single file query
        log.info(f"Querying single analyzer {file_data[0]['file_id']}: {request.question}")
        result = await query_service.query_single(
            file_data[0]["file_path"], 
            file_data[0]["dialect"], 
            request.question
        )
        result["sources"] = [file_data[0]["filename"]]
    else:
        # Multi-file query
        log.info(f"Querying {len(file_data)} analyzers: {request.question}")
        result = await query_service.query_multiple(
            file_data,
            request.question
        )
    
    return QueryResponse(**result)




