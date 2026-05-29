"""
SQL-specific lineage parser for Program-Object Xref analysis.
"""

from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

from migration_accelerator.app.services.node_type_helper import NodeTypeHelper
from migration_accelerator.app.services.sql_object_classifier import (
    DROP_CTE,
    DROP_FUNCTION,
    DROP_LOCAL_TEMP,
    DROP_PSEUDO_TABLE,
    DROP_TABLE_VARIABLE,
    DROP_VARIABLE,
    SQLObjectClassifier,
)
from migration_accelerator.utils.logger import get_logger

log = get_logger()


class SQLLineageParser:
    """Parser for SQL analyzer lineage data."""

    @staticmethod
    def parse_program_object_xref(
        df: pd.DataFrame,
        sql_programs_df: Optional[pd.DataFrame] = None,
        functions_df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        """
        Parse Program-Object Xref sheet to build dependency graph.

        Logic:
        - CREATE operation = view/table definition (source node)
        - READ operation = dependency (target node)
        - Build: Program(CREATE) -> depends on -> Object(READ)
        - Infer view-to-view: if Program is in Object column, it's a view

        Object subtype refinement (when sql_programs_df is provided):
        - Cross-references creating programs' Script Category to assign
          TABLE / VIEW / MATERIALIZED_VIEW / PROCEDURE / SEQUENCE / INDEX / MACRO.
        - Objects never CREATEd in the corpus use TABLE_OR_VIEW (subtype unknown).
        - Drops CTE / function / table-variable false positives.

        Args:
            df: DataFrame with Program-Object Xref data
            sql_programs_df: optional `SQL Programs` sheet for Script Category lookup
            functions_df: optional `Functions` sheet for false-positive drops

        Returns:
            Dictionary with nodes, edges, and metadata
        """
        log.info("Parsing SQL Program-Object Xref for lineage")

        df.columns = df.columns.str.strip()

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

        classifier = SQLObjectClassifier(
            sql_programs_df=sql_programs_df, functions_df=functions_df
        )
        classifier.build_lookups()

        file_extensions = ['.sql', '.py', '.scala', '.ipynb', '.r', '.sh']

        # First (and only) pass: stream rows, accumulate per-object bookkeeping,
        # and stash raw row tuples for edge construction. We defer node-emission
        # decisions to a final pass once the classifier has full visibility.
        creating_programs_by_obj: Dict[str, Set[str]] = {}
        referencing_programs_by_obj: Dict[str, Set[str]] = {}
        ops_by_obj: Dict[str, Set[str]] = {}
        obj_display: Dict[str, str] = {}  # obj_id -> original-case label
        program_display: Dict[str, str] = {}
        program_type: Dict[str, str] = {}
        # Stash (program_id, obj_id, operation) for the deferred edge pass.
        raw_rows: List[Tuple[str, str, str]] = []

        temp_tables_filtered = 0
        global_temp_tables_count = 0
        variables_filtered = 0

        col_list = list(df.columns)
        program_idx = col_list.index(program_col)
        object_idx = col_list.index(object_col)
        operation_idx = col_list.index(operation_col) if operation_col else None

        for row in df.itertuples(index=False):
            program = row[program_idx]
            obj = row[object_idx]
            operation = row[operation_idx] if operation_idx is not None else ""

            if pd.isna(program) or pd.isna(obj):
                continue

            program = str(program).strip()
            obj = str(obj).strip()
            operation = (
                str(operation).strip().upper() if not pd.isna(operation) else ""
            )

            # Variable / local temp filtering for the OBJECT column.
            if obj.startswith('@'):
                variables_filtered += 1
                continue
            if obj.startswith('#'):
                if obj.startswith('##'):
                    obj_kind = NodeTypeHelper.TABLE_OR_VIEW
                    if obj.lower() not in obj_display:
                        global_temp_tables_count += 1
                else:
                    temp_tables_filtered += 1
                    continue
            else:
                obj_kind = NodeTypeHelper.TABLE_OR_VIEW

            # Variable / local temp filtering for the PROGRAM column (skip row).
            if program.startswith('@'):
                continue
            if program.startswith('#'):
                if program.startswith('##'):
                    prog_kind = NodeTypeHelper.TABLE_OR_VIEW
                else:
                    continue
            else:
                is_file = any(program.lower().endswith(ext) for ext in file_extensions)
                prog_kind = NodeTypeHelper.FILE if is_file else NodeTypeHelper.TABLE_OR_VIEW

            program_id = program.lower() if prog_kind == NodeTypeHelper.TABLE_OR_VIEW else program
            obj_id = obj.lower() if obj_kind == NodeTypeHelper.TABLE_OR_VIEW else obj

            if program_id not in program_display:
                program_display[program_id] = program
                program_type[program_id] = prog_kind
            if obj_id not in obj_display:
                obj_display[obj_id] = obj
                ops_by_obj[obj_id] = set()
                creating_programs_by_obj[obj_id] = set()
                referencing_programs_by_obj[obj_id] = set()

            ops_by_obj[obj_id].add(operation)
            referencing_programs_by_obj[obj_id].add(program)
            if operation == "CREATE":
                creating_programs_by_obj[obj_id].add(program)

            raw_rows.append((program_id, obj_id, operation))

        # Deferred classification: assign each TABLE_OR_VIEW-shaped object an
        # explicit subtype, or drop it as a CTE/function/table-variable.
        nodes: Dict[str, Dict[str, Any]] = {}
        dropped_obj_ids: Set[str] = set()
        ctes_filtered = 0
        functions_filtered = 0
        pseudo_tables_filtered = 0
        table_variables_filtered = 0
        local_temp_dropped_in_classifier = 0
        variables_dropped_in_classifier = 0

        for obj_id, display in obj_display.items():
            node_type, drop_reason = classifier.classify_with_referencing_programs(
                object_name=display,
                creating_programs=creating_programs_by_obj.get(obj_id, set()),
                referencing_programs=referencing_programs_by_obj.get(obj_id, set()),
                operations=ops_by_obj.get(obj_id, set()),
                is_table_variable=False,
            )
            if drop_reason is not None:
                dropped_obj_ids.add(obj_id)
                if drop_reason == DROP_CTE:
                    ctes_filtered += 1
                elif drop_reason == DROP_FUNCTION:
                    functions_filtered += 1
                elif drop_reason == DROP_TABLE_VARIABLE:
                    table_variables_filtered += 1
                elif drop_reason == DROP_LOCAL_TEMP:
                    local_temp_dropped_in_classifier += 1
                elif drop_reason == DROP_VARIABLE:
                    variables_dropped_in_classifier += 1
                elif drop_reason == DROP_PSEUDO_TABLE:
                    pseudo_tables_filtered += 1
                continue
            nodes[obj_id] = {
                "id": obj_id,
                "type": node_type,
                "label": display,
                "name": display,
            }

        # Program nodes are always emitted - they're FILEs or globally-named
        # TABLE_OR_VIEWs that were promoted via ## prefix.
        for program_id, display in program_display.items():
            if program_id in nodes:
                continue
            nodes[program_id] = {
                "id": program_id,
                "type": program_type[program_id],
                "label": display,
                "name": display,
            }

        # Edge construction: skip any row whose program or object was dropped.
        edges: List[Dict[str, Any]] = []
        for program_id, obj_id, operation in raw_rows:
            if obj_id in dropped_obj_ids or program_id in dropped_obj_ids:
                continue
            if obj_id not in nodes or program_id not in nodes:
                continue

            if operation == "CREATE":
                rel = "CREATES"
            elif operation in ("CREATE INDEX", "INDEX", "CREATE_INDEX"):
                rel = "CREATES_INDEX"
            elif operation in ("READ", "SELECT"):
                rel = "READS_FROM"
            elif operation in ("WRITE", "INSERT", "UPDATE"):
                rel = "WRITES_TO"
            elif operation in ("DELETE", "TRUNCATE"):
                rel = "DELETES_FROM"
            elif operation == "DROP":
                rel = "DROPS"
            elif operation:
                log.warning(f"Unknown operation type: {operation}")
                edges.append({"source": obj_id, "target": program_id, "relationship": operation})
                continue
            else:
                rel = "READS_FROM"

            edges.append({"source": program_id, "target": obj_id, "relationship": rel})

        counts = NodeTypeHelper.count_by_type(list(nodes.values()))

        log.info(
            f"Parsed {len(nodes)} nodes and {len(edges)} edges. "
            f"Files: {counts['files']} | Tables: {counts['table']} | Views: {counts['view']} | "
            f"MaterializedViews: {counts['materialized_view']} | "
            f"TableOrView (unspecified subtype): {counts['table_or_view']} | "
            f"Procedures: {counts['procedures']} | Sequences: {counts['sequences']} | "
            f"Indexes: {counts['indexes']} | Macros: {counts['macros']}"
        )
        if variables_filtered or variables_dropped_in_classifier:
            log.info(f"Filtered {variables_filtered + variables_dropped_in_classifier} variables (@/@@ prefix)")
        if temp_tables_filtered or local_temp_dropped_in_classifier:
            log.info(
                f"Filtered {temp_tables_filtered + local_temp_dropped_in_classifier} local temp tables (# prefix)"
            )
        if global_temp_tables_count:
            log.info(f"Found {global_temp_tables_count} global temp tables (## prefix)")
        if ctes_filtered:
            log.info(f"Filtered {ctes_filtered} CTE false positives")
        if functions_filtered:
            log.info(f"Filtered {functions_filtered} function-name false positives")
        if pseudo_tables_filtered:
            log.info(f"Filtered {pseudo_tables_filtered} pseudo-table references (e.g. DUAL)")
        if table_variables_filtered:
            log.info(f"Filtered {table_variables_filtered} table variables")

        # Tag objects with no CREATE in this corpus for downstream insights
        # (properties.tags / external_creation), without a dedicated node subtype.
        external_creation_count = 0
        for node_id, node in nodes.items():
            if not NodeTypeHelper.is_table_node(node):
                continue
            if not creating_programs_by_obj.get(node_id):
                if node["type"] in NodeTypeHelper.PERSISTED_DATA_TYPES and node["type"] != NodeTypeHelper.FLAT_FILE:
                    node.setdefault("properties", {})
                    tags = node["properties"].setdefault("tags", [])
                    if "external_creation" not in tags:
                        tags.append("external_creation")
                    node["properties"]["external_creation"] = True
                    external_creation_count += 1

        if external_creation_count:
            log.info(
                f"Found {external_creation_count} tables/views with external creation"
            )

        stats: Dict[str, Any] = {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "files": counts['files'],
            "tables_or_views": counts['tables'],
            "tables": counts['table'],
            "views": counts['view'],
            "materialized_views": counts['materialized_view'],
            "external_tables_or_views": counts['external'],
            "table_or_view_legacy": counts['table_or_view'],
            "procedures": counts['procedures'],
            "sequences": counts['sequences'],
            "indexes": counts['indexes'],
            "macros": counts['macros'],
            "external_creation_tables": external_creation_count,
            "classifier_active": classifier.has_categories,
        }
        if variables_filtered or variables_dropped_in_classifier:
            stats["variables_filtered"] = variables_filtered + variables_dropped_in_classifier
        if temp_tables_filtered or local_temp_dropped_in_classifier:
            stats["temp_tables_filtered"] = temp_tables_filtered + local_temp_dropped_in_classifier
        if global_temp_tables_count:
            stats["global_temp_tables"] = global_temp_tables_count
        if ctes_filtered:
            stats["ctes_filtered"] = ctes_filtered
        if functions_filtered:
            stats["functions_filtered"] = functions_filtered
        if pseudo_tables_filtered:
            stats["pseudo_tables_filtered"] = pseudo_tables_filtered
        if table_variables_filtered:
            stats["table_variables_filtered"] = table_variables_filtered

        return {
            "nodes": list(nodes.values()),
            "edges": edges,
            "stats": stats,
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

        cross_ref_data = []
        for edge in parsed["edges"]:
            cross_ref_data.append({
                "Source": edge["source"],
                "Target": edge["target"],
                "Relationship": edge["relationship"],
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

        dependencies: Dict[str, Any] = {}
        for edge in parsed["edges"]:
            program = edge["source"]
            obj = edge["target"]

            if program not in dependencies:
                dependencies[program] = {
                    "type": next(
                        (n["type"] for n in parsed["nodes"] if n["id"] == program),
                        "UNKNOWN",
                    ),
                    "dependencies": [],
                }

            dependencies[program]["dependencies"].append({
                "object": obj,
                "relationship": edge["relationship"],
                "type": next(
                    (n["type"] for n in parsed["nodes"] if n["id"] == obj),
                    "UNKNOWN",
                ),
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

        data_flows = []
        for edge in parsed["edges"]:
            if edge["relationship"] in ["READS_FROM", "CREATES", "WRITES_TO", "DROPS", "DEPENDS_ON"]:
                data_flows.append({
                    "from": edge["source"],
                    "to": edge["target"],
                    "operation": edge["relationship"],
                    "source_node": edge["source"],
                    "target_node": edge["target"],
                })

        return data_flows
