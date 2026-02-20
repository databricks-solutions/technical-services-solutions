"""
Lineage Analyzer Service for computing insights from lineage graphs.

This is a PURE FUNCTION SERVICE - receives graph data and processes it in-memory.
Does NOT perform any I/O or re-merging operations.
"""

import hashlib
import json
from collections import defaultdict
from typing import Any, Dict, List, Optional

import networkx as nx

from migration_accelerator.app.services.cache_service import CacheService, get_cache_service
from migration_accelerator.app.services.edge_relationship_helper import EdgeRelationshipHelper
from migration_accelerator.app.services.node_type_helper import NodeTypeHelper
from migration_accelerator.utils.logger import get_logger

log = get_logger()


class LineageAnalyzer:
    """
    Service for analyzing lineage graphs and computing insights.
    
    PURE FUNCTION SERVICE: Receives graph_data from LineageMerger (cached)
    and performs analysis in-memory. Does NOT perform any I/O.
    
    Optimization: Caches NetworkX graph to avoid rebuilding it for multiple
    operations (insights, search).
    """
    
    def __init__(self, cache_service: Optional[CacheService] = None):
        """
        Initialize lineage analyzer.
        
        Args:
            cache_service: Optional cache service (uses singleton if not provided)
        """
        self.cache = cache_service or get_cache_service()
    
    async def compute_insights(self, graph_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compute insights from aggregate lineage graph.
        
        Uses cached NetworkX graph if available (built once, reused).
        Optimized: Single pass through edges for all table patterns.
        
        Args:
            graph_data: Graph data with nodes and edges
        
        Returns:
            Dictionary with insights including most connected nodes, orphans, statistics
        """
        nodes = graph_data.get("nodes", [])
        edges = graph_data.get("edges", [])

        if not nodes:
            return {
                "most_connected": [],
                "orphaned_nodes": [],
                "total_nodes": 0,
                "total_edges": 0,
                "node_types": {},
                "relationship_types": {},
                "total_files": 0,
                "total_tables": 0,
                "tables_only_read": [],
                "tables_never_read": [],
                "tables_with_deletes": [],
                "tables_with_drops": [],
            }

        # Build NetworkX graph (cached)
        G = self._get_or_build_nx_graph(graph_data)

        # Create node lookup dict
        nodes_dict = {node["id"]: node for node in nodes}

        # Calculate degree centrality (most connected TABLE_OR_VIEW nodes only)
        degree_dict = dict(G.degree())
        most_connected_raw = sorted(
            [
                {
                    "node_id": node_id,
                    "name": nodes_dict.get(node_id, {}).get("name", node_id),
                    "type": nodes_dict.get(node_id, {}).get("type", "Unknown"),
                    "connection_count": degree,
                }
                for node_id, degree in degree_dict.items()
                if nodes_dict.get(node_id, {}).get("type") != "FILE"  # Exclude FILE nodes
            ],
            key=lambda x: x["connection_count"],
            reverse=True,
        )[:10]

        # Enhance most_connected with file references
        most_connected = []
        for node_info in most_connected_raw:
            node_id = node_info["node_id"]
            
            # Use helper to get file references
            creator_files = EdgeRelationshipHelper.get_creating_files(edges, node_id, nodes_dict)
            reads_from_files = EdgeRelationshipHelper.get_reading_files(edges, node_id, nodes_dict)
            writes_to_files = EdgeRelationshipHelper.get_writing_files(edges, node_id, nodes_dict)
            
            # Add file_references to node info
            node_info["file_references"] = {
                "creator_files": creator_files,
                "reads_from_files": reads_from_files,
                "writes_to_files": writes_to_files,
            }
            
            most_connected.append(node_info)

        # Find orphaned nodes (0 connections)
        orphaned = [
            {
                "node_id": node_id,
                "name": nodes_dict.get(node_id, {}).get("name", node_id),
                "type": nodes_dict.get(node_id, {}).get("type", "Unknown"),
            }
            for node_id, degree in degree_dict.items()
            if degree == 0
        ]

        # Count by node type
        node_types = defaultdict(int)
        for node in nodes:
            node_type = node.get("type", "Unknown")
            node_types[node_type] += 1
        
        # Get counts using NodeTypeHelper
        counts = NodeTypeHelper.count_by_type(nodes)
        total_files = counts['files']
        total_tables = counts['tables']

        # Count by relationship type
        relationship_types = defaultdict(int)
        for edge in edges:
            relationship_types[edge.get("relationship", "DEPENDS_ON")] += 1

        # Analyze tables/views by operation types
        table_operations = EdgeRelationshipHelper.categorize_table_operations(edges, nodes_dict)

        # Find tables with only reads (no CREATE/WRITE/DELETE/DROP)
        tables_only_read = [
            {
                "node_id": table_id,
                "name": nodes_dict[table_id].get("name", table_id),
                "type": nodes_dict[table_id].get("type", "TABLE_OR_VIEW"),
            }
            for table_id, ops in table_operations.items()
            if ops["reads"] > 0 and ops["writes"] == 0 and ops["deletes"] == 0 and ops["drops"] == 0
        ]

        # Find tables never read (sink nodes)
        tables_never_read = [
            {
                "node_id": table_id,
                "name": nodes_dict[table_id].get("name", table_id),
                "type": nodes_dict[table_id].get("type", "TABLE_OR_VIEW"),
            }
            for table_id, ops in table_operations.items()
            if ops["reads"] == 0 and (ops["writes"] > 0 or ops["deletes"] > 0 or ops["drops"] > 0)
        ]

        # Find tables with destructive operations
        tables_with_deletes = [
            {
                "node_id": table_id,
                "name": nodes_dict[table_id].get("name", table_id),
                "type": nodes_dict[table_id].get("type", "TABLE_OR_VIEW"),
                "delete_count": ops["deletes"],
            }
            for table_id, ops in table_operations.items()
            if ops["deletes"] > 0
        ]

        tables_with_drops = [
            {
                "node_id": table_id,
                "name": nodes_dict[table_id].get("name", table_id),
                "type": nodes_dict[table_id].get("type", "TABLE_OR_VIEW"),
                "drop_count": ops["drops"],
            }
            for table_id, ops in table_operations.items()
            if ops["drops"] > 0
        ]

        log.info(
            f"Computed insights: {len(most_connected)} most connected, {len(orphaned)} orphaned, "
            f"{len(tables_only_read)} only-read tables, {len(tables_never_read)} never-read tables"
        )

        return {
            "most_connected": most_connected,
            "orphaned_nodes": orphaned,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "node_types": dict(node_types),
            "relationship_types": dict(relationship_types),
            "total_files": total_files,
            "total_tables": total_tables,
            "tables_only_read": tables_only_read,
            "tables_never_read": tables_never_read,
            "tables_with_deletes": tables_with_deletes,
            "tables_with_drops": tables_with_drops,
        }
    
    async def search_node_with_paths(
        self, graph_data: Dict[str, Any], query: str
    ) -> Dict[str, Any]:
        """
        Search for nodes matching query and compute their upstream/downstream paths.
        
        Reuses cached NetworkX graph if insights was called first.
        
        Args:
            graph_data: Graph data with nodes and edges
            query: Search query (node name or ID)
        
        Returns:
            Dictionary with matched nodes and their paths
        """
        nodes = graph_data.get("nodes", [])
        edges = graph_data.get("edges", [])

        if not nodes:
            return {"matched_nodes": [], "paths": []}

        # Search for matching nodes (case-insensitive substring match)
        query_lower = query.lower()
        matched_nodes = [
            node
            for node in nodes
            if query_lower in node.get("name", "").lower()
            or query_lower in node.get("id", "").lower()
        ]

        if not matched_nodes:
            log.info(f"No nodes matched query: {query}")
            return {"matched_nodes": [], "paths": []}

        # Build NetworkX graph (cached)
        G = self._get_or_build_nx_graph(graph_data)

        # For each matched node, compute upstream and downstream paths
        paths = []

        for matched_node in matched_nodes:
            node_id = matched_node["id"]

            # Find all upstream nodes (ancestors)
            try:
                upstream = list(nx.ancestors(G, node_id))
            except nx.NetworkXError:
                upstream = []

            # Find all downstream nodes (descendants)
            try:
                downstream = list(nx.descendants(G, node_id))
            except nx.NetworkXError:
                downstream = []

            # Calculate centrality score
            try:
                degree_centrality = nx.degree_centrality(G)
                centrality_score = degree_centrality.get(node_id, 0.0)
            except:
                centrality_score = 0.0

            # Get all edges in the upstream/downstream subgraph
            affected_nodes = {node_id} | set(upstream) | set(downstream)
            affected_edges = [
                edge
                for edge in edges
                if edge["source"] in affected_nodes
                and edge["target"] in affected_nodes
            ]

            # Create enhanced node information with roles
            nodes_with_roles = []
            
            # Add matched node
            matched_with_role = dict(matched_node)
            matched_with_role["node_role"] = "matched"
            matched_with_role["centrality_score"] = centrality_score
            nodes_with_roles.append(matched_with_role)
            
            # Add upstream nodes
            for upstream_id in upstream:
                upstream_node = next((n for n in nodes if n["id"] == upstream_id), None)
                if upstream_node:
                    node_with_role = dict(upstream_node)
                    node_with_role["node_role"] = "upstream"
                    nodes_with_roles.append(node_with_role)
            
            # Add downstream nodes
            for downstream_id in downstream:
                downstream_node = next((n for n in nodes if n["id"] == downstream_id), None)
                if downstream_node:
                    node_with_role = dict(downstream_node)
                    node_with_role["node_role"] = "downstream"
                    nodes_with_roles.append(node_with_role)

            paths.append(
                {
                    "matched_node": matched_node,
                    "upstream_nodes": upstream,
                    "downstream_nodes": downstream,
                    "connection_count": len(upstream) + len(downstream),
                    "affected_edges": affected_edges,
                    "centrality_score": centrality_score,
                    "nodes_with_roles": nodes_with_roles,
                }
            )

        log.info(f"Search found {len(matched_nodes)} nodes matching '{query}'")

        return {"matched_nodes": matched_nodes, "paths": paths}
    
    def _get_or_build_nx_graph(self, graph_data: Dict[str, Any]) -> nx.DiGraph:
        """
        Get cached NetworkX graph or build it once.
        
        This prevents rebuilding the graph for every operation.
        Cache key is based on graph data hash.
        
        Args:
            graph_data: Graph data with nodes and edges
        
        Returns:
            NetworkX DiGraph
        """
        # Use graph_data hash as cache key
        data_hash = hashlib.md5(
            json.dumps(graph_data.get("stats", {})).encode()
        ).hexdigest()[:12]
        
        cache_key = f"nx_graph:{data_hash}"
        cached_graph = self.cache.get(cache_key)
        
        if cached_graph:
            log.debug(f"Using cached NetworkX graph: {cache_key}")
            return cached_graph
        
        # Build graph
        log.debug(f"Building NetworkX graph: {cache_key}")
        G = nx.DiGraph()
        
        for node in graph_data.get("nodes", []):
            G.add_node(node["id"], **node)
        
        for edge in graph_data.get("edges", []):
            G.add_edge(edge["source"], edge["target"], **edge)
        
        # Cache for 1 hour
        self.cache.set(cache_key, G, ttl=3600)
        
        return G

