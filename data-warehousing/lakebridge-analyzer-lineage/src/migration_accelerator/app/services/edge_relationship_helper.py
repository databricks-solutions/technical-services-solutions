"""
Edge Relationship Helper - Centralized utility for interpreting edge relationships.

This module provides a single source of truth for understanding edge direction semantics
in the lineage graph, preventing bugs from inconsistent interpretation.

Edge Direction Semantics:
-------------------------
All file operations follow a consistent pattern where FILE is the SOURCE (actor) and TABLE is the TARGET.

READS_FROM: FILE -> TABLE
    - File is the SOURCE (performs the read operation)
    - Table is the TARGET (being read from)
    - Meaning: A file reads data from a table
    - Dependency: FILE depends on TABLE (must exist for read to succeed)

CREATES: FILE -> TABLE
    - File is the SOURCE (file creates the table)
    - Table is the TARGET (table is being created)
    - Meaning: A file creates a table

CREATES_INDEX: FILE -> TABLE
    - File is the SOURCE (file creates index on table)
    - Table is the TARGET (index is being created on table)
    - Meaning: A file creates an index on a table

WRITES_TO: FILE -> TABLE
    - File is the SOURCE (data flows from file)
    - Table is the TARGET (data flows to table)
    - Meaning: A file writes data to a table (INSERT/UPDATE)
    - Dependency: FILE depends on TABLE (must exist for write to succeed)

DELETES_FROM: FILE -> TABLE
    - File is the SOURCE (file deletes from table)
    - Table is the TARGET (data is being deleted from table)
    - Meaning: A file deletes data from a table (DELETE/TRUNCATE)
    - Dependency: FILE depends on TABLE (must exist for delete to succeed)

DROPS: FILE -> TABLE
    - File is the SOURCE (file drops the table)
    - Table is the TARGET (table is being dropped)
    - Meaning: A file drops a table
    - Dependency: FILE depends on TABLE (must exist for drop to succeed)

DEPENDS_ON: NODE_A -> NODE_B
    - NODE_A is the SOURCE (depends on NODE_B)
    - NODE_B is the TARGET (is depended upon)
    - Meaning: Generic dependency relationship
"""

from typing import Any, Dict, List, Set, Tuple

from migration_accelerator.app.services.node_type_helper import NodeTypeHelper


