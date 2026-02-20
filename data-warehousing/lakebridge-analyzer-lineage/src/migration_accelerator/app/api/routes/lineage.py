"""
Lineage visualization endpoints.
"""

from typing import List

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response

from migration_accelerator.app.api.dependencies import (
    get_current_user,
    get_lineage_analyzer,
    get_lineage_exporter,
    get_lineage_merger,
    get_lineage_service,
    get_migration_planner,
    get_storage_service,
    verify_file_access,
)
from migration_accelerator.app.models.requests import (
    FilterAggregateRequest,
    LineageCreateRequest,
)
from migration_accelerator.app.models.responses import (
    AggregateLineageResponse,
    LineageGraphResponse,
    LineageInsightsResponse,
    LineageResponse,
    NodeSearchResponse,
)
from migration_accelerator.app.constants import ExportFormat
from migration_accelerator.app.decorators import handle_errors
from migration_accelerator.app.services import LineageService, StorageService
from migration_accelerator.app.services.lineage_analyzer import LineageAnalyzer
from migration_accelerator.app.services.lineage_exporter import LineageExporter
from migration_accelerator.app.services.lineage_merger import LineageMerger
from migration_accelerator.app.services.migration_planner import MigrationPlanner
from migration_accelerator.utils.logger import get_logger

log = get_logger()

router = APIRouter(prefix="/lineage", tags=["lineage"])


@router.post("", response_model=LineageResponse)
async def create_lineage(
    request: LineageCreateRequest = Body(...),
    user_id: str = Depends(get_current_user),
    storage: StorageService = Depends(get_storage_service),
    lineage: LineageService = Depends(get_lineage_service),
):
    """
    Create lineage visualization from analyzer file.

    Args:
        request: Lineage creation request
        user_id: Current user ID
        storage: Storage service
        lineage: Lineage service

    Returns:
        Lineage response with graph statistics
    """
    try:
        # Verify access to analyzer file
        await verify_file_access(request.analyzer_id, user_id, storage)

        file_path = storage.get_file_path(request.analyzer_id, user_id)
        if not file_path:
            raise HTTPException(status_code=404, detail="Analyzer not found")

        # Get dialect from metadata
        metadata = storage.get_file_metadata(request.analyzer_id, user_id)
        dialect = metadata.get("dialect", "talend") if metadata else "talend"
        
        # Create lineage
        log.info(f"Creating lineage for analyzer {request.analyzer_id} (dialect: {dialect})")
        result = await lineage.create_lineage_from_analyzer(
            file_path=str(file_path),
            dialect=dialect,
            sheet_name=request.sheet_name,
            user_id=user_id,
            format=request.format,
            source_column=request.source_column,
            target_column=request.target_column,
            relationship_column=request.relationship_column,
            script_column=request.script_column,
            enhance_with_llm=request.enhance_with_llm,
            additional_context=request.additional_context,
        )
        
        # Update metadata with new lineage
        if metadata:
            current_lineages = metadata.get("lineages", [])
            current_lineages.append({
                "lineage_id": result["lineage_id"],
                "format": request.format,
                "sheet_name": request.sheet_name,
                "created_at": result["created_at"],
                "auto_generated": False,
            })
            storage.update_file_metadata(
                request.analyzer_id,
                user_id,
                {"lineages": current_lineages}
            )

        return LineageResponse(**result, analyzer_id=request.analyzer_id)

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to create lineage: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Aggregate Lineage Endpoints
# NOTE: These routes must come BEFORE /{lineage_id}/* routes to avoid path collisions
# (FastAPI would otherwise match "aggregate" as a lineage_id)


