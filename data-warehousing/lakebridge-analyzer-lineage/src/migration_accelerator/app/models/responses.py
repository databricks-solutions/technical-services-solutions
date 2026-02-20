"""
Response models for API endpoints.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Error response model."""

    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Detailed error information")
    type: Optional[str] = Field(None, description="Error type")


class UploadResponse(BaseModel):
    """Response for file upload."""

    analyzer_id: str = Field(..., description="Unique analyzer ID")
    filename: str = Field(..., description="Original filename")
    dialect: str = Field(..., description="Analyzer dialect")
    file_size: int = Field(..., description="File size in bytes")
    sheets: List[str] = Field(..., description="Available sheets in the file")
    created_at: str = Field(..., description="Upload timestamp")
    lineages: List[Dict[str, Any]] = Field(default=[], description="Auto-generated lineages")


class MetricsResponse(BaseModel):
    """Response for analyzer metrics."""

    analyzer_id: str
    dialect: str
    metrics: Dict[str, Any] = Field(..., description="Key metrics extracted")
    sheet_name: str = Field(..., description="Sheet name used for extraction")


class ComplexityResponse(BaseModel):
    """Response for complexity breakdown."""

    analyzer_id: str
    complexity: Dict[str, int] = Field(..., description="Complexity categorization")
    total: int = Field(..., description="Total count")
    sheet_name: str


class AnalyzerResponse(BaseModel):
    """Response for analyzer information."""

    analyzer_id: str
    filename: str
    dialect: str
    sheets: List[str]
    file_size: int
    created_at: str
    metrics: Optional[Dict[str, Any]] = None
    complexity: Optional[Dict[str, int]] = None
    lineages: List[Dict[str, Any]] = Field(default=[], description="Associated lineages")


class LineageResponse(BaseModel):
    """Response for lineage creation."""

    lineage_id: str = Field(..., description="Unique lineage ID")
    analyzer_id: str
    nodes_count: int = Field(..., description="Number of nodes in graph")
    edges_count: int = Field(..., description="Number of edges in graph")
    node_types: Dict[str, int] = Field(..., description="Node types breakdown")
    relationship_types: Dict[str, int] = Field(
        ..., description="Relationship types breakdown"
    )
    enhanced_with_llm: bool = Field(..., description="Whether LLM enhancement was used")
    created_at: str


class LineageGraphResponse(BaseModel):
    """Response for lineage graph data."""

    lineage_id: str
    nodes: List[Dict[str, Any]] = Field(..., description="Graph nodes")
    edges: List[Dict[str, Any]] = Field(..., description="Graph edges")
    stats: Dict[str, Any] = Field(..., description="Graph statistics")


class QueryResponse(BaseModel):
    """Response for LLM query."""

    question: str = Field(..., description="Original question")
    answer: str = Field(..., description="LLM answer")
    sources: Optional[List[str]] = Field(None, description="Data sources used")
    confidence: Optional[float] = Field(None, description="Confidence score")


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(..., description="Service status")
    version: str = Field(..., description="App version")
    storage_backend: str = Field(..., description="Storage backend in use")
    llm_endpoint: str = Field(..., description="LLM endpoint")


class AggregateLineageResponse(BaseModel):
    """Response for aggregate lineage graph (merged from all user files)."""

    nodes: List[Dict[str, Any]] = Field(..., description="Merged graph nodes with source tracking")
    edges: List[Dict[str, Any]] = Field(..., description="Merged graph edges with source tracking")
    stats: Dict[str, Any] = Field(..., description="Statistics about the merged graph")


class LineageInsightsResponse(BaseModel):
    """Response for lineage insights and analytics.
    
    most_connected includes file_references structure:
    {
        "node_id": str,
        "name": str,
        "type": str,
        "connection_count": int,
        "file_references": {
            "creator_files": [{"file_id": str, "filename": str}, ...],
            "reads_from_files": [{"file_id": str, "filename": str}, ...],
            "writes_to_files": [{"file_id": str, "filename": str}, ...]
        }
    }
    """

    most_connected: List[Dict[str, Any]] = Field(
        ..., description="Top 10 most connected nodes with connection counts and file references"
    )
    orphaned_nodes: List[Dict[str, Any]] = Field(
        ..., description="Nodes with no connections"
    )
    total_nodes: int = Field(..., description="Total number of nodes")
    total_edges: int = Field(..., description="Total number of edges")
    node_types: Dict[str, int] = Field(..., description="Node count by type")
    relationship_types: Dict[str, int] = Field(
        ..., description="Edge count by relationship type"
    )
    total_files: int = Field(..., description="Total number of FILE nodes")
    total_tables: int = Field(..., description="Total number of TABLE_OR_VIEW nodes")
    tables_only_read: List[Dict[str, Any]] = Field(
        ..., description="Tables with only READ operations (no CREATE/WRITE)"
    )
    tables_never_read: List[Dict[str, Any]] = Field(
        ..., description="Tables that are written to but never read (sink nodes)"
    )


class NodeSearchResponse(BaseModel):
    """Response for node search with path analysis."""

    matched_nodes: List[Dict[str, Any]] = Field(
        ..., description="Nodes matching the search query"
    )
    paths: List[Dict[str, Any]] = Field(
        ..., description="Path analysis for each matched node including upstream/downstream"
    )


class MigrationOrderResponse(BaseModel):
    """Response for migration order computation with grouped structure.
    
    Groups files into logical migration units based on shared table dependencies.
    Each group contains multiple waves ordered by file-to-file dependencies.
    
    Each wave node includes:
    - node_id, name, type: Basic node information
    - upstream_count, downstream_count: File-to-file dependencies
    - upstream_files, downstream_files: Names of dependent files
    - pre_existing_tables: List of table names that must exist before migration
    - pre_existing_table_count: Count of pre-existing table dependencies
    - rationale: Human-readable explanation of dependencies
    - source_files: Original source files this node came from
    """
    
    groups: List[Dict[str, Any]] = Field(
        ..., description="Migration groups with ordered waves"
    )
    total_nodes: int = Field(..., description="Total number of FILE nodes")
    total_groups: int = Field(..., description="Total number of migration groups")
    has_cycles: bool = Field(..., description="Whether circular dependencies exist")
    cycle_info: Optional[str] = Field(None, description="Information about cycles if detected")
    pre_existing_tables: List[Dict[str, Any]] = Field(
        default=[],
        description="Tables referenced but never created (must exist before migration)"
    )
    table_dependencies: Dict[str, Any] = Field(
        default={},
        description="Summary of table creation and reference patterns"
    )


