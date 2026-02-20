"""
SQL-specific lineage parser for Program-Object Xref analysis.
"""

from typing import Any, Dict, List, Set

import pandas as pd

from migration_accelerator.app.services.node_type_helper import NodeTypeHelper
from migration_accelerator.utils.logger import get_logger

log = get_logger()


class SQLLineageParser:
    """Parser for SQL analyzer lineage data."""

    @staticmethod
    def parse_program_object_xref(df: pd.DataFrame) -> Dict[str, Any]:
        """
        Parse Program-Object Xref sheet to build dependency graph.
        
        Logic:
        - CREATE operation = view/table definition (source node)
        - READ operation = dependency (target node)
        - Build: Program(CREATE) -> depends on -> Object(READ)
        - Infer view-to-view: if Program is in Object column, it's a view
        
        Args:
            df: DataFrame with Program-Object Xref data
            
        Returns:
            Dictionary with nodes, edges, and metadata
        """
        log.info("Parsing SQL Program-Object Xref for lineage")
        
        # Expected columns: Program, Object, Operation, Count (or similar)
        # Normalize column names
        df.columns = df.columns.str.strip()
        
        # Identify key columns
        program_col = None
        object_col = None
        operation_col = None
        
        for col in df.columns:
            col_lower = col.lower()
            if 'program' in col_lower or 'script' in col_lower:
                program_col = col
            elif 'object' in col_lower and 'program' not in col_lower:
                object_col = col
            elif 'operation' in col_lower or 'type' in col_lower:
                operation_col = col
        
        if not program_col or not object_col:
            raise ValueError(
                f"Could not identify required columns. Found: {list(df.columns)}"
            )
        
        log.info(
            f"Using columns: Program={program_col}, Object={object_col}, "
            f"Operation={operation_col or 'N/A'}"
        )
        
        # File extensions to detect FILE nodes
        file_extensions = ['.sql', '.py', '.scala', '.ipynb', '.r', '.sh']
        
        # Build edges and nodes
        edges = []
        nodes = {}
        temp_tables_filtered = 0
        global_temp_tables_count = 0
        variables_filtered = 0
        
        for _, row in df.iterrows():
            program = row[program_col]
            obj = row[object_col]
            operation = row[operation_col] if operation_col else ""
            
            if pd.isna(program) or pd.isna(obj):
                continue
            
            program = str(program).strip()
            obj = str(obj).strip()
            operation = str(operation).strip().upper() if not pd.isna(operation) else ""
            
            # Filter local variables (start with @ or @@)
            # @ = user-defined variables, @@ = system variables
            # These are SQL variables and should not be treated as tables/views
            if obj.startswith('@'):
                variables_filtered += 1
                continue
            
            # Filter temporary tables
            # Single # = local temp table (skip entirely)
            # Double ## = global temp table (treated as TABLE_OR_VIEW)
            if obj.startswith('#'):
                if obj.startswith('##'):
                    # Global temp table - keep it as TABLE_OR_VIEW
                    object_type = NodeTypeHelper.TABLE_OR_VIEW
                    global_temp_tables_count += 1 if obj not in nodes else 0
                else:
                    # Local temp table - skip it
                    temp_tables_filtered += 1
                    continue
            else:
                object_type = NodeTypeHelper.TABLE_OR_VIEW  # Regular database objects
            
            # Same check for program (skip if it's a variable or local temp table)
            if program.startswith('@'):
                # Skip if program is a variable
                continue
            
            if program.startswith('#'):
                if program.startswith('##'):
                    program_type = NodeTypeHelper.TABLE_OR_VIEW
                else:
                    # Skip if program is a local temp table
                    continue
            else:
                # Determine node types based on file extensions
                is_file = any(program.lower().endswith(ext) for ext in file_extensions)
                program_type = NodeTypeHelper.FILE if is_file else NodeTypeHelper.TABLE_OR_VIEW
            
            # Add nodes
            if program not in nodes:
                nodes[program] = {"id": program, "type": program_type, "label": program}
            if obj not in nodes:
                nodes[obj] = {"id": obj, "type": object_type, "label": obj}
            
            # Map Operation column value to standardized relationship
            # Create edges with correct direction based on data flow
            if operation == "CREATE":
                # FILE creates TABLE → FILE is source, TABLE is target
                edge = {
                    "source": program,
                    "target": obj,
                    "relationship": "CREATES"
                }
            elif operation in ["CREATE INDEX", "INDEX", "CREATE_INDEX"]:
                # FILE creates INDEX on TABLE → FILE is source, TABLE is target
                # Indexes are schema modifications, treated like WRITES_TO
                edge = {
                    "source": program,
                    "target": obj,
                    "relationship": "CREATES_INDEX"
                }
            elif operation in ["READ", "SELECT"]:
                # FILE reads from TABLE → FILE is source (active reader), TABLE is target (being read from)
                # This makes the direction intuitive: "FILE reads from TABLE"
                edge = {
                    "source": program,  # FILE is source (performs the read)
                    "target": obj,      # TABLE is target (being read from)
                    "relationship": "READS_FROM"
                }
                log.debug(f"Created READS_FROM edge: {program} -> {obj}")
            elif operation in ["WRITE", "INSERT", "UPDATE"]:
                # FILE writes to TABLE → FILE is source, TABLE is target
                edge = {
                    "source": program,
                    "target": obj,
                    "relationship": "WRITES_TO"
                }
            elif operation in ["DELETE", "TRUNCATE"]:
                # FILE deletes from TABLE → FILE is source, TABLE is target
                # Destructive operations separated for impact analysis
                edge = {
                    "source": program,
                    "target": obj,
                    "relationship": "DELETES_FROM"
                }
            elif operation == "DROP":
                # FILE drops TABLE → FILE is source, TABLE is target
                edge = {
                    "source": program,
                    "target": obj,
                    "relationship": "DROPS"
                }
            else:
                # Keep original for unknown operations, but log warning
                if operation:
                    log.warning(f"Unknown operation type: {operation}")
                    # Default to treating as read (reverse direction)
                    edge = {
                        "source": obj,
                        "target": program,
                        "relationship": operation
                    }
                else:
                    # Default fallback: treat as read
                    edge = {
                        "source": program,  # FILE performs the read
                        "target": obj,      # TABLE is being read from
                        "relationship": "READS_FROM"
                    }
            
            edges.append(edge)
        
        # Count node types using NodeTypeHelper
        counts = NodeTypeHelper.count_by_type(list(nodes.values()))
        
        log.info(
            f"Parsed {len(nodes)} nodes and {len(edges)} edges. "
            f"File nodes: {counts['files']}, Table/View nodes: {counts['tables']} "
            f"(includes {global_temp_tables_count} global temp tables)"
        )
        if variables_filtered > 0:
            log.info(f"Filtered {variables_filtered} variables (starting with @ or @@)")
        if temp_tables_filtered > 0:
            log.info(f"Filtered {temp_tables_filtered} local temp tables (starting with #)")
        if global_temp_tables_count > 0:
            log.info(f"Found {global_temp_tables_count} global temp tables (starting with ##)")
        
        # Identify tables with no CREATE relationship (external creation)
        tables_with_create = {
            edge["target"] for edge in edges if edge["relationship"] == "CREATES"
        }
        
        external_creation_count = 0
        for node_id, node in nodes.items():
            # Only check table/view nodes
            if NodeTypeHelper.is_table_node(node):
                # If table has no CREATE edge pointing to it, mark as externally created
                if node_id not in tables_with_create:
                    if "properties" not in node:
                        node["properties"] = {}
                    node["properties"]["external_creation"] = True
                    node["properties"]["tags"] = node["properties"].get("tags", [])
                    if "external_creation" not in node["properties"]["tags"]:
                        node["properties"]["tags"].append("external_creation")
                    external_creation_count += 1
        
        if external_creation_count > 0:
            log.info(
                f"Found {external_creation_count} tables/views with external creation "
                f"(no CREATE statement found)"
            )
        
        stats = {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "files": counts['files'],
            "tables_or_views": counts['tables'],
            "external_creation_tables": external_creation_count,
        }
        
        # Only include filtering stats if they exist
        if variables_filtered > 0:
            stats["variables_filtered"] = variables_filtered
        if temp_tables_filtered > 0:
            stats["temp_tables_filtered"] = temp_tables_filtered
        if global_temp_tables_count > 0:
            stats["global_temp_tables"] = global_temp_tables_count
        
        return {
            "nodes": list(nodes.values()),
            "edges": edges,
            "stats": stats
        }

    @staticmethod
    def build_cross_reference_format(df: pd.DataFrame) -> pd.DataFrame:
        """
        Build source->target cross-reference format.
        
        Args:
            df: Original DataFrame
            
        Returns:
            DataFrame with Source, Target, Relationship columns
        """
        parsed = SQLLineageParser.parse_program_object_xref(df)
        
        # Convert edges to cross-reference DataFrame
        cross_ref_data = []
        for edge in parsed["edges"]:
            cross_ref_data.append({
                "Source": edge["source"],
                "Target": edge["target"],
                "Relationship": edge["relationship"]
            })
        
        return pd.DataFrame(cross_ref_data)

    @staticmethod
    def build_dependency_format(df: pd.DataFrame) -> Dict[str, Any]:
        """
        Build hierarchical dependency structure.
        
        Args:
            df: Original DataFrame
            
        Returns:
            Hierarchical dependency dictionary
        """
        parsed = SQLLineageParser.parse_program_object_xref(df)
        
        # Build hierarchy: program -> depends on objects
        dependencies = {}
        for edge in parsed["edges"]:
            program = edge["source"]
            obj = edge["target"]
            
            if program not in dependencies:
                dependencies[program] = {
                    "type": next(
                        (n["type"] for n in parsed["nodes"] if n["id"] == program), 
                        "UNKNOWN"
                    ),
                    "dependencies": []
                }
            
            dependencies[program]["dependencies"].append({
                "object": obj,
                "relationship": edge["relationship"],
                "type": next(
                    (n["type"] for n in parsed["nodes"] if n["id"] == obj),
                    "UNKNOWN"
                )
            })
        
        return dependencies

    @staticmethod
    def build_data_flow_format(df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Build data flow edges representing actual data flow.
        
        Note: For authoritative edge direction semantics, see EdgeRelationshipHelper.
        Edge directions follow a consistent pattern where FILE is the actor (source):
        - READS_FROM: FILE -> TABLE (file reads data from table)
        - CREATES: FILE -> TABLE (file creates the table)
        - WRITES_TO: FILE -> TABLE (file writes data to table)
        - DROPS: FILE -> TABLE (file drops table)
        
        Use EdgeRelationshipHelper methods to correctly interpret these edges.
        
        Args:
            df: Original DataFrame
            
        Returns:
            List of data flow edge dictionaries
        """
        parsed = SQLLineageParser.parse_program_object_xref(df)
        
        # Data flows - edges already have correct direction
        data_flows = []
        for edge in parsed["edges"]:
            # Include all relationship types in data flow
            if edge["relationship"] in ["READS_FROM", "CREATES", "WRITES_TO", "DROPS", "DEPENDS_ON"]:
                data_flows.append({
                    "from": edge["source"],  # Source is already correct
                    "to": edge["target"],    # Target is already correct
                    "operation": edge["relationship"],
                    "source_node": edge["source"],
                    "target_node": edge["target"]
                })
        
        return data_flows