@router.get("/aggregate", response_model=AggregateLineageResponse)
@handle_errors("get_aggregate_lineage")
async def get_aggregate_lineage(
    include_file_dependencies: bool = Query(
        False,
        description="Include FILE->FILE dependency edges derived from table lineage"
    ),
    user_id: str = Depends(get_current_user),
    merger: LineageMerger = Depends(get_lineage_merger),
):
    """
    Get aggregate lineage graph merged from all user files.

    Args:
        include_file_dependencies: If True, add FILE->FILE dependency edges showing
                                   which files depend on other files through shared tables
        user_id: Current user ID
        merger: Lineage merger service

    Returns:
        Merged lineage graph with all nodes and edges from user's files
    """
    import time
    start_time = time.time()
    
    graph_data = await merger.merge_all_lineages(
        user_id, include_file_dependencies=include_file_dependencies
    )
    
    duration = time.time() - start_time
    cached = graph_data.get("cached", False)
    node_count = len(graph_data.get("nodes", []))
    edge_count = len(graph_data.get("edges", []))
    
    log.info(
        f"Aggregate lineage computed in {duration:.2f}s | "
        f"cached={cached} | nodes={node_count} | edges={edge_count} | user={user_id}"
    )
    
    return AggregateLineageResponse(**graph_data)


@router.get("/aggregate/complete")
@handle_errors("get_aggregate_lineage_complete")
async def get_aggregate_lineage_complete(
    include_file_dependencies: bool = Query(
        False,
        description="Include FILE->FILE dependency edges derived from table lineage"
    ),
    user_id: str = Depends(get_current_user),
    merger: LineageMerger = Depends(get_lineage_merger),
    analyzer: LineageAnalyzer = Depends(get_lineage_analyzer),
):
    """
    Get complete aggregate lineage with both graph data and insights in one call.
    
    This endpoint combines /aggregate and /aggregate/insights to reduce API calls
    and avoid duplicate graph computation.

    Args:
        include_file_dependencies: If True, add FILE->FILE dependency edges
        user_id: Current user ID
        merger: Lineage merger service
        analyzer: Lineage analyzer service

    Returns:
        Combined response with graph data and insights
    """
    # Get merged graph (cached)
    graph_data = await merger.merge_all_lineages(
        user_id, include_file_dependencies=include_file_dependencies
    )

    # Compute insights from the same graph data
    insights = await analyzer.compute_insights(graph_data)

    # Combine both responses
    return {
        "graph": graph_data,
        "insights": insights,
    }


@router.get("/aggregate/insights", response_model=LineageInsightsResponse)
@handle_errors("get_aggregate_lineage_insights")
async def get_aggregate_lineage_insights(
    user_id: str = Depends(get_current_user),
    merger: LineageMerger = Depends(get_lineage_merger),
    analyzer: LineageAnalyzer = Depends(get_lineage_analyzer),
):
    """
    Get insights and analytics from the aggregate lineage graph.

    Args:
        user_id: Current user ID
        merger: Lineage merger service
        analyzer: Lineage analyzer service

    Returns:
        Insights including most connected nodes, orphans, statistics
    """
    import time
    start_time = time.time()
    
    # First get the merged graph (cached)
    graph_data = await merger.merge_all_lineages(user_id)

    # Compute insights
    insights = await analyzer.compute_insights(graph_data)
    
    duration = time.time() - start_time
    log.info(f"Insights computed in {duration:.2f}s | user={user_id}")

    return LineageInsightsResponse(**insights)


@router.get("/aggregate/search", response_model=NodeSearchResponse)
@handle_errors("search_aggregate_lineage")
async def search_aggregate_lineage(
    query: str = Query(..., description="Search query for node name or ID"),
    user_id: str = Depends(get_current_user),
    merger: LineageMerger = Depends(get_lineage_merger),
    analyzer: LineageAnalyzer = Depends(get_lineage_analyzer),
):
    """
    Search for nodes in the aggregate lineage and get their upstream/downstream paths.

    Args:
        query: Search query
        user_id: Current user ID
        merger: Lineage merger service
        analyzer: Lineage analyzer service

    Returns:
        Matched nodes with their full upstream and downstream path analysis
    """
    # Get merged graph
    graph_data = await merger.merge_all_lineages(user_id)

    # Search and analyze paths
    search_results = await analyzer.search_node_with_paths(graph_data, query)

    return NodeSearchResponse(**search_results)


