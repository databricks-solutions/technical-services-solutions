"""
Lineage service for creating and managing data lineage visualizations.

Supports both Unity Catalog (via Databricks SDK) and local filesystem storage.
"""

import io
import json
import os
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd

from migration_accelerator.app.constants import Dialect
from migration_accelerator.app.services.edge_relationship_helper import (
    EdgeRelationshipHelper,
)
from migration_accelerator.app.services.node_type_helper import NodeTypeHelper
from migration_accelerator.configs.modules import AnalyzerConfig, LLMConfig
from migration_accelerator.discovery.analyzer.base import SourceAnalyzer
from migration_accelerator.discovery.lineage_visualizer import DataLineageVisualizer
from migration_accelerator.utils.logger import get_logger

log = get_logger()


class ColumnRole(Enum):
    """Role of column in lineage cross-reference data."""
    SOURCE = "source"
    TARGET = "target"


class LineageService:
    """Service for lineage visualization operations with Unity Catalog support."""

    def __init__(self, llm_endpoint: Optional[str] = None, storage_path: str = "/tmp"):
        """
        Initialize lineage service.

        Args:
            llm_endpoint: LLM endpoint name (optional)
            storage_path: Path to store lineage artifacts
        """
        self.llm_endpoint = llm_endpoint
        self.llm_config = None
        self.databricks_client = None
        
        # Determine if we're using Unity Catalog
        from migration_accelerator.app.config import StorageBackend
        from migration_accelerator.app import config
        self.storage_backend = config.settings.storage_backend
        
        # Store paths as strings for UC, Path objects for local
        if self.storage_backend == StorageBackend.UNITY_CATALOG:
            self.storage_path = f"{storage_path}/lineage"
            self._init_databricks_client()
        else:
            self.storage_path = Path(storage_path) / "lineage"
            self.storage_path.mkdir(parents=True, exist_ok=True)

        if llm_endpoint:
            self.llm_config = LLMConfig(
                endpoint_name=llm_endpoint, temperature=0.1, max_tokens=2000
            )

    def _init_databricks_client(self) -> None:
        """Initialize Databricks client for Unity Catalog operations using service principal."""
        try:
            from databricks.sdk import WorkspaceClient
            
            # Use service principal credentials from environment
            self.databricks_client = WorkspaceClient()
            log.info("Lineage service using service principal for UC")
            
            # Ensure lineage directory exists in UC
            try:
                self.databricks_client.files.create_directory(self.storage_path)
                log.info(f"Lineage storage ready in UC: {self.storage_path}")
            except Exception:
                pass  # Directory might already exist
        except Exception as e:
            log.error(f"Failed to initialize Databricks client for lineage: {e}")
            raise

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
        log.debug(f"User path validated for {operation}: user={user_id}")

    def _get_user_lineage_path(self, user_id: str, lineage_id: str) -> Union[str, Path]:
        """
        Get the full path to a lineage file for a specific user.
        
        Args:
            user_id: User identifier
            lineage_id: Lineage identifier
            
        Returns:
            Path to lineage file (string for UC, Path object for local)
        """
        self._validate_user_path(user_id, "get_lineage_path")
        
        if self.storage_backend.value == "unity_catalog":
            return f"{self.storage_path}/{user_id}/{lineage_id}.json"
        else:
            return self.storage_path / user_id / f"{lineage_id}.json"

    def _ensure_user_lineage_directory(self, user_id: str) -> None:
        """
        Ensure user's lineage directory exists.
        
        Args:
            user_id: User identifier
        """
        self._validate_user_path(user_id, "ensure_directory")
        
        if self.storage_backend.value == "unity_catalog":
            user_path = f"{self.storage_path}/{user_id}"
            try:
                self.databricks_client.files.create_directory(user_path)
                log.debug(f"Ensured UC lineage directory: {user_path}")
            except Exception:
                pass  # Directory might already exist
        else:
            user_path = self.storage_path / user_id
            user_path.mkdir(parents=True, exist_ok=True)
            log.debug(f"Ensured local lineage directory: {user_path}")

    async def create_lineage_from_analyzer(
        self,
        file_path: str,
        dialect: str,
        sheet_name: Union[str, List[str]],
        user_id: str,
        format: str = "cross_reference",
        source_column: Optional[str] = None,
        target_column: Optional[str] = None,
        relationship_column: Optional[str] = None,
        script_column: Optional[str] = None,
        enhance_with_llm: bool = False,
        additional_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create lineage visualization from analyzer file.

        Args:
            file_path: Path to analyzer file
            dialect: Analyzer dialect
            sheet_name: Sheet name or list of sheet names containing lineage data
            user_id: User identifier for storage isolation
            format: Data format (matrix or cross_reference)
            source_column: Source column for cross-reference format
            target_column: Target column for cross-reference format
            relationship_column: Relationship column for cross-reference format
            script_column: Script column for matrix format
            enhance_with_llm: Whether to use LLM enhancement
            additional_context: Additional context for LLM

        Returns:
            Lineage information dictionary
        """
        import tempfile
        from migration_accelerator.app.config import StorageBackend
        
        try:
            # If using Unity Catalog, download file to temp location first
            local_file_path = file_path
            temp_file = None
            
            if self.storage_backend == StorageBackend.UNITY_CATALOG:
                # Download from UC to temp file using service principal
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=Path(file_path).suffix)
                temp_file.close()
                
                download_response = self.databricks_client.files.download(file_path)
                with open(temp_file.name, 'wb') as f:
                    f.write(download_response.contents.read())
                
                local_file_path = temp_file.name
                log.info(f"Downloaded UC file to temp location: {local_file_path}")
            
            # Load data from analyzer
            analyzer_config = AnalyzerConfig(analyzer_file=local_file_path, dialect=dialect)
            analyzer = SourceAnalyzer(analyzer_config)
            
            # Convert single sheet to list for unified processing
            sheet_names = [sheet_name] if isinstance(sheet_name, str) else sheet_name
            
            log.info(f"Processing {len(sheet_names)} sheet(s): {sheet_names}")

            # Import lineage configuration to determine parser type
            from migration_accelerator.app.services.lineage_config import get_lineage_config
            
            lineage_config = get_lineage_config(dialect)
            
            # Use dialect-specific parsing based on configuration
            if lineage_config.parser_type == "sql" and format == "cross_reference":
                from migration_accelerator.app.services.sql_lineage_parser import SQLLineageParser
                
                log.info("Using SQL-specific lineage parsing for multiple sheets")
                
                # Merge data from all sheets
                merged_nodes = {}
                merged_edges = []
                
                for sheet in sheet_names:
                    df = analyzer.get_sheet(sheet)
                    log.info(f"Loaded sheet '{sheet}' with {len(df)} rows")
                    
                    parsed_data = SQLLineageParser.parse_program_object_xref(df)
                    
                    # Merge nodes (deduplicate by ID)
                    for node in parsed_data["nodes"]:
                        if node["id"] not in merged_nodes:
                            merged_nodes[node["id"]] = node
                    
                    # Combine all edges
                    merged_edges.extend(parsed_data["edges"])
                
                # Collect statistics from merged data using NodeTypeHelper
                counts = NodeTypeHelper.count_by_type(list(merged_nodes.values()))
                
                log.info(
                    f"Merged {len(merged_nodes)} unique nodes and "
                    f"{len(merged_edges)} edges from {len(sheet_names)} sheet(s)"
                )
                log.info(f"  → Total UNIQUE Files: {counts['files']}")
                log.info(f"  → Total UNIQUE Tables/Views: {counts['tables']}")
                
                # Analyze tables/views by operation types using helper
                table_operations = EdgeRelationshipHelper.categorize_table_operations(
                    merged_edges, merged_nodes
                )
                
                # Find tables with only reads (no CREATE/WRITE/DELETE)
                tables_only_read = [
                    merged_nodes[table_id]["label"]
                    for table_id, ops in table_operations.items()
                    if ops["reads"] > 0 and ops["writes"] == 0 and ops["deletes"] == 0 and ops["drops"] == 0
                ]
                
                # Find tables never read (sink nodes)
                tables_never_read = [
                    merged_nodes[table_id]["label"]
                    for table_id, ops in table_operations.items()
                    if ops["reads"] == 0 and (ops["writes"] > 0 or ops["deletes"] > 0 or ops["drops"] > 0)
                ]
                
                # Find tables with destructive operations
                tables_with_deletes = [
                    merged_nodes[table_id]["label"]
                    for table_id, ops in table_operations.items()
                    if ops["deletes"] > 0
                ]
                
                tables_with_drops = [
                    merged_nodes[table_id]["label"]
                    for table_id, ops in table_operations.items()
                    if ops["drops"] > 0
                ]
                
                log.info(f"  → Tables/Views ONLY READ (no modifications): {len(tables_only_read)}")
                if tables_only_read:
                    log.info(f"    Examples: {', '.join(tables_only_read[:5])}")
                
                log.info(f"  → Tables/Views NEVER READ (sink nodes): {len(tables_never_read)}")
                if tables_never_read:
                    log.info(f"    Examples: {', '.join(tables_never_read[:5])}")
                
                log.info(f"  → Tables/Views with DESTRUCTIVE operations (DELETE/TRUNCATE): {len(tables_with_deletes)}")
                if tables_with_deletes:
                    log.info(f"    Examples: {', '.join(tables_with_deletes[:5])}")
                
                log.info(f"  → Tables/Views with DROP operations: {len(tables_with_drops)}")
                if tables_with_drops:
                    log.info(f"    Examples: {', '.join(tables_with_drops[:5])}")
                
                # Create visualizer and add merged data
                visualizer = DataLineageVisualizer(
                    llm_config=self.llm_config if enhance_with_llm else None,
                    enable_llm_enhancement=enhance_with_llm,
                )
                
                # Add nodes and edges from merged data
                # Use internal methods to properly track nodes in both graph and nodes dict
                for node in merged_nodes.values():
                    visualizer._add_node(
                        node_id=node["id"],
                        node_type=node["type"],
                        properties={"label": node["label"]}
                    )
                
                for edge in merged_edges:
                    visualizer._add_edge(
                        source=edge["source"],
                        target=edge["target"],
                        relationship=edge["relationship"],
                        properties={}
                    )
                
                log.info(
                    f"Added {len(merged_nodes)} nodes and "
                    f"{len(merged_edges)} edges to visualizer"
                )
                
            # Parse lineage based on format (for non-SQL or other formats)
            elif format == "cross_reference":
                # Create visualizer
                visualizer = DataLineageVisualizer(
                    llm_config=self.llm_config if enhance_with_llm else None,
                    enable_llm_enhancement=enhance_with_llm,
                )
                
                # Process first sheet only for non-SQL dialects (backward compatibility)
                df = analyzer.get_sheet(sheet_names[0])
                log.info(f"Loaded sheet '{sheet_names[0]}' with {len(df)} rows")
                
                # Use default column names if not provided
                if not source_column:
                    source_column = self._infer_source_column(df, dialect)
                if not target_column:
                    target_column = self._infer_target_column(df, dialect)

                visualizer.parse_cross_reference_dataframe(
                    df=df,
                    source_column=source_column,
                    target_column=target_column,
                    relationship_column=relationship_column,
                    default_relationship="DEPENDS_ON",
                )
            else:
                # Matrix format
                visualizer = DataLineageVisualizer(
                    llm_config=self.llm_config if enhance_with_llm else None,
                    enable_llm_enhancement=enhance_with_llm,
                )
                
                # Process first sheet only for matrix format (backward compatibility)
                df = analyzer.get_sheet(sheet_names[0])
                log.info(f"Loaded sheet '{sheet_names[0]}' with {len(df)} rows")
                
                if not script_column:
                    script_column = df.columns[0]

                visualizer.parse_dataframe_lineage(
                    df=df, script_column=script_column, relationship_indicator="src"
                )

            # Enhance with LLM if requested
            if enhance_with_llm and self.llm_config:
                log.info("Enhancing lineage with LLM")
                visualizer.enhance_with_llm(additional_context or "")

            # Get statistics
            stats = visualizer.get_lineage_stats()

            # Validate that we have nodes
            if stats["nodes"]["total"] == 0:
                error_msg = (
                    f"No lineage nodes were generated from the data. "
                    f"Sheet(s): {sheet_names}, Format: {format}. "
                    f"This could indicate: (1) Empty or invalid data, "
                    f"(2) Incorrect column mappings, or (3) Unsupported data format. "
                    f"Please verify the data and configuration."
                )
                log.error(error_msg)
                raise ValueError(error_msg)

            # Generate unique lineage ID
            lineage_id = str(uuid.uuid4())

            # Save lineage data
            lineage_data = {
                "lineage_id": lineage_id,
                "user_id": user_id,
                "created_at": datetime.now().isoformat(),
                "dialect": dialect,
                "sheet_name": sheet_name,  # Keep as-is (str or list) for metadata
                "sheet_names": sheet_names,  # Also track the list version
                "format": format,
                "enhanced_with_llm": enhance_with_llm,
                "stats": stats,
            }

            # Export graph data
            graph_data = visualizer.export_graph(format="json")
            lineage_data["graph"] = graph_data

            # Ensure user's lineage directory exists
            self._ensure_user_lineage_directory(user_id)

            # Save to file (UC or local) with per-user path
            lineage_file_path = self._get_user_lineage_path(user_id, lineage_id)
            
            if self.storage_backend.value == "unity_catalog":
                lineage_content = json.dumps(lineage_data, indent=2).encode()
                # Wrap bytes in BytesIO for SDK
                lineage_obj = io.BytesIO(lineage_content)
                self.databricks_client.files.upload(str(lineage_file_path), lineage_obj, overwrite=True)
            else:
                with open(lineage_file_path, "w") as f:
                    json.dump(lineage_data, f, indent=2)

            log.info(f"Created lineage {lineage_id} for user {user_id} with {stats['nodes']['total']} nodes")

            return {
                "lineage_id": lineage_id,
                "nodes_count": stats["nodes"]["total"],
                "edges_count": stats["edges"]["total"],
                "node_types": stats["nodes"]["by_type"],
                "relationship_types": stats["edges"]["by_relationship"],
                "enhanced_with_llm": enhance_with_llm,
                "created_at": lineage_data["created_at"],
            }

        except Exception as e:
            log.error(f"Failed to create lineage: {e}")
            raise
        finally:
            # Clean up temp file if created
            if temp_file and os.path.exists(temp_file.name):
                os.unlink(temp_file.name)
                log.debug(f"Cleaned up temp file: {temp_file.name}")

    async def get_lineage_graph(self, lineage_id: str, user_id: str) -> Dict[str, Any]:
        """
        Get lineage graph data.

        Args:
            lineage_id: Lineage identifier
            user_id: User identifier for access control

        Returns:
            Graph data dictionary
        """
        try:
            # Get user-specific lineage path
            lineage_file_path = self._get_user_lineage_path(user_id, lineage_id)
            
            if self.storage_backend.value == "unity_catalog":
                try:
                    lineage_content = self.databricks_client.files.download(str(lineage_file_path)).contents.read()
                    lineage_data = json.loads(lineage_content)
                except Exception as e:
                    # Convert SDK "file not found" errors to FileNotFoundError
                    # Check for various indicators that the file doesn't exist
                    error_str = str(e).lower() if e else ""
                    if ("not found" in error_str or "404" in error_str or 
                        "nosuchkey" in error_str or not error_str or error_str == "none"):
                        raise FileNotFoundError(f"Lineage {lineage_id} not found")
                    raise
            else:
                if not lineage_file_path.exists():
                    raise FileNotFoundError(f"Lineage {lineage_id} not found")
                
                with open(lineage_file_path, "r") as f:
                    lineage_data = json.load(f)

            # Verify ownership (user_id in data should match requested user_id)
            stored_user_id = lineage_data.get("user_id")
            if stored_user_id and stored_user_id != user_id:
                log.warning(f"Access denied: user {user_id} attempted to access lineage {lineage_id} owned by {stored_user_id}")
                raise FileNotFoundError(f"Lineage {lineage_id} not found")

            return {
                "lineage_id": lineage_id,
                "nodes": lineage_data["graph"]["nodes"],
                "edges": lineage_data["graph"]["edges"],
                "stats": lineage_data["stats"],
            }

        except FileNotFoundError:
            raise
        except Exception as e:
            log.error(f"Failed to get lineage graph {lineage_id}: {e}")
            raise
    
    async def get_lineage_graphs_batch(
        self, lineage_ids: List[str], user_id: str
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get multiple lineage graphs in batch using async gather.
        
        This eliminates N+1 query pattern by loading all lineages in parallel.
        
        Args:
            lineage_ids: List of lineage identifiers
            user_id: User identifier for access control
        
        Returns:
            Dictionary mapping lineage_id to graph data
        """
        import asyncio
        
        try:
            # Load all lineages in parallel
            tasks = [self.get_lineage_graph(lid, user_id) for lid in lineage_ids]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Build result dict, filtering out errors
            batch_result = {}
            for lineage_id, result in zip(lineage_ids, results):
                if isinstance(result, Exception):
                    log.warning(f"Failed to load lineage {lineage_id}: {result}")
                    continue
                batch_result[lineage_id] = result
            
            log.info(
                f"Batch loaded {len(batch_result)}/{len(lineage_ids)} lineages for user {user_id}"
            )
            return batch_result
        
        except Exception as e:
            log.error(f"Failed to batch load lineages: {e}")
            raise

    async def export_lineage(
        self, lineage_id: str, user_id: str, format: str = "json"
    ) -> Dict[str, Any]:
        """
        Export lineage in specified format.

        Args:
            lineage_id: Lineage identifier
            user_id: User identifier for access control
            format: Export format (json, graphml, gexf)

        Returns:
            Export data
        """
        try:
            # Get user-specific lineage path
            lineage_file_path = self._get_user_lineage_path(user_id, lineage_id)
            
            if self.storage_backend.value == "unity_catalog":
                try:
                    lineage_content = self.databricks_client.files.download(str(lineage_file_path)).contents.read()
                    lineage_data = json.loads(lineage_content)
                except Exception as e:
                    # Convert SDK "file not found" errors to FileNotFoundError
                    error_str = str(e).lower() if e else ""
                    if ("not found" in error_str or "404" in error_str or 
                        "nosuchkey" in error_str or not error_str or error_str == "none"):
                        raise FileNotFoundError(f"Lineage {lineage_id} not found")
                    raise
            else:
                if not lineage_file_path.exists():
                    raise FileNotFoundError(f"Lineage {lineage_id} not found")
                
                with open(lineage_file_path, "r") as f:
                    lineage_data = json.load(f)

            # Verify ownership
            stored_user_id = lineage_data.get("user_id")
            if stored_user_id and stored_user_id != user_id:
                log.warning(f"Access denied: user {user_id} attempted to export lineage {lineage_id} owned by {stored_user_id}")
                raise FileNotFoundError(f"Lineage {lineage_id} not found")

            if format == "json":
                return lineage_data

            # TODO: Implement other formats (GraphML, GEXF) if needed
            return lineage_data

        except Exception as e:
            log.error(f"Failed to export lineage: {e}")
            raise

    def _infer_column(
        self, 
        df: pd.DataFrame, 
        dialect: Dialect, 
        role: ColumnRole
    ) -> str:
        """
        Unified column inference for source and target columns.
        
        Args:
            df: DataFrame to infer column from
            dialect: Analyzer dialect enum
            role: Whether inferring source or target column
            
        Returns:
            Inferred column name
        """
        if role == ColumnRole.SOURCE:
            possible_columns = {
                Dialect.TALEND: ["Job_Name", "Job Name", "Source Job"],
                Dialect.SQL: ["Program", "Program_Name", "Script_Name", "Source Program", "SQL_Program"],
                Dialect.INFORMATICA: ["Mapping_Name", "Mapping Name", "Source Mapping"],
            }.get(dialect, [])
            fallback_index = 0
        else:  # TARGET
            possible_columns = {
                Dialect.TALEND: ["Referenced_Object", "Referenced Object", "Target"],
                Dialect.SQL: ["Object", "Referenced_Object", "Object_Name", "Target", "Table_Name"],
                Dialect.INFORMATICA: ["Referenced_Object", "Object_Name", "Target"],
            }.get(dialect, [])
            fallback_index = 1 if len(df.columns) > 1 else 0
        
        # Try exact match
        for col in possible_columns:
            if col in df.columns:
                return col
        
        # Try case-insensitive matching
        for col in possible_columns:
            for df_col in df.columns:
                if col.lower() == df_col.lower():
                    return df_col
        
        # Fallback to index
        return df.columns[fallback_index]
    
    def _infer_source_column(self, df: pd.DataFrame, dialect: str) -> str:
        """
        Infer source column name based on dialect.
        
        Deprecated: Use _infer_column with ColumnRole.SOURCE instead.
        Kept for backwards compatibility.
        """
        # Convert string dialect to enum
        try:
            dialect_enum = Dialect(dialect.lower())
        except ValueError:
            dialect_enum = Dialect.TALEND
        
        return self._infer_column(df, dialect_enum, ColumnRole.SOURCE)

    def _infer_target_column(self, df: pd.DataFrame, dialect: str) -> str:
        """
        Infer target column name based on dialect.
        
        Deprecated: Use _infer_column with ColumnRole.TARGET instead.
        Kept for backwards compatibility.
        """
        # Convert string dialect to enum
        try:
            dialect_enum = Dialect(dialect.lower())
        except ValueError:
            dialect_enum = Dialect.TALEND
        
        return self._infer_column(df, dialect_enum, ColumnRole.TARGET)

    async def delete_lineage(self, lineage_id: str, user_id: str) -> bool:
        """
        Delete a lineage file from storage.

        Args:
            lineage_id: Lineage identifier
            user_id: User identifier for access control

        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            if self.storage_backend.value == "unity_catalog":
                return self._delete_lineage_uc(lineage_id, user_id)
            else:
                return self._delete_lineage_local(lineage_id, user_id)
        except Exception as e:
            log.error(f"Failed to delete lineage {lineage_id}: {e}")
            return False

    def _delete_lineage_uc(self, lineage_id: str, user_id: str) -> bool:
        """Delete lineage file from Unity Catalog."""
        lineage_file_path = self._get_user_lineage_path(user_id, lineage_id)
        
        try:
            self.databricks_client.files.delete(str(lineage_file_path))
            log.info(f"Deleted lineage from UC: {lineage_id} for user {user_id}")
            return True
        except Exception as e:
            # If file doesn't exist, consider it already deleted
            if "not found" in str(e).lower():
                log.info(f"Lineage {lineage_id} not found in UC, considering it deleted")
                return True
            log.warning(f"Failed to delete lineage {lineage_id} from UC: {e}")
            return False

    def _delete_lineage_local(self, lineage_id: str, user_id: str) -> bool:
        """Delete lineage file from local filesystem."""
        lineage_file = self._get_user_lineage_path(user_id, lineage_id)
        
        try:
            if lineage_file.exists():
                lineage_file.unlink()
                log.info(f"Deleted lineage: {lineage_id} for user {user_id}")
                return True
            else:
                log.info(f"Lineage {lineage_id} not found, considering it deleted")
                return True
        except Exception as e:
            log.warning(f"Failed to delete lineage {lineage_id}: {e}")
            return False

    async def delete_lineages_batch(self, lineage_ids: List[str], user_id: str) -> Dict[str, bool]:
        """
        Delete multiple lineage files from storage.

        Args:
            lineage_ids: List of lineage identifiers
            user_id: User identifier for access control

        Returns:
            Dictionary mapping lineage_id to deletion success status
        """
        results = {}
        for lineage_id in lineage_ids:
            results[lineage_id] = await self.delete_lineage(lineage_id, user_id)
        
        successful = sum(1 for success in results.values() if success)
        log.info(f"Deleted {successful}/{len(lineage_ids)} lineages for user {user_id}")
        
        return results


