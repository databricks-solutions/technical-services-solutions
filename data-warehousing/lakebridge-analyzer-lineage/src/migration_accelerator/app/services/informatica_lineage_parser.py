"""
Informatica PowerCenter lineage parser for Mappings Objects List and Subjob Info.

Builds MAPPING and TABLE_OR_VIEW nodes with READS_FROM/WRITES_TO/TRUNCATES edges,
plus SESSION/WORKFLOW nodes with CONTAINS edges from Subjob Info orchestration data.
Uses System Types sheet (when available) to classify objects as tables vs flat files.
"""

import os as _os
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from migration_accelerator.app.services.node_type_helper import NodeTypeHelper
from migration_accelerator.utils.logger import get_logger

log = get_logger()

# Sheet names expected from Informatica PowerCenter Analyzer (-t INFA)
MAPPINGS_OBJECTS_LIST_SHEET = "Mappings Objects List"
SUBJOB_INFO_SHEET = "Subjob Info"
MAPPING_DETAILS_SHEET = "Mapping Details"
SYSTEM_TYPES_SHEET = "System Types"
WORKFLOW_LINKS_SHEET = "Workflow Links and Conditions"
ITEM_NODE_INFO_SHEET = "Item Node Info"
DATABASE_CONNECTIONS_SHEET = "Database Connections"

# Map of Source/Target Indicator values to graph relationship types
_INDICATOR_MAP = {
    "S": "READS_FROM",
    "SOURCE": "READS_FROM",
    "SRC": "READS_FROM",
    "LOOKUP": "READS_FROM",
    "LKP": "READS_FROM",
    "LOOK UP": "READS_FROM",
    "T": "WRITES_TO",
    "TARGET": "WRITES_TO",
    "TGT": "WRITES_TO",
    "TARGET INSTANCE": "WRITES_TO",
}

# Map of Subjob Info type strings to NodeTypeHelper constants
_SUBJOB_TYPE_MAP = {
    "session": NodeTypeHelper.SESSION,
    "workflow": NodeTypeHelper.WORKFLOW,
    "mapping": NodeTypeHelper.MAPPING,
    "mapplet": NodeTypeHelper.MAPPLET,
}


_FLATFILE_SYSTEM_TYPES = {"FLATFILE", "FLAT FILE"}

_FILE_EXTENSIONS = frozenset({
    ".csv", ".txt", ".dat", ".xml", ".json", ".xls", ".xlsx",
    ".tsv", ".log", ".gz", ".zip", ".parquet", ".avro", ".orc",
})


def _find_column(df: pd.DataFrame, patterns: List[str]) -> Optional[str]:
    """Return first column whose name matches a pattern exactly (case-insensitive, stripped)."""
    if df is None or not hasattr(df, "columns") or len(df.columns) == 0:
        return None
    col_map = {str(col).strip().lower(): col for col in df.columns}
    for p in patterns:
        match = col_map.get(p.strip().lower())
        if match is not None:
            return match
    return None


def _source_target_indicator_to_relationship(indicator: Any) -> Optional[str]:
    """Map INFA Source/Target Indicator to graph relationship."""
    if pd.isna(indicator):
        return None
    val = str(indicator).strip().upper()
    if not val:
        return None
    return _INDICATOR_MAP.get(val)


def _apply_operation_override(relationship: str, operation: Any) -> str:
    """
    Override the edge relationship type based on the Operations column value.

    - TRUNCATE  -> TRUNCATES
    - DELETE    -> DELETES_FROM
    - INSERT/UPDATE when already WRITES_TO -> keep WRITES_TO
    """
    if pd.isna(operation):
        return relationship
    op = str(operation).strip().upper()
    if op == "TRUNCATE":
        return "TRUNCATES"
    if op == "DELETE":
        return "DELETES_FROM"
    return relationship