@router.post("/aggregate/filter", response_model=AggregateLineageResponse)
@handle_errors("filter_aggregate_lineage")
async def filter_aggregate_lineage(
    request: FilterAggregateRequest = Body(...),
    user_id: str = Depends(get_current_user),
    merger: LineageMerger = Depends(get_lineage_merger),
):
    """
    Filter aggregate lineage to only show nodes/edges from specific source files.

    Args:
        request: Filter request with file IDs and options
        user_id: Current user ID
        merger: Lineage merger service

    Returns:
        Filtered lineage graph
    """
    # Get full merged graph
    graph_data = await merger.merge_all_lineages(
        user_id, include_file_dependencies=request.include_file_dependencies
    )

    # Filter by source files
    filtered_data = await merger.filter_by_sources(graph_data, request.file_ids)

    return AggregateLineageResponse(**filtered_data)


@router.get("/aggregate/migration-order")
@handle_errors("get_migration_order")
async def get_migration_order(
    user_id: str = Depends(get_current_user),
    merger: LineageMerger = Depends(get_lineage_merger),
    planner: MigrationPlanner = Depends(get_migration_planner),
):
    """
    Get recommended migration order using topological sort.

    Args:
        user_id: Current user ID
        merger: Lineage merger service
        planner: Migration planner service

    Returns:
        Migration order with waves and rationale
    """
    # Get merged graph
    graph_data = await merger.merge_all_lineages(user_id)

    # Compute migration order
    order = await planner.compute_migration_order(graph_data)

    return order


@router.get("/aggregate/export")
@handle_errors("export_aggregate_lineage")
async def export_aggregate_lineage(
    format: str = Query("json", description="Export format: json, graphml, csv"),
    user_id: str = Depends(get_current_user),
    merger: LineageMerger = Depends(get_lineage_merger),
    exporter: LineageExporter = Depends(get_lineage_exporter),
):
    """
    Export aggregate lineage in various formats.

    Args:
        format: Export format (json, graphml, csv)
        user_id: Current user ID
        merger: Lineage merger service
        exporter: Lineage exporter service

    Returns:
        Exported lineage data
    """
    # Get merged graph
    graph_data = await merger.merge_all_lineages(user_id)
    
    # Use the exporter service to export the graph (sync method)
    content, media_type, filename = exporter.export_graph(graph_data, format, user_id)
    
    # Return Response with proper headers
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# Individual Lineage Endpoints
# NOTE: These routes come AFTER /aggregate/* routes to avoid path collisions


@router.get("/{lineage_id}/graph", response_model=LineageGraphResponse)
async def get_lineage_graph(
    lineage_id: str,
    user_id: str = Depends(get_current_user),
    lineage: LineageService = Depends(get_lineage_service),
):
    """
    Get lineage graph data.

    Args:
        lineage_id: Lineage identifier
        user_id: Current user ID
        lineage: Lineage service

    Returns:
        Lineage graph data
    """
    try:
        graph_data = await lineage.get_lineage_graph(lineage_id, user_id)
        return LineageGraphResponse(**graph_data)

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Lineage not found")
    except Exception as e:
        log.error(f"Failed to get lineage graph: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{lineage_id}/export")
async def export_lineage(
    lineage_id: str,
    format: str = "json",
    user_id: str = Depends(get_current_user),
    lineage: LineageService = Depends(get_lineage_service),
):
    """
    Export lineage in specified format.

    Args:
        lineage_id: Lineage identifier
        format: Export format (json, graphml, gexf)
        user_id: Current user ID
        lineage: Lineage service

    Returns:
        Exported lineage data
    """
    try:
        export_data = await lineage.export_lineage(lineage_id, user_id, format)
        return export_data

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Lineage not found")
    except Exception as e:
        log.error(f"Failed to export lineage: {e}")
        raise HTTPException(status_code=500, detail=str(e))


