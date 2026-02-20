"""
Lineage Merger Service for combining multiple lineage graphs.

This service is the ONLY one that performs I/O operations for aggregate lineage.
All other services (LineageAnalyzer, MigrationPlanner, LineageExporter) receive
the merged graph data and operate as pure functions.
"""

import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

from migration_accelerator.app.services.cache_service import (
    CacheService,
    generate_cache_key,
    get_cache_service,
)
from migration_accelerator.app.services.edge_relationship_helper import (
    EdgeRelationshipHelper,
)
from migration_accelerator.app.services.lineage_service import LineageService
from migration_accelerator.app.services.node_type_helper import NodeTypeHelper
from migration_accelerator.app.services.storage_service import StorageService
from migration_accelerator.utils.logger import get_logger

log = get_logger()


class LineageMerger:
    """
    Service for merging multiple lineage graphs into a single aggregate graph.
    
    This is the ONLY service that reads files and performs I/O. It checks cache
    FIRST before any file operations. All other aggregate lineage services receive
    the merged graph_data from this service and process it in-memory.
    
    Caching Strategy:
    - Checks cache before any I/O operations
    - Cache key based on user_id + file_ids (deterministic)
    - Pre-computes file dependencies for instant client-side toggle
    - Other services consume cached data without triggering re-merge
    """
    
    def __init__(
        self,
        storage_service: StorageService,
        lineage_service: LineageService,
        cache_service: Optional[CacheService] = None,
    ):
        """
        Initialize lineage merger.
        
        Args:
            storage_service: Storage service for accessing files
            lineage_service: Lineage service for accessing individual lineages
            cache_service: Optional cache service (uses singleton if not provided)
        """
        self.storage = storage_service
        self.lineage = lineage_service
        self.cache = cache_service or get_cache_service()
    
    async def merge_all_lineages(
        self, user_id: str, include_file_dependencies: bool = False
    ) -> Dict[str, Any]:
        """
        Merge all lineage graphs for a user into a single aggregate graph.
        
        CACHING: Checks cache FIRST before any I/O. On cache hit, returns immediately
        without reading any files. Pre-computes file dependencies for instant toggle.
        
        Args:
            user_id: User identifier
            include_file_dependencies: Whether to include FILE->FILE dependency edges
                                      (pre-computed, just filters result)
        
        Returns:
            Dictionary with:
            - nodes: List of merged nodes with source tracking
            - edges: List of merged edges (includes/excludes file deps based on flag)
            - stats: Statistics about the merged graph
            - compute_time_ms: Time taken to compute/retrieve
            - cached: Whether result came from cache
        """
        start_time = time.time()
        
        log.info(
            f"Merging all lineages for user {user_id} "
            f"(include_file_dependencies={include_file_dependencies})"
        )

        # Get all files for user
        files = self.storage.list_user_files(user_id)
        
        # Generate cache key (independent of include_file_dependencies flag)
        file_ids = [f["file_id"] for f in files]
        cache_key = generate_cache_key(user_id, file_ids, include_deps=False)
        
        # Try to get from cache
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            cache_time_ms = (time.time() - start_time) * 1000
            log.info(f"Cache hit for {cache_key} (took {cache_time_ms:.1f}ms)")
            
            # Filter file dependencies based on flag
            result = self._filter_file_dependencies(cached_result, include_file_dependencies)
            result["compute_time_ms"] = cache_time_ms
            result["cached"] = True
            return result
        
        log.info(f"Cache miss for {cache_key}, computing merge...")

        if not files:
            log.info(f"No files found for user {user_id}")
            return {
                "nodes": [],
                "edges": [],
                "stats": {
                    "total_nodes": 0,
                    "total_edges": 0,
                    "total_files": 0,
                    "files": [],
                },
            }

        # Initialize merged graph structures
        merged_nodes: Dict[str, Dict[str, Any]] = {}  # keyed by node ID
        merged_edges: Dict[str, Dict[str, Any]] = {}  # keyed by edge composite key
        file_sources: List[Dict[str, Any]] = []

        # Process each file
        for file_info in files:
            file_id = file_info["file_id"]
            filename = file_info["filename"]

            # Get metadata for lineages
            metadata = self.storage.get_file_metadata(file_id, user_id)
            if not metadata:
                log.warning(f"No metadata found for file {file_id}")
                continue

            lineages = metadata.get("lineages", [])
            if not lineages:
                log.info(f"No lineages found for file {filename}")
                continue

            # Track this file as a source
            file_source = {
                "file_id": file_id,
                "filename": filename,
                "dialect": metadata.get("dialect", "unknown"),
                "lineage_count": len(lineages),
            }
            file_sources.append(file_source)

            # Process each lineage in the file
            for lineage_ref in lineages:
                lineage_id = lineage_ref.get("lineage_id")
                if not lineage_id:
                    continue

                try:
                    # Get lineage graph data (with user_id for access control)
                    lineage_data = await self.lineage.get_lineage_graph(lineage_id, user_id)

                    # Merge nodes
                    for node in lineage_data.get("nodes", []):
                        node_id = node["id"]

                        if node_id not in merged_nodes:
                            # New node - add with source tracking
                            merged_nodes[node_id] = {
                                "id": node_id,
                                "name": node.get("name", node_id),
                                "type": node.get("type", "Unknown"),
                                "properties": node.get("properties", {}),
                                "sources": [],
                            }

                        # Add source reference
                        merged_nodes[node_id]["sources"].append(
                            {
                                "file_id": file_id,
                                "filename": filename,
                                "lineage_id": lineage_id,
                            }
                        )

                    # Merge edges
                    for edge in lineage_data.get("edges", []):
                        source = edge["source"]
                        target = edge["target"]
                        relationship = edge.get("relationship", "DEPENDS_ON")

                        # Create composite key for deduplication
                        edge_key = f"{source}||{target}||{relationship}"

                        if edge_key not in merged_edges:
                            # New edge - add with source tracking
                            merged_edges[edge_key] = {
                                "source": source,
                                "target": target,
                                "relationship": relationship,
                                "properties": edge.get("properties", {}),
                                "sources": [],
                            }

                        # Add source reference
                        merged_edges[edge_key]["sources"].append(
                            {
                                "file_id": file_id,
                                "filename": filename,
                                "lineage_id": lineage_id,
                            }
                        )

                except Exception as e:
                    log.error(
                        f"Failed to load lineage {lineage_id} from file {filename}: {e}"
                    )
                    continue

        # Convert to lists
        nodes_list = list(merged_nodes.values())
        edges_list = list(merged_edges.values())
        
        # Tag tables with no CREATE relationship as externally created
        tables_with_create = {
            edge["target"] for edge in edges_list if edge["relationship"] == "CREATES"
        }
        
        external_creation_count = 0
        for node in nodes_list:
            # Only check table/view nodes
            if NodeTypeHelper.is_table_node(node):
                # If table has no CREATE edge pointing to it, mark as externally created
                if node["id"] not in tables_with_create:
                    if "properties" not in node:
                        node["properties"] = {}
                    node["properties"]["external_creation"] = True
                    node["properties"]["tags"] = node["properties"].get("tags", [])
                    if "external_creation" not in node["properties"]["tags"]:
                        node["properties"]["tags"].append("external_creation")
                    external_creation_count += 1

        # ALWAYS pre-compute FILE->FILE dependency edges
        log.info("Pre-computing FILE->FILE dependency edges from table lineage...")
        
        file_dependency_edges = self._build_file_dependencies(edges_list, merged_nodes)
        
        file_dependency_edges_count = len(file_dependency_edges)
        log.info(f"Pre-computed {file_dependency_edges_count} FILE->FILE dependency edges")
        
        log.info(
            f"Merged lineage: {len(nodes_list)} nodes, {len(edges_list)} edges from {len(file_sources)} files"
        )
        if external_creation_count > 0:
            log.info(
                f"Tagged {external_creation_count} tables/views with external creation "
                f"(no CREATE statement found in any file)"
            )

        compute_time_ms = (time.time() - start_time) * 1000
        log.info(f"Merge completed in {compute_time_ms:.1f}ms")

        # Store FULL result with file dependencies pre-computed
        full_result = {
            "nodes": nodes_list,
            "edges": edges_list,  # Base edges without file dependencies
            "file_dependency_edges": file_dependency_edges,  # Stored separately
            "stats": {
                "total_nodes": len(nodes_list),
                "total_edges": len(edges_list),
                "total_files": len(file_sources),
                "files": file_sources,
                "file_dependency_edges": file_dependency_edges_count,
            },
            "compute_time_ms": compute_time_ms,
            "cached": False,
        }
        
        # Cache the full result
        self.cache.set(cache_key, full_result)
        log.info(f"Cached result for {cache_key}")
        
        # Filter file dependencies based on request
        return self._filter_file_dependencies(full_result, include_file_dependencies)
    
    async def filter_by_sources(
        self, graph_data: Dict[str, Any], file_ids: List[str]
    ) -> Dict[str, Any]:
        """
        Filter graph to only include nodes/edges from specific source files.
        
        Args:
            graph_data: Full graph data
            file_ids: List of file IDs to filter by
        
        Returns:
            Filtered graph data
        """
        if not file_ids:
            return graph_data

        file_ids_set = set(file_ids)
        nodes = graph_data.get("nodes", [])
        edges = graph_data.get("edges", [])

        # Filter nodes that have at least one source from the file_ids
        filtered_nodes = [
            node
            for node in nodes
            if any(
                source["file_id"] in file_ids_set
                for source in node.get("sources", [])
            )
        ]

        # Get filtered node IDs for edge filtering
        filtered_node_ids = {node["id"] for node in filtered_nodes}

        # Filter edges where both source and target are in filtered nodes
        # AND the edge has at least one source from the file_ids
        filtered_edges = [
            edge
            for edge in edges
            if edge["source"] in filtered_node_ids
            and edge["target"] in filtered_node_ids
            and any(
                source["file_id"] in file_ids_set
                for source in edge.get("sources", [])
            )
        ]

        log.info(
            f"Filtered to {len(filtered_nodes)} nodes, {len(filtered_edges)} edges from {len(file_ids)} files"
        )

        return {
            "nodes": filtered_nodes,
            "edges": filtered_edges,
            "stats": {
                "total_nodes": len(filtered_nodes),
                "total_edges": len(filtered_edges),
                "filtered_by_files": len(file_ids),
            },
        }
    
    def _build_file_dependencies(
        self, edges: List[Dict[str, Any]], nodes_dict: Dict[str, Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Build FILE->FILE dependency edges from table lineage.
        
        If FileA creates TableX and FileB reads TableX, then FileB depends on FileA.
        
        Args:
            edges: List of edge dictionaries
            nodes_dict: Dictionary mapping node IDs to node data
        
        Returns:
            List of FILE->FILE dependency edges
        """
        file_dependency_edges = []
        
        # Build helper maps
        table_creators, table_readers, _ = EdgeRelationshipHelper.build_table_file_maps(
            edges, nodes_dict
        )
        
        # Generate FILE->FILE dependencies
        for table_id in table_creators:
            creator_files = table_creators[table_id]
            reader_files = table_readers.get(table_id, set())
            
            for creator_file in creator_files:
                for reader_file in reader_files:
                    if creator_file != reader_file:
                        # Create a dependency edge: reader depends on creator
                        file_dependency_edges.append({
                            "source": creator_file,
                            "target": reader_file,
                            "relationship": "DEPENDS_ON_FILE",
                            "via_table": table_id,
                            "sources": [],  # Derived edge, not from any specific source
                        })
        
        return file_dependency_edges
    
    def _filter_file_dependencies(
        self, graph_data: Dict[str, Any], include_file_dependencies: bool
    ) -> Dict[str, Any]:
        """
        Filter file dependency edges from graph data.
        
        This is a client-side filter that operates on pre-computed file dependencies,
        making the toggle instant without recomputing the graph.
        
        Args:
            graph_data: Full graph data with pre-computed file dependencies
            include_file_dependencies: Whether to include file dependency edges
        
        Returns:
            Filtered graph data
        """
        result = {
            "nodes": graph_data["nodes"],
            "edges": graph_data["edges"].copy(),  # Start with base edges
            "stats": graph_data["stats"].copy(),
            "compute_time_ms": graph_data.get("compute_time_ms", 0),
            "cached": graph_data.get("cached", False),
        }
        
        if include_file_dependencies:
            # Add pre-computed file dependency edges
            file_dep_edges = graph_data.get("file_dependency_edges", [])
            result["edges"] = result["edges"] + file_dep_edges
            result["stats"]["total_edges"] = len(result["edges"])
        
        return result
    
    def invalidate_cache_for_user(self, user_id: str) -> None:
        """
        Invalidate all cached aggregate lineage data for a user.
        
        Should be called when:
        - Files are uploaded
        - Files are deleted
        - Lineages are regenerated
        
        Args:
            user_id: User identifier
        """
        pattern = f"lineage:aggregate:{user_id}:*"
        count = self.cache.invalidate_pattern(pattern)
        log.info(f"Invalidated {count} cache entries for user {user_id}")