def _classify_object_type(
    connection: str,
    object_name: str,
    system_type: Optional[str] = None,
) -> str:
    """Classify an object as FLAT_FILE (data endpoint) or TABLE_OR_VIEW.

    FLAT_FILE = flat file data sources/targets referenced in mappings (e.g. CSV).
    FILE (source files) are created separately from Mapping Details sheet.
    Uses System Type (authoritative) when available, otherwise falls back
    to Connection/Object Name heuristics per the Informatica Analyzer reference.
    """
    if system_type:
        if system_type.strip().upper() in _FLATFILE_SYSTEM_TYPES:
            return NodeTypeHelper.FLAT_FILE
        return NodeTypeHelper.TABLE_OR_VIEW

    if not connection:
        if "/" in object_name or "\\" in object_name:
            return NodeTypeHelper.FLAT_FILE
        name_lower = object_name.lower()
        if any(name_lower.endswith(ext) for ext in _FILE_EXTENSIONS):
            return NodeTypeHelper.FLAT_FILE

    return NodeTypeHelper.TABLE_OR_VIEW


def _parse_system_types(df: pd.DataFrame) -> Dict[Tuple[str, str], str]:
    """Parse System Types sheet -> {(mapping_name, node_name): system_type}.

    Columns per reference: Mapping (A), Node (B), Node Type (C), System Type (D).
    """
    result: Dict[Tuple[str, str], str] = {}
    if df is None or df.empty:
        return result
    df = df.copy()
    df.columns = df.columns.astype(str).str.strip()

    mapping_col = _find_column(df, ["Mapping", "Item"])
    node_col = _find_column(df, ["Node", "Node Name"])
    system_type_col = _find_column(df, ["System Type", "SystemType"])

    if not mapping_col or not node_col or not system_type_col:
        log.warning(
            f"System Types: could not find required columns (Mapping, Node, System Type). "
            f"Found: {list(df.columns)}"
        )
        return result

    col_list = list(df.columns)
    mapping_idx = col_list.index(mapping_col)
    node_idx = col_list.index(node_col)
    system_type_idx = col_list.index(system_type_col)

    for row in df.itertuples(index=False):
        mapping_name = row[mapping_idx]
        node_name = row[node_idx]
        system_type = row[system_type_idx]
        if pd.isna(mapping_name) or pd.isna(node_name) or pd.isna(system_type):
            continue
        mapping_name = str(mapping_name).strip()
        node_name = str(node_name).strip()
        system_type = str(system_type).strip()
        if not mapping_name or not node_name or not system_type:
            continue
        result[(mapping_name, node_name)] = system_type
    return result


def _parse_mapping_details(df: pd.DataFrame) -> Dict[str, str]:
    """Parse Mapping Details sheet -> {mapping_name: xml_basename}.

    Column A: mapping/workflow name; Column C ('Source File'): XML file path.
    Returns only rows where both values are non-empty.
    """
    result: Dict[str, str] = {}
    if df is None or df.empty:
        return result
    df = df.copy()
    df.columns = df.columns.astype(str).str.strip()

    mapping_col = _find_column(
        df,
        ["Mapping / Workflow Details", "Mapping / Workflow", "Mapping", "Workflow Details"],
    )
    source_file_col = _find_column(df, ["Source File", "SourceFile"])

    if not mapping_col or not source_file_col:
        log.warning(
            f"Mapping Details: could not find Mapping and Source File columns. "
            f"Found: {list(df.columns)}"
        )
        return result

    col_list = list(df.columns)
    mapping_idx = col_list.index(mapping_col)
    source_file_idx = col_list.index(source_file_col)

    for row in df.itertuples(index=False):
        mapping_name = row[mapping_idx]
        source_file = row[source_file_idx]
        if pd.isna(mapping_name) or pd.isna(source_file):
            continue
        mapping_name = str(mapping_name).strip()
        source_file = str(source_file).strip()
        if not mapping_name or not source_file:
            continue
        # Normalise path separators then extract basename
        xml_basename = _os.path.basename(source_file.replace("\\", "/"))
        if xml_basename:
            result[mapping_name] = xml_basename
    return result


