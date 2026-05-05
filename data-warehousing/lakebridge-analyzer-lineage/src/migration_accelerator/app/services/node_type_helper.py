"""
Node type helper utility for centralized node type management.

Provides constants, type checking methods, and UI normalization for node types.
"""

from typing import Dict, List, Any


class NodeTypeHelper:
    """
    Centralized node type management with UI normalization.
    
    Backend uses technical constants (FILE, TABLE_OR_VIEW) for consistency.
    UI displays user-friendly names ("File", "Table or View").
    
    NOTE: GLOBAL_TEMP_TABLE has been deprecated and merged into TABLE_OR_VIEW.
    """
    
    # Backend constants (uppercase with underscores)
    FILE = "FILE"
    FLAT_FILE = "FLAT_FILE"
    TABLE_OR_VIEW = "TABLE_OR_VIEW"
    MAPPING = "MAPPING"
    SESSION = "SESSION"
    WORKFLOW = "WORKFLOW"
    MAPPLET = "MAPPLET"

    # All valid types
    ALL_TYPES = {FILE, FLAT_FILE, TABLE_OR_VIEW, MAPPING, SESSION, WORKFLOW, MAPPLET}

    # UI display names (user-friendly)
    DISPLAY_NAMES = {
        FILE: "File",
        FLAT_FILE: "Flat File",
        TABLE_OR_VIEW: "Table or View",
        MAPPING: "Mapping",
        SESSION: "Session",
        WORKFLOW: "Workflow",
        MAPPLET: "Mapplet",
    }
    
    @classmethod
    def is_table_node(cls, node: Dict[str, Any]) -> bool:
        """
        Check if node is a data target (table/view or flat file).

        Flat files (CSV, TXT, XML, etc.) are treated identically to tables
        for migration ordering, dependency analysis, and insights.

        Args:
            node: Node dictionary with 'type' field

        Returns:
            True if node is a table/view or flat file, False otherwise
        """
        return node.get("type") in {cls.TABLE_OR_VIEW, cls.FLAT_FILE}
    
    @classmethod
    def is_file_node(cls, node: Dict[str, Any]) -> bool:
        """
        Check if node is a source file (migration unit).

        Args:
            node: Node dictionary with 'type' field

        Returns:
            True if node is a source file, False otherwise
        """
        return node.get("type") == cls.FILE

    @classmethod
    def is_flat_file_node(cls, node: Dict[str, Any]) -> bool:
        """
        Check if node is a flat file data reference (data endpoint in mappings).

        Args:
            node: Node dictionary with 'type' field

        Returns:
            True if node is a flat file reference, False otherwise
        """
        return node.get("type") == cls.FLAT_FILE
    
    @classmethod
    def get_display_name(cls, node_type: str) -> str:
        """
        Convert backend constant to UI-friendly display name.
        
        Args:
            node_type: Backend node type constant (FILE, TABLE_OR_VIEW)
            
        Returns:
            User-friendly display name
            
        Examples:
            >>> NodeTypeHelper.get_display_name("FILE")
            "File"
            >>> NodeTypeHelper.get_display_name("TABLE_OR_VIEW")
            "Table or View"
        """
        return cls.DISPLAY_NAMES.get(node_type, node_type)
    
    @classmethod
    def normalize_type(cls, node_type: str) -> str:
        """
        Normalize legacy type names to current standard.
        
        Handles migration from old 3-type system:
            "GLOBAL_TEMP_TABLE" → "TABLE_OR_VIEW"
            
        Args:
            node_type: Node type (may be legacy)
            
        Returns:
            Normalized node type
            
        Examples:
            >>> NodeTypeHelper.normalize_type("GLOBAL_TEMP_TABLE")
            "TABLE_OR_VIEW"
            >>> NodeTypeHelper.normalize_type("FILE")
            "FILE"
        """
        if node_type == "GLOBAL_TEMP_TABLE":
            return cls.TABLE_OR_VIEW
        return node_type
    
    @classmethod
    def count_by_type(cls, nodes: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Count nodes by type.

        Args:
            nodes: List of node dictionaries

        Returns:
            Dictionary with counts for all node types.
        """
        return {
            "files":        sum(1 for n in nodes if n.get("type") == cls.FILE),
            "flat_files":   sum(1 for n in nodes if n.get("type") == cls.FLAT_FILE),
            "tables":       sum(1 for n in nodes if n.get("type") == cls.TABLE_OR_VIEW),
            "data_targets": sum(1 for n in nodes if n.get("type") in {cls.TABLE_OR_VIEW, cls.FLAT_FILE}),
            "mappings":     sum(1 for n in nodes if n.get("type") == cls.MAPPING),
            "sessions":     sum(1 for n in nodes if n.get("type") == cls.SESSION),
            "workflows":    sum(1 for n in nodes if n.get("type") == cls.WORKFLOW),
            "mapplets":     sum(1 for n in nodes if n.get("type") == cls.MAPPLET),
        }

    @classmethod
    def detect_graph_dialect(cls, nodes_dict: Dict[str, Any]) -> str:
        """Return the graph dialect based on node types present.

        Returns ``"informatica"`` if WORKFLOW nodes exist in the graph,
        otherwise ``"sql"``.  Distinct from :meth:`detect_actor_type` —
        this controls which migration-planning strategy to use.
        """
        has_workflow = any(
            n.get("type") == cls.WORKFLOW for n in nodes_dict.values()
        )
        return "informatica" if has_workflow else "sql"

    @classmethod
    def detect_actor_type(cls, nodes_dict: Dict[str, Any]) -> str:
        """Return the node type that acts as 'source actor' for this graph.

        SQL graphs use FILE nodes as actors. INFA graphs also have FILE nodes
        when Mapping Details is present (preferred). Falls back to MAPPING, then
        FILE as a last resort.
        """
        has_file = any(n.get("type") == cls.FILE for n in nodes_dict.values())
        if has_file:
            return cls.FILE
        has_mapping = any(n.get("type") == cls.MAPPING for n in nodes_dict.values())
        if has_mapping:
            return cls.MAPPING
        return cls.FILE  # fallback


