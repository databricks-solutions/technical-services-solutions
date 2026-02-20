"""
Lineage Exporter Service for exporting graphs in various formats.

This is a PURE FUNCTION SERVICE - receives graph data and processes it in-memory.
Does NOT perform any I/O operations.
"""

import json as json_lib
from io import BytesIO, StringIO
from typing import Any, Dict, Tuple

import networkx as nx

from migration_accelerator.app.constants import ExportFormat
from migration_accelerator.utils.logger import get_logger

log = get_logger()


class LineageExporter:
    """
    Service for exporting lineage data in various formats.
    
    PURE FUNCTION SERVICE: Receives graph_data from LineageMerger (cached)
    and exports it in requested format. Does NOT perform any I/O.
    
    Supports:
    - JSON: Full graph structure with metadata
    - CSV: Edge list with source file information
    - GraphML: NetworkX format for graph visualization tools
    """
    
    def export_graph(
        self,
        graph_data: Dict[str, Any],
        format: ExportFormat,
        user_id: str
    ) -> Tuple[str, str, str]:
        """
        Export graph in specified format.
        
        Args:
            graph_data: Graph data with nodes and edges from LineageMerger
            format: Export format (JSON, CSV, or GRAPHML)
            user_id: User ID for filename generation
        
        Returns:
            Tuple of (content, media_type, filename)
        
        Raises:
            ValueError: If format is not supported
        """
        if format == ExportFormat.JSON:
            return self._export_json(graph_data, user_id)
        elif format == ExportFormat.CSV:
            return self._export_csv(graph_data, user_id)
        elif format == ExportFormat.GRAPHML:
            return self._export_graphml(graph_data, user_id)
        else:
            raise ValueError(f"Unsupported export format: {format}")
    
    def _export_json(
        self,
        graph_data: Dict[str, Any],
        user_id: str
    ) -> Tuple[str, str, str]:
        """
        Export graph as JSON.
        
        Args:
            graph_data: Graph data with nodes and edges
            user_id: User ID for filename
        
        Returns:
            Tuple of (json_content, media_type, filename)
        """
        content = json_lib.dumps(graph_data, indent=2)
        media_type = "application/json"
        filename = f"aggregate-lineage-{user_id}.json"
        
        log.info(f"Exported lineage as JSON for user {user_id}")
        return (content, media_type, filename)
    
    def _export_csv(
        self,
        graph_data: Dict[str, Any],
        user_id: str
    ) -> Tuple[str, str, str]:
        """
        Export graph as CSV edge list.
        
        CSV format:
        Source,Target,Relationship,Source Files
        
        Args:
            graph_data: Graph data with nodes and edges
            user_id: User ID for filename
        
        Returns:
            Tuple of (csv_content, media_type, filename)
        """
        edges = graph_data.get("edges", [])
        lines = ["Source,Target,Relationship,Source Files"]
        
        for edge in edges:
            source = edge.get("source", "")
            target = edge.get("target", "")
            relationship = edge.get("relationship", "")
            sources = edge.get("sources", [])
            source_files = ";".join([s.get("filename", "") for s in sources])
            
            lines.append(
                f'"{source}","{target}","{relationship}","{source_files}"'
            )
        
        content = "\n".join(lines)
        media_type = "text/csv"
        filename = f"aggregate-lineage-{user_id}.csv"
        
        log.info(
            f"Exported lineage as CSV with {len(edges)} edges for user {user_id}"
        )
        return (content, media_type, filename)
    
    def _export_graphml(
        self,
        graph_data: Dict[str, Any],
        user_id: str
    ) -> Tuple[str, str, str]:
        """
        Export graph as GraphML using NetworkX.
        
        GraphML is an XML-based format that can be imported into
        graph visualization tools like Gephi, Cytoscape, etc.
        
        Args:
            graph_data: Graph data with nodes and edges
            user_id: User ID for filename
        
        Returns:
            Tuple of (graphml_content, media_type, filename)
        """
        # Build NetworkX graph
        G = nx.DiGraph()
        
        # Add nodes with attributes
        for node in graph_data.get("nodes", []):
            G.add_node(
                node["id"],
                name=node.get("name", ""),
                type=node.get("type", ""),
            )
        
        # Add edges with attributes
        for edge in graph_data.get("edges", []):
            G.add_edge(
                edge["source"],
                edge["target"],
                relationship=edge.get("relationship", "")
            )
        
        # Write to BytesIO (networkx requires binary mode for GraphML)
        sio = BytesIO()
        nx.write_graphml(G, sio)
        content = sio.getvalue().decode('utf-8')
        media_type = "application/xml"
        filename = f"aggregate-lineage-{user_id}.graphml"
        
        log.info(
            f"Exported lineage as GraphML with {G.number_of_nodes()} nodes "
            f"and {G.number_of_edges()} edges for user {user_id}"
        )
        return (content, media_type, filename)



