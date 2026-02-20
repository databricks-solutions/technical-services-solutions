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
    TABLE_OR_VIEW = "TABLE_OR_VIEW"
    
    # All valid types
    ALL_TYPES = {FILE, TABLE_OR_VIEW}
    
    # UI display names (user-friendly)
    DISPLAY_NAMES = {
        FILE: "File",
        TABLE_OR_VIEW: "Table or View"
    }
    
    @classmethod
    def is_table_node(cls, node: Dict[str, Any]) -> bool:
        """
        Check if node is a table/view.
        
        Args:
            node: Node dictionary with 'type' field
            
        Returns:
            True if node is a table or view, False otherwise
        """
        return node.get("type") == cls.TABLE_OR_VIEW
    
    @classmethod
    def is_file_node(cls, node: Dict[str, Any]) -> bool:
        """
        Check if node is a file.
        
        Args:
            node: Node dictionary with 'type' field
            
        Returns:
            True if node is a file, False otherwise
        """
        return node.get("type") == cls.FILE
    
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
            Dictionary with counts: {"files": int, "tables": int}
        """
        return {
            "files": sum(1 for n in nodes if cls.is_file_node(n)),
            "tables": sum(1 for n in nodes if cls.is_table_node(n))
        }