def _parse_mappings_objects_list(
    df: pd.DataFrame,
    system_types_lookup: Optional[Dict[Tuple[str, str], str]] = None,
) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Parse Mappings Objects List and produce MAPPING/TABLE_OR_VIEW/FILE nodes and edges.

    Uses system_types_lookup (when available) to classify objects as tables vs flat files.
    Falls back to Connection/Object Name heuristics when System Types is not available.

    Returns (nodes_dict, edges_list).
    """
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []

    if df is None or df.empty:
        return nodes, edges

    df = df.copy()
    df.columns = df.columns.astype(str).str.strip()

    mapping_col = _find_column(df, ["Mapping", "Mapping Name", "MappingName"])
    object_col = _find_column(df, ["Object Name", "ObjectName", "Table Name"])
    indicator_col = _find_column(
        df,
        ["Source/Target Indicator", "Source Target Indicator", "Indicator", "Usage"],
    )
    operation_col = _find_column(df, ["Operations", "Operation"])
    connection_col = _find_column(df, ["Connection"])
    workflow_col = _find_column(df, ["Workflow"])
    session_col = _find_column(df, ["Session"])
    folder_col = _find_column(df, ["Folder"])
    mapplet_col = _find_column(df, ["Mapplet"])
    instance_col = _find_column(df, ["Object Instance", "ObjectInstance"])

    if not mapping_col or not object_col:
        log.warning(
            f"Mappings Objects List: could not find Mapping and Object Name columns. "
            f"Found: {list(df.columns)}"
        )
        return nodes, edges

    # Build column index map for itertuples access
    col_list = list(df.columns)
    mapping_idx = col_list.index(mapping_col)
    object_idx = col_list.index(object_col)
    connection_idx = col_list.index(connection_col) if connection_col else None
    workflow_idx = col_list.index(workflow_col) if workflow_col else None
    session_idx = col_list.index(session_col) if session_col else None
    folder_idx = col_list.index(folder_col) if folder_col else None
    instance_idx = col_list.index(instance_col) if instance_col else None
    indicator_idx = col_list.index(indicator_col) if indicator_col else None
    operation_idx = col_list.index(operation_col) if operation_col else None
    mapplet_idx = col_list.index(mapplet_col) if mapplet_col else None

    for row in df.itertuples(index=False):
        mapping_name = row[mapping_idx]
        obj_name = row[object_idx]
        if pd.isna(mapping_name) or pd.isna(obj_name):
            continue
        mapping_name = str(mapping_name).strip()
        obj_name = str(obj_name).strip()
        if not mapping_name or not obj_name:
            continue

        connection = str(row[connection_idx]).strip() if connection_idx is not None else ""
        workflow = str(row[workflow_idx]).strip() if workflow_idx is not None else ""
        session = str(row[session_idx]).strip() if session_idx is not None else ""
        folder = str(row[folder_idx]).strip() if folder_idx is not None else ""
        instance = str(row[instance_idx]).strip() if instance_idx is not None else ""

        # Classify object type via System Types (authoritative) or heuristics (fallback)
        system_type = None
        if system_types_lookup and instance:
            system_type = system_types_lookup.get((mapping_name, instance))
        obj_type = _classify_object_type(connection, obj_name, system_type)

        # Create or update MAPPING node
        if mapping_name not in nodes:
            nodes[mapping_name] = {
                "id": mapping_name,
                "type": NodeTypeHelper.MAPPING,
                "label": mapping_name,
                "name": mapping_name,
                "workflow": workflow,
                "session": session,
                "folder": folder,
                "connection": connection,
            }
        else:
            existing = nodes[mapping_name]
            if workflow and not existing.get("workflow"):
                existing["workflow"] = workflow
            if session and not existing.get("session"):
                existing["session"] = session
            if folder and not existing.get("folder"):
                existing["folder"] = folder
            if connection and not existing.get("connection"):
                existing["connection"] = connection

        # Normalize ID to lowercase for data objects so case variants merge; display names keep original case
        obj_id = (
            obj_name.lower()
            if obj_type in (NodeTypeHelper.TABLE_OR_VIEW, NodeTypeHelper.FLAT_FILE)
            else obj_name
        )
        if obj_id not in nodes:
            nodes[obj_id] = {
                "id": obj_id,
                "type": obj_type,
                "label": obj_name,
                "name": obj_name,
                "connection": connection,
            }

        relationship = "READS_FROM"  # default
        if indicator_idx is not None:
            rel = _source_target_indicator_to_relationship(row[indicator_idx])
            if rel:
                relationship = rel

        if operation_idx is not None:
            relationship = _apply_operation_override(relationship, row[operation_idx])

        edges.append({
            "source": mapping_name,
            "target": obj_id,
            "relationship": relationship,
        })

        if mapplet_idx is not None:
            mapplet_val = row[mapplet_idx]
            if not pd.isna(mapplet_val):
                mapplet_name = str(mapplet_val).strip()
                if mapplet_name:
                    if mapplet_name not in nodes:
                        nodes[mapplet_name] = {
                            "id": mapplet_name,
                            "type": NodeTypeHelper.MAPPLET,
                            "label": mapplet_name,
                            "name": mapplet_name,
                        }
                    edges.append({
                        "source": mapplet_name,
                        "target": mapping_name,
                        "relationship": "CONTAINS",
                    })

    return nodes, edges


def _parse_workflow_links(
    df: pd.DataFrame,
    nodes: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Parse Workflow Links and Conditions -> PRECEDES edges between tasks.

    Columns per reference: Workflow (A), FromTask (B), ToTask (C),
    Workflow Link Condition (D).

    Ensures referenced task nodes exist (defaults to SESSION type).
    Returns edges_list.
    """
    edges: List[Dict[str, Any]] = []
    if df is None or df.empty:
        return edges
    df = df.copy()
    df.columns = df.columns.astype(str).str.strip()

    workflow_col = _find_column(df, ["Workflow"])
    from_col = _find_column(df, ["FromTask", "From Task", "From"])
    to_col = _find_column(df, ["ToTask", "To Task", "To"])
    condition_col = _find_column(
        df, ["Workflow Link Condition", "Condition", "Link Condition"]
    )

    if not from_col or not to_col:
        log.warning(
            f"Workflow Links and Conditions: could not find FromTask/ToTask columns. "
            f"Found: {list(df.columns)}"
        )
        return edges

    col_list = list(df.columns)
    from_idx = col_list.index(from_col)
    to_idx = col_list.index(to_col)
    workflow_idx = col_list.index(workflow_col) if workflow_col else None
    condition_idx = col_list.index(condition_col) if condition_col else None

    for row in df.itertuples(index=False):
        from_task = row[from_idx]
        to_task = row[to_idx]
        if pd.isna(from_task) or pd.isna(to_task):
            continue
        from_task = str(from_task).strip()
        to_task = str(to_task).strip()
        if not from_task or not to_task:
            continue

        workflow = ""
        if workflow_idx is not None and not pd.isna(row[workflow_idx]):
            workflow = str(row[workflow_idx]).strip()

        condition = ""
        if condition_idx is not None and not pd.isna(row[condition_idx]):
            condition = str(row[condition_idx]).strip()

        for task_name in (from_task, to_task):
            if task_name not in nodes:
                nodes[task_name] = {
                    "id": task_name,
                    "type": NodeTypeHelper.SESSION,
                    "label": task_name,
                    "name": task_name,
                }

        edge: Dict[str, Any] = {
            "source": from_task,
            "target": to_task,
            "relationship": "PRECEDES",
        }
        if workflow:
            edge["workflow"] = workflow
        if condition:
            edge["condition"] = condition
        edges.append(edge)

    return edges


