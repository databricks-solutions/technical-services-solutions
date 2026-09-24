"""
Request models for API endpoints.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class AnalyzerUploadRequest(BaseModel):
    """Request model for analyzer file upload."""

    dialect: str = Field(
        ...,
        description="Analyzer dialect for uploads: sql or informatica only",
        examples=["sql"],
    )


class LineageCreateRequest(BaseModel):
    """Request model for creating lineage visualization."""

    analyzer_id: str = Field(..., description="Analyzer ID")
    sheet_name: str = Field(..., description="Sheet name containing lineage data")
    format: str = Field(
        default="cross_reference",
        description="Data format (matrix or cross_reference)",
    )
    source_column: Optional[str] = Field(
        None, description="Source column name for cross-reference format"
    )
    target_column: Optional[str] = Field(
        None, description="Target column name for cross-reference format"
    )
    relationship_column: Optional[str] = Field(
        None, description="Relationship type column name"
    )
    script_column: Optional[str] = Field(
        None, description="Script column name for matrix format"
    )


class ExportRequest(BaseModel):
    """Request model for exporting data."""

    resource_type: str = Field(..., description="Type of resource (lineage, metrics)")
    resource_id: str = Field(..., description="Resource ID")
    format: str = Field(
        default="json", description="Export format (json, csv, graphml, gexf)"
    )


class FilterAggregateRequest(BaseModel):
    """Request model for filtering aggregate lineage."""
    file_ids: List[str] = Field(..., description="List of file IDs to filter by")
    include_file_dependencies: bool = Field(
        default=False,
        description="Include FILE->FILE dependency edges derived from table lineage"
    )
