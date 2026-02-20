"""
Analyzer endpoints for metrics and complexity data.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from migration_accelerator.app.api.dependencies import (
    get_analyzer_service,
    get_current_user,
    get_storage_service,
    verify_file_access,
)
from migration_accelerator.app.decorators import handle_errors
from migration_accelerator.app.helpers.metadata_helper import MetadataHelper
from migration_accelerator.app.models.responses import (
    AnalyzerResponse,
    ComplexityResponse,
    MetricsResponse,
)
from migration_accelerator.app.services import AnalyzerService, StorageService
from migration_accelerator.utils.logger import get_logger

log = get_logger()

router = APIRouter(prefix="/analyzers", tags=["analyzer"])


@router.get("/{analyzer_id}", response_model=AnalyzerResponse)
@handle_errors("get_analyzer")
async def get_analyzer(
    analyzer_id: str,
    user_id: str = Depends(get_current_user),
    storage: StorageService = Depends(get_storage_service),
    analyzer: AnalyzerService = Depends(get_analyzer_service),
):
    """
    Get analyzer information.

    Args:
        analyzer_id: Analyzer file ID
        user_id: Current user ID
        storage: Storage service
        analyzer: Analyzer service

    Returns:
        Analyzer information
    """
    # Validate analyzer_id to prevent path traversal
    if ".." in analyzer_id or "/" in analyzer_id or "\\" in analyzer_id or analyzer_id.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid analyzer ID format")
    
    # Verify access
    await verify_file_access(analyzer_id, user_id, storage)

    # Get file path and metadata
    file_path, metadata = MetadataHelper.get_file_with_metadata(
        analyzer_id, user_id, storage
    )
    
    # Get dialect and lineages from metadata
    dialect = MetadataHelper.get_dialect_str(metadata)
    lineages = metadata.get("lineages", [])
    
    # Get analysis
    analysis = await analyzer.analyze_file(str(file_path), dialect, user_id)

    return AnalyzerResponse(
        analyzer_id=analyzer_id,
        filename=metadata["filename"],
        dialect=dialect,
        sheets=analysis["sheets"],
        file_size=metadata["file_size"],
        created_at=metadata["created_at"],
        metrics=analysis.get("metrics"),
        complexity=analysis.get("complexity"),
        lineages=lineages,
    )


@router.get("/{analyzer_id}/metrics", response_model=MetricsResponse)
@handle_errors("get_metrics")
async def get_metrics(
    analyzer_id: str,
    sheet_name: str = Query(default="Summary"),
    user_id: str = Depends(get_current_user),
    storage: StorageService = Depends(get_storage_service),
    analyzer: AnalyzerService = Depends(get_analyzer_service),
):
    """
    Get analyzer metrics.

    Args:
        analyzer_id: Analyzer file ID
        sheet_name: Sheet name to extract metrics from
        user_id: Current user ID
        storage: Storage service
        analyzer: Analyzer service

    Returns:
        Metrics response
    """
    # Verify access
    await verify_file_access(analyzer_id, user_id, storage)

    # Get file path and metadata
    file_path, metadata = MetadataHelper.get_file_with_metadata(
        analyzer_id, user_id, storage
    )
    dialect = MetadataHelper.get_dialect_str(metadata)
    
    metrics = await analyzer.get_metrics(str(file_path), dialect, sheet_name)

    return MetricsResponse(
        analyzer_id=analyzer_id,
        dialect=dialect,
        metrics=metrics,
        sheet_name=sheet_name,
    )


@router.get("/{analyzer_id}/complexity", response_model=ComplexityResponse)
@handle_errors("get_complexity")
async def get_complexity(
    analyzer_id: str,
    sheet_name: str = Query(default="Summary"),
    user_id: str = Depends(get_current_user),
    storage: StorageService = Depends(get_storage_service),
    analyzer: AnalyzerService = Depends(get_analyzer_service),
):
    """
    Get complexity breakdown.

    Args:
        analyzer_id: Analyzer file ID
        sheet_name: Sheet name to extract complexity from
        user_id: Current user ID
        storage: Storage service
        analyzer: Analyzer service

    Returns:
        Complexity response
    """
    # Verify access
    await verify_file_access(analyzer_id, user_id, storage)

    # Get file path and metadata
    file_path, metadata = MetadataHelper.get_file_with_metadata(
        analyzer_id, user_id, storage
    )
    dialect = MetadataHelper.get_dialect_str(metadata)
    
    complexity = await analyzer.get_complexity(str(file_path), dialect, sheet_name)

    # Handle SQL dialect which returns nested dict
    if isinstance(complexity, dict) and any(
        k in complexity for k in ["SQL", "ETL"]
    ):
        # Flatten for response
        flat_complexity = {}
        for key, value in complexity.items():
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    flat_complexity[f"{key}_{sub_key}"] = sub_value
            else:
                flat_complexity[key] = value
        complexity = flat_complexity

    total = sum(complexity.values())

    return ComplexityResponse(
        analyzer_id=analyzer_id,
        complexity=complexity,
        total=total,
        sheet_name=sheet_name,
    )


@router.get("/{analyzer_id}/sheets/{sheet_name}")
@handle_errors("get_sheet_data")
async def get_sheet_data(
    analyzer_id: str,
    sheet_name: str,
    user_id: str = Depends(get_current_user),
    storage: StorageService = Depends(get_storage_service),
    analyzer: AnalyzerService = Depends(get_analyzer_service),
):
    """
    Get data from a specific sheet.

    Args:
        analyzer_id: Analyzer file ID
        sheet_name: Sheet name
        user_id: Current user ID
        storage: Storage service
        analyzer: Analyzer service

    Returns:
        Sheet data as JSON
    """
    # Verify access
    await verify_file_access(analyzer_id, user_id, storage)

    # Get file path and metadata
    file_path, metadata = MetadataHelper.get_file_with_metadata(
        analyzer_id, user_id, storage
    )
    dialect = MetadataHelper.get_dialect_str(metadata)

    data = await analyzer.get_sheet_data(str(file_path), dialect, sheet_name)

    return {"sheet_name": sheet_name, "data": data, "count": len(data)}