def _parse_item_node_info(
    df: pd.DataFrame,
) -> Dict[str, List[Dict[str, Any]]]:
    """Parse Item Node Info -> per-mapping transformation pipeline metadata.

    Columns per reference: Item (A), Node Name (B), Orig Node Type (C),
    Conformed Node Type (D), Node Order (E), Subjob Ref (F).

    Returns {mapping_name: [{node_name, node_type, conformed_type, order, subjob_ref}]}.
    """
    result: Dict[str, List[Dict[str, Any]]] = {}
    if df is None or df.empty:
        return result
    df = df.copy()
    df.columns = df.columns.astype(str).str.strip()

    item_col = _find_column(df, ["Item", "Mapping"])
    node_name_col = _find_column(df, ["Node Name", "NodeName", "Node"])
    orig_type_col = _find_column(df, ["Orig Node Type", "Original Node Type"])
    conformed_col = _find_column(df, ["Conformed Node Type", "Conformed Type"])
    order_col = _find_column(df, ["Node Order", "Order"])
    subjob_ref_col = _find_column(df, ["Subjob Ref", "SubjobRef"])

    if not item_col or not node_name_col:
        log.warning(
            f"Item Node Info: could not find Item and Node Name columns. "
            f"Found: {list(df.columns)}"
        )
        return result

    col_list = list(df.columns)
    item_idx = col_list.index(item_col)
    node_name_idx = col_list.index(node_name_col)
    orig_type_idx = col_list.index(orig_type_col) if orig_type_col else None
    conformed_idx = col_list.index(conformed_col) if conformed_col else None
    order_idx = col_list.index(order_col) if order_col else None
    subjob_ref_idx = col_list.index(subjob_ref_col) if subjob_ref_col else None

    for row in df.itertuples(index=False):
        item = row[item_idx]
        node_name = row[node_name_idx]
        if pd.isna(item) or pd.isna(node_name):
            continue
        item = str(item).strip()
        node_name = str(node_name).strip()
        if not item or not node_name:
            continue

        entry: Dict[str, Any] = {"node_name": node_name}
        if orig_type_idx is not None and not pd.isna(row[orig_type_idx]):
            entry["node_type"] = str(row[orig_type_idx]).strip()
        if conformed_idx is not None and not pd.isna(row[conformed_idx]):
            entry["conformed_type"] = str(row[conformed_idx]).strip()
        if order_idx is not None and not pd.isna(row[order_idx]):
            try:
                entry["order"] = int(row[order_idx])
            except (ValueError, TypeError):
                pass
        if subjob_ref_idx is not None and not pd.isna(row[subjob_ref_idx]):
            entry["subjob_ref"] = str(row[subjob_ref_idx]).strip()

        result.setdefault(item, []).append(entry)

    return result