class EdgeRelationshipHelper:
    """Utility class for interpreting edge relationships in lineage graphs."""

    # Relationship types that indicate a table is being read from
    READ_RELATIONSHIPS = {"READS_FROM", "READS"}

    # Relationship types that indicate a table is being written to (INSERT/UPDATE/CREATE)
    # Includes CREATE INDEX as it's a schema modification
    WRITE_RELATIONSHIPS = {"WRITES_TO", "WRITES", "CREATES", "CREATES_INDEX"}

    # Relationship types that indicate destructive operations (DELETE/TRUNCATE)
    DESTRUCTIVE_RELATIONSHIPS = {"DELETES_FROM"}

    # Relationship types that indicate table/view dropping (metadata destruction)
    DROP_RELATIONSHIPS = {"DROPS"}

    # Relationship type for table creation specifically
    CREATE_RELATIONSHIPS = {"CREATES"}
    
    # Relationship type for index creation specifically
    INDEX_RELATIONSHIPS = {"CREATES_INDEX"}

    # All modification operations (writes + destructive + drops)
    ALL_MODIFICATION_RELATIONSHIPS = WRITE_RELATIONSHIPS | DESTRUCTIVE_RELATIONSHIPS | DROP_RELATIONSHIPS

    @classmethod
    def is_table_read_edge(cls, edge: Dict[str, Any], table_id: str) -> bool:
        """
        Check if an edge represents a table being read from.

        For READS_FROM relationships:
        - File is the SOURCE of the edge (performs the read)
        - Table is the TARGET of the edge (being read from)

        Args:
            edge: Edge dictionary with source, target, relationship keys
            table_id: ID of the table to check

        Returns:
            True if this edge shows the table being read from
        """
        relationship = edge.get("relationship", "")
        return (
            relationship in cls.READ_RELATIONSHIPS
            and edge.get("target") == table_id
        )

    @classmethod
    def is_table_written_edge(cls, edge: Dict[str, Any], table_id: str) -> bool:
        """
        Check if an edge represents a table being written to (INSERT/UPDATE).

        For WRITES_TO/CREATES relationships:
        - File is the SOURCE of the edge
        - Table is the TARGET of the edge

        Args:
            edge: Edge dictionary with source, target, relationship keys
            table_id: ID of the table to check

        Returns:
            True if this edge shows the table being written to
        """
        relationship = edge.get("relationship", "")
        return (
            relationship in cls.WRITE_RELATIONSHIPS
            and edge.get("target") == table_id
        )

    @classmethod
    def is_table_deleted_edge(cls, edge: Dict[str, Any], table_id: str) -> bool:
        """
        Check if an edge represents destructive operations on a table (DELETE/TRUNCATE).

        For DELETES_FROM relationships:
        - File is the SOURCE of the edge
        - Table is the TARGET of the edge

        Args:
            edge: Edge dictionary with source, target, relationship keys
            table_id: ID of the table to check

        Returns:
            True if this edge shows the table being deleted from
        """
        relationship = edge.get("relationship", "")
        return (
            relationship in cls.DESTRUCTIVE_RELATIONSHIPS
            and edge.get("target") == table_id
        )

    @classmethod
    def is_table_dropped_edge(cls, edge: Dict[str, Any], table_id: str) -> bool:
        """
        Check if an edge represents a table being dropped.

        For DROPS relationships:
        - File is the SOURCE of the edge
        - Table is the TARGET of the edge

        Args:
            edge: Edge dictionary with source, target, relationship keys
            table_id: ID of the table to check

        Returns:
            True if this edge shows the table being dropped
        """
        relationship = edge.get("relationship", "")
        return (
            relationship in cls.DROP_RELATIONSHIPS
            and edge.get("target") == table_id
        )

    @classmethod
    def is_table_modified_edge(cls, edge: Dict[str, Any], table_id: str) -> bool:
        """
        Check if an edge represents ANY modification to a table (writes/deletes/drops).

        For ALL_MODIFICATION_RELATIONSHIPS:
        - File is the SOURCE of the edge
        - Table is the TARGET of the edge

        Args:
            edge: Edge dictionary with source, target, relationship keys
            table_id: ID of the table to check

        Returns:
            True if this edge shows any modification to the table
        """
        relationship = edge.get("relationship", "")
        return (
            relationship in cls.ALL_MODIFICATION_RELATIONSHIPS
            and edge.get("target") == table_id
        )

    @classmethod
    def is_table_created_edge(cls, edge: Dict[str, Any], table_id: str) -> bool:
        """
        Check if an edge represents a table being created.

        For CREATES relationships:
        - File is the SOURCE of the edge
        - Table is the TARGET of the edge

        Args:
            edge: Edge dictionary with source, target, relationship keys
            table_id: ID of the table to check

        Returns:
            True if this edge shows the table being created
        """
        relationship = edge.get("relationship", "")
        return (
            relationship in cls.CREATE_RELATIONSHIPS
            and edge.get("target") == table_id
        )

    @classmethod
    def get_reading_files(
        cls, edges: List[Dict[str, Any]], table_id: str, nodes_dict: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Get all files that read from a specific table.

        Args:
            edges: List of edge dictionaries
            table_id: ID of the table
            nodes_dict: Dictionary mapping node IDs to node data

        Returns:
            List of file information dictionaries with file_id and filename
        """
        reading_files_map = {}

        for edge in edges:
            if cls.is_table_read_edge(edge, table_id):
                # With new direction FILE -> TABLE, file is the source
                file_id = edge["source"]
                file_node = nodes_dict.get(file_id)
                if file_node and file_node.get("type") == "FILE":
                    # Get all source file references
                    for source in file_node.get("sources", []):
                        source_file_id = source["file_id"]
                        if source_file_id not in reading_files_map:
                            reading_files_map[source_file_id] = {
                                "file_id": source_file_id,
                                "filename": source["filename"],
                            }

        return list(reading_files_map.values())

    @classmethod
    def get_writing_files(
        cls, edges: List[Dict[str, Any]], table_id: str, nodes_dict: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Get all files that write to a specific table (includes CREATES, WRITES_TO, DELETES_FROM, DROPS).

        Args:
            edges: List of edge dictionaries
            table_id: ID of the table
            nodes_dict: Dictionary mapping node IDs to node data

        Returns:
            List of file information dictionaries with file_id and filename
        """
        writing_files_map = {}

        for edge in edges:
            if cls.is_table_modified_edge(edge, table_id):
                file_id = edge["source"]
                file_node = nodes_dict.get(file_id)
                if file_node and file_node.get("type") == "FILE":
                    # Get all source file references
                    for source in file_node.get("sources", []):
                        source_file_id = source["file_id"]
                        if source_file_id not in writing_files_map:
                            writing_files_map[source_file_id] = {
                                "file_id": source_file_id,
                                "filename": source["filename"],
                            }

        return list(writing_files_map.values())

    @classmethod
    def get_deleting_files(
        cls, edges: List[Dict[str, Any]], table_id: str, nodes_dict: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Get all files that delete from a specific table (DELETE/TRUNCATE operations).

        Args:
            edges: List of edge dictionaries
            table_id: ID of the table
            nodes_dict: Dictionary mapping node IDs to node data

        Returns:
            List of file information dictionaries with file_id and filename
        """
        deleting_files_map = {}

        for edge in edges:
            if cls.is_table_deleted_edge(edge, table_id):
                file_id = edge["source"]
                file_node = nodes_dict.get(file_id)
                if file_node and file_node.get("type") == "FILE":
                    # Get all source file references
                    for source in file_node.get("sources", []):
                        source_file_id = source["file_id"]
                        if source_file_id not in deleting_files_map:
                            deleting_files_map[source_file_id] = {
                                "file_id": source_file_id,
                                "filename": source["filename"],
                            }

        return list(deleting_files_map.values())

    @classmethod
    def get_dropping_files(
        cls, edges: List[Dict[str, Any]], table_id: str, nodes_dict: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Get all files that drop a specific table.

        Args:
            edges: List of edge dictionaries
            table_id: ID of the table
            nodes_dict: Dictionary mapping node IDs to node data

        Returns:
            List of file information dictionaries with file_id and filename
        """
        dropping_files_map = {}

        for edge in edges:
            if cls.is_table_dropped_edge(edge, table_id):
                file_id = edge["source"]
                file_node = nodes_dict.get(file_id)
                if file_node and file_node.get("type") == "FILE":
                    # Get all source file references
                    for source in file_node.get("sources", []):
                        source_file_id = source["file_id"]
                        if source_file_id not in dropping_files_map:
                            dropping_files_map[source_file_id] = {
                                "file_id": source_file_id,
                                "filename": source["filename"],
                            }

        return list(dropping_files_map.values())

    @classmethod
    def get_creating_files(
        cls, edges: List[Dict[str, Any]], table_id: str, nodes_dict: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Get all files that create a specific table.

        Args:
            edges: List of edge dictionaries
            table_id: ID of the table
            nodes_dict: Dictionary mapping node IDs to node data

        Returns:
            List of file information dictionaries with file_id and filename
        """
        creating_files_map = {}

        for edge in edges:
            if cls.is_table_created_edge(edge, table_id):
                file_id = edge["source"]
                file_node = nodes_dict.get(file_id)
                if file_node and file_node.get("type") == "FILE":
                    # Get all source file references
                    for source in file_node.get("sources", []):
                        source_file_id = source["file_id"]
                        if source_file_id not in creating_files_map:
                            creating_files_map[source_file_id] = {
                                "file_id": source_file_id,
                                "filename": source["filename"],
                            }

        return list(creating_files_map.values())

    @classmethod
    def get_tables_read_by_file(
        cls, edges: List[Dict[str, Any]], file_id: str, nodes_dict: Dict[str, Any]
    ) -> List[str]:
        """
        Get all tables read by a specific file.

        Args:
            edges: List of edge dictionaries
            file_id: ID of the file
            nodes_dict: Dictionary mapping node IDs to node data

        Returns:
            List of table names read by the file
        """
        tables = []

        for edge in edges:
            relationship = edge.get("relationship", "")
            # For READS_FROM: FILE -> TABLE (file is source, performs the read)
            if relationship in cls.READ_RELATIONSHIPS and edge["source"] == file_id:
                table_id = edge["target"]
                table_node = nodes_dict.get(table_id)
                if table_node and NodeTypeHelper.is_table_node(table_node):
                    tables.append(table_node.get("name", table_id))

        return tables

    @classmethod
    def get_tables_written_by_file(
        cls, edges: List[Dict[str, Any]], file_id: str, nodes_dict: Dict[str, Any]
    ) -> List[str]:
        """
        Get all tables written to by a specific file.

        Args:
            edges: List of edge dictionaries
            file_id: ID of the file
            nodes_dict: Dictionary mapping node IDs to node data

        Returns:
            List of table names written by the file
        """
        tables = []

        for edge in edges:
            relationship = edge.get("relationship", "")
            # For WRITES_TO/CREATES/DROPS: FILE -> TABLE (file is source)
            if relationship in cls.WRITE_RELATIONSHIPS and edge["source"] == file_id:
                table_id = edge["target"]
                table_node = nodes_dict.get(table_id)
                if table_node and NodeTypeHelper.is_table_node(table_node):
                    tables.append(table_node.get("name", table_id))

        return tables

    @classmethod
    def categorize_table_operations(
        cls, edges: List[Dict[str, Any]], nodes_dict: Dict[str, Any]
    ) -> Dict[str, Dict[str, int]]:
        """
        Categorize all table operations (reads, writes, deletes, drops) from edge list.
        
        For node type checking, see NodeTypeHelper class.

        Args:
            edges: List of edge dictionaries
            nodes_dict: Dictionary mapping node IDs to node data

        Returns:
            Dictionary mapping table_id to {"reads": count, "writes": count, "deletes": count, "drops": count}
        """
        table_operations = {}

        for edge in edges:
            relationship = edge.get("relationship", "")

            # For READS_FROM: FILE -> TABLE (table is target, being read from)
            if relationship in cls.READ_RELATIONSHIPS:
                table_id = edge["target"]
                table_node = nodes_dict.get(table_id)
                if table_node and NodeTypeHelper.is_table_node(table_node):
                    if table_id not in table_operations:
                        table_operations[table_id] = {"reads": 0, "writes": 0, "deletes": 0, "drops": 0}
                    table_operations[table_id]["reads"] += 1

            # For WRITES_TO/CREATES: FILE -> TABLE (table is target, being written to)
            elif relationship in cls.WRITE_RELATIONSHIPS:
                table_id = edge["target"]
                table_node = nodes_dict.get(table_id)
                if table_node and NodeTypeHelper.is_table_node(table_node):
                    if table_id not in table_operations:
                        table_operations[table_id] = {"reads": 0, "writes": 0, "deletes": 0, "drops": 0}
                    table_operations[table_id]["writes"] += 1

            # For DELETES_FROM: FILE -> TABLE (table is target, data being deleted)
            elif relationship in cls.DESTRUCTIVE_RELATIONSHIPS:
                table_id = edge["target"]
                table_node = nodes_dict.get(table_id)
                if table_node and NodeTypeHelper.is_table_node(table_node):
                    if table_id not in table_operations:
                        table_operations[table_id] = {"reads": 0, "writes": 0, "deletes": 0, "drops": 0}
                    table_operations[table_id]["deletes"] += 1

            # For DROPS: FILE -> TABLE (table is target, being dropped)
            elif relationship in cls.DROP_RELATIONSHIPS:
                table_id = edge["target"]
                table_node = nodes_dict.get(table_id)
                if table_node and NodeTypeHelper.is_table_node(table_node):
                    if table_id not in table_operations:
                        table_operations[table_id] = {"reads": 0, "writes": 0, "deletes": 0, "drops": 0}
                    table_operations[table_id]["drops"] += 1

        return table_operations

    @classmethod
    def build_table_file_maps(
        cls, edges: List[Dict[str, Any]], nodes_dict: Dict[str, Any]
    ) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]], Dict[str, Set[str]]]:
        """
        Build maps of tables to files for creators, readers, and writers.

        Args:
            edges: List of edge dictionaries
            nodes_dict: Dictionary mapping node IDs to node data

        Returns:
            Tuple of (table_creators, table_readers, table_writers)
            where each is a dict mapping table_id to set of file_ids
        """
        table_creators = {}
        table_readers = {}
        table_writers = {}

        for edge in edges:
            relationship = edge.get("relationship", "")
            source = edge["source"]
            target = edge["target"]
            source_node = nodes_dict.get(source)
            target_node = nodes_dict.get(target)

            # Track which FILES create which tables
            # CREATES: FILE -> TABLE (source is file, target is table)
            if (
                relationship in cls.CREATE_RELATIONSHIPS
                and source_node
                and source_node.get("type") == "FILE"
            ):
                if target not in table_creators:
                    table_creators[target] = set()
                table_creators[target].add(source)

            # Track which FILES read from which tables
            # READS_FROM: FILE -> TABLE (source is file, target is table)
            if (
                relationship in cls.READ_RELATIONSHIPS
                and source_node
                and source_node.get("type") == "FILE"
            ):
                if target not in table_readers:
                    table_readers[target] = set()
                table_readers[target].add(source)

            # Track which FILES write to which tables (includes all modifications)
            # WRITES_TO/DELETES_FROM/DROPS: FILE -> TABLE (source is file, target is table)
            if (
                relationship in cls.ALL_MODIFICATION_RELATIONSHIPS
                and source_node
                and source_node.get("type") == "FILE"
            ):
                if target not in table_writers:
                    table_writers[target] = set()
                table_writers[target].add(source)

        return table_creators, table_readers, table_writers