def _parse_database_connections(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    """Parse Database Connections -> {connection_name: {type, variable, count}}.

    Columns per reference: Connection Ref Type, Connection Name,
    Connection Type, Connection Variable, Count.
    """
    result: Dict[str, Dict[str, Any]] = {}
    if df is None or df.empty:
        return result
    df = df.copy()
    df.columns = df.columns.astype(str).str.strip()

    name_col = _find_column(df, ["Connection Name", "ConnectionName"])
    type_col = _find_column(df, ["Connection Type", "ConnectionType"])
    ref_type_col = _find_column(df, ["Connection Ref Type", "Ref Type"])
    variable_col = _find_column(df, ["Connection Variable", "Variable"])
    count_col = _find_column(df, ["Count"])

    if not name_col:
        log.warning(
            f"Database Connections: could not find Connection Name column. "
            f"Found: {list(df.columns)}"
        )
        return result

    col_list = list(df.columns)
    name_idx = col_list.index(name_col)
    type_idx = col_list.index(type_col) if type_col else None
    ref_type_idx = col_list.index(ref_type_col) if ref_type_col else None
    variable_idx = col_list.index(variable_col) if variable_col else None
    count_idx = col_list.index(count_col) if count_col else None

    for row in df.itertuples(index=False):
        conn_name = row[name_idx]
        if pd.isna(conn_name):
            continue
        conn_name = str(conn_name).strip()
        if not conn_name:
            continue
        entry: Dict[str, Any] = {}
        if type_idx is not None and not pd.isna(row[type_idx]):
            entry["connection_type"] = str(row[type_idx]).strip()
        if ref_type_idx is not None and not pd.isna(row[ref_type_idx]):
            entry["ref_type"] = str(row[ref_type_idx]).strip()
        if variable_idx is not None and not pd.isna(row[variable_idx]):
            entry["variable"] = str(row[variable_idx]).strip()
        if count_idx is not None and not pd.isna(row[count_idx]):
            try:
                entry["count"] = int(row[count_idx])
            except (ValueError, TypeError):
                pass
        result[conn_name] = entry

    return result


def _parse_subjob_info(
    df: pd.DataFrame,
    nodes: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Parse Subjob Info and produce CONTAINS edges (SESSION/WORKFLOW orchestration).

    Columns expected: Parent Item, Child Item, Parent Type, Child Type.
    New nodes are added to the provided nodes dict in-place.

    Returns edges_list.
    """
    edges: List[Dict[str, Any]] = []

    if df is None or df.empty:
        return edges

    df = df.copy()
    df.columns = df.columns.astype(str).str.strip()

    parent_item_col = _find_column(df, ["Parent Item", "ParentItem", "Parent"])
    child_item_col = _find_column(df, ["Child Item", "ChildItem", "Child"])
    parent_type_col = _find_column(df, ["Parent Type", "ParentType"])
    child_type_col = _find_column(df, ["Child Type", "ChildType"])

    if not parent_item_col or not child_item_col:
        log.warning(
            f"Subjob Info: could not find Parent Item and Child Item columns. "
            f"Found: {list(df.columns)}"
        )
        return edges

    col_list = list(df.columns)
    parent_item_idx = col_list.index(parent_item_col)
    child_item_idx = col_list.index(child_item_col)
    parent_type_idx = col_list.index(parent_type_col) if parent_type_col else None
    child_type_idx = col_list.index(child_type_col) if child_type_col else None

    for row in df.itertuples(index=False):
        parent_item = row[parent_item_idx]
        child_item = row[child_item_idx]
        if pd.isna(parent_item) or pd.isna(child_item):
            continue
        parent_item = str(parent_item).strip()
        child_item = str(child_item).strip()
        if not parent_item or not child_item:
            continue

        # Resolve parent type
        parent_type = NodeTypeHelper.WORKFLOW  # default
        if parent_type_idx is not None:
            raw = str(row[parent_type_idx]).strip().lower()
            parent_type = _SUBJOB_TYPE_MAP.get(raw, NodeTypeHelper.WORKFLOW)

        # Resolve child type
        child_type = NodeTypeHelper.SESSION  # default
        if child_type_idx is not None:
            raw = str(row[child_type_idx]).strip().lower()
            child_type = _SUBJOB_TYPE_MAP.get(raw, NodeTypeHelper.SESSION)

        # Ensure parent node exists
        if parent_item not in nodes:
            nodes[parent_item] = {
                "id": parent_item,
                "type": parent_type,
                "label": parent_item,
                "name": parent_item,
            }

        # Ensure child node exists
        if child_item not in nodes:
            nodes[child_item] = {
                "id": child_item,
                "type": child_type,
                "label": child_item,
                "name": child_item,
            }

        edges.append({
            "source": parent_item,
            "target": child_item,
            "relationship": "CONTAINS",
        })

    return edges


class InformaticaLineageParser:
    """Parser for Informatica PowerCenter Analyzer lineage sheets."""

    @staticmethod
    def parse_infa_sheets(sheets: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        """
        Parse Mappings Objects List (primary) and Subjob Info (optional secondary)
        into nodes and edges.

        Args:
            sheets: Dict mapping sheet name to DataFrame. Must contain
                "Mappings Objects List" (case-insensitive). "Subjob Info" is
                optional; a warning is logged if it is missing.

        Returns:
            Dictionary with "nodes", "edges", "stats" in the same format as
            SQLLineageParser.parse_program_object_xref for use by LineageService.
        """
        log.info("Parsing Informatica lineage sheets")

        # Resolve sheet names case-insensitively
        sheets_lower = {k.strip().lower(): k for k in sheets.keys()}

        mol_key = None
        for key in ["mappings objects list", "mappings objects xref"]:
            if key in sheets_lower:
                mol_key = sheets_lower[key]
                break

        subjob_key = None
        for key in ["subjob info", "subjobinfo"]:
            if key in sheets_lower:
                subjob_key = sheets_lower[key]
                break

        mapping_details_key = sheets_lower.get("mapping details")
        system_types_key = sheets_lower.get("system types")
        workflow_links_key = sheets_lower.get("workflow links and conditions")
        item_node_info_key = sheets_lower.get("item node info")
        db_connections_key = sheets_lower.get("database connections")

        if not mol_key:
            raise ValueError(
                "Informatica lineage requires 'Mappings Objects List' sheet. "
                f"Available sheets: {list(sheets.keys())}"
            )

        if not subjob_key:
            log.warning(
                "Informatica lineage: 'Subjob Info' sheet not found; "
                "SESSION/WORKFLOW orchestration nodes will be omitted. "
                f"Available sheets: {list(sheets.keys())}"
            )

        system_types_lookup: Optional[Dict[Tuple[str, str], str]] = None
        if system_types_key:
            system_types_lookup = _parse_system_types(sheets[system_types_key])
            log.info(
                f"Loaded {len(system_types_lookup)} System Types entries "
                f"for object classification"
            )
        else:
            log.info(
                "System Types sheet not found; using Connection/Object Name heuristics"
            )

        nodes_dict, mol_edges = _parse_mappings_objects_list(
            sheets[mol_key], system_types_lookup=system_types_lookup
        )

        subjob_edges: List[Dict[str, Any]] = []
        if subjob_key:
            subjob_edges = _parse_subjob_info(sheets[subjob_key], nodes_dict)

        all_edges = mol_edges + subjob_edges

        # ---- Workflow Links and Conditions (task ordering) -------------------
        workflow_link_edges: List[Dict[str, Any]] = []
        if workflow_links_key:
            workflow_link_edges = _parse_workflow_links(
                sheets[workflow_links_key], nodes_dict
            )
            log.info(
                f"Parsed {len(workflow_link_edges)} workflow link (PRECEDES) edges"
            )
        all_edges += workflow_link_edges

        # ---- Item Node Info (transformation pipeline per mapping) ------------
        item_node_info: Dict[str, List[Dict[str, Any]]] = {}
        if item_node_info_key:
            item_node_info = _parse_item_node_info(sheets[item_node_info_key])
            for mapping_name, transformations in item_node_info.items():
                if mapping_name in nodes_dict:
                    node = nodes_dict[mapping_name]
                    node["transformations"] = transformations
                    node["transformation_count"] = len(transformations)
                    conformed = {
                        t["conformed_type"]
                        for t in transformations
                        if "conformed_type" in t
                    }
                    if conformed:
                        node["conformed_types"] = sorted(conformed)
            log.info(
                f"Enriched {len(item_node_info)} mappings with transformation metadata"
            )

        # ---- Database Connections (connection inventory) ---------------------
        db_connections: Dict[str, Dict[str, Any]] = {}
        if db_connections_key:
            db_connections = _parse_database_connections(sheets[db_connections_key])
            for node in nodes_dict.values():
                conn_name = node.get("connection", "")
                if conn_name and conn_name in db_connections:
                    conn_info = db_connections[conn_name]
                    if "connection_type" in conn_info:
                        node["connection_type"] = conn_info["connection_type"]
            log.info(
                f"Loaded {len(db_connections)} database connections for enrichment"
            )

        # ---- FILE nodes from Mapping Details ---------------------------------
        mapping_to_xml: Dict[str, str] = {}
        if mapping_details_key:
            mapping_to_xml = _parse_mapping_details(sheets[mapping_details_key])

            for mapping_name, xml_basename in mapping_to_xml.items():
                if xml_basename not in nodes_dict:
                    nodes_dict[xml_basename] = {
                        "id": xml_basename,
                        "type": NodeTypeHelper.FILE,
                        "label": xml_basename,
                        "name": xml_basename,
                    }
                all_edges.append({
                    "source": xml_basename,
                    "target": mapping_name,
                    "relationship": "CONTAINS",
                })

        nodes_list = list(nodes_dict.values())
        counts = NodeTypeHelper.count_by_type(nodes_list)

        log.info(
            f"Parsed Informatica lineage: {len(nodes_list)} nodes, {len(all_edges)} edges. "
            f"Mappings: {counts['mappings']}, Tables: {counts['tables']}, "
            f"Sessions: {counts['sessions']}, Workflows: {counts['workflows']}, "
            f"Files: {counts['files']}, Flat files: {counts['flat_files']}"
        )

        stats = {
            "total_nodes": len(nodes_list),
            "total_edges": len(all_edges),
            "files": counts["files"],
            "flat_files": counts["flat_files"],
            "tables_or_views": counts["tables"],
            "mappings": counts["mappings"],
            "sessions": counts["sessions"],
            "workflows": counts["workflows"],
            "mapplets": counts["mapplets"],
            "workflow_links": len(workflow_link_edges),
            "mappings_with_transformations": len(item_node_info),
            "database_connections": len(db_connections),
        }

        return {
            "nodes": nodes_list,
            "edges": all_edges,
            "stats": stats,
        }
