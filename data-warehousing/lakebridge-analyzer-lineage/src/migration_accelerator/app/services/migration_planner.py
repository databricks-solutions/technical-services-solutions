"""
Migration Planner Service for computing migration order.

This is a PURE FUNCTION SERVICE - receives graph data and processes it in-memory.
Does NOT perform any I/O operations.
"""

from typing import Any, Dict, List, Set

import networkx as nx

from migration_accelerator.app.services.edge_relationship_helper import (
    EdgeRelationshipHelper,
)
from migration_accelerator.app.services.node_type_helper import NodeTypeHelper
from migration_accelerator.utils.logger import get_logger

log = get_logger()


class MigrationPlanner:
    """
    Service for planning migration order using dependency analysis.
    
    PURE FUNCTION SERVICE: Receives graph_data from LineageMerger (cached)
    and computes migration order in-memory. Does NOT perform any I/O.
    
    Uses NetworkX for:
    - Connected components to identify file groups sharing tables
    - Topological sorting to determine migration waves within groups
    - Group-level dependency ordering
    
    Analyzes FILE->FILE dependencies based on table lineage relationships.
    """
    
    async def compute_migration_order(
        self, graph_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Compute recommended migration order with grouped structure.
        
        Groups files into logical migration units based on shared table dependencies,
        then creates waves within each group based on file-to-file dependencies.
        
        Builds FILE->FILE dependency graph based on table lineage:
        - If FileA creates TableX and FileB reads TableX, then FileB depends on FileA
        - Identifies connected components (files sharing tables) as migration groups
        - Uses topological generations within each group to create waves
        - Orders groups based on inter-group dependencies
        - Detects circular dependencies
        - Identifies pre-existing tables (read but never created)
        
        Args:
            graph_data: Graph data with nodes and edges from LineageMerger
        
        Returns:
            Dictionary with migration groups, waves, pre-existing tables, and metadata:
            {
                "groups": [{"group_number": int, "waves": [...], ...}, ...],
                "total_nodes": int,
                "total_groups": int,
                "has_cycles": bool,
                "cycle_info": str or None,
                "pre_existing_tables": [...],
                "table_dependencies": {...}
            }
        """
        nodes = graph_data.get("nodes", [])
        edges = graph_data.get("edges", [])
        
        if not nodes:
            return {
                "groups": [],
                "total_nodes": 0,
                "total_groups": 0,
                "has_cycles": False,
            }
        
        # Build nodes dictionary
        nodes_dict = {node["id"]: node for node in nodes}
        
        # Use helper to build table-to-file maps
        table_creators, table_readers, table_writers = (
            EdgeRelationshipHelper.build_table_file_maps(edges, nodes_dict)
        )
        
        # Build FILE->FILE dependency graph
        file_dependency_graph = self._build_file_dependency_graph(
            nodes_dict, table_creators, table_readers
        )
        
        # Identify file groups using connected components
        file_groups = self._identify_file_groups(
            nodes, edges, nodes_dict, table_creators, table_readers
        )
        
        # Check for cycles globally
        has_cycles = False
        cycle_info = None
        try:
            cycles = list(nx.simple_cycles(file_dependency_graph))
            if cycles:
                has_cycles = True
                cycle_info = (
                    f"Found {len(cycles)} circular dependencies. "
                    f"Consider breaking dependencies in: {', '.join(cycles[0][:3])}"
                )
                log.warning(f"Circular dependencies detected: {len(cycles)} cycles")
        except Exception as e:
            log.warning(f"Failed to detect cycles: {e}")
        
        # Order groups based on inter-group dependencies
        ordered_group_indices = self._order_groups(
            file_groups, file_dependency_graph, nodes_dict, table_creators
        )
        
        # Create migration groups with waves
        groups = []
        for group_idx in ordered_group_indices:
            group_file_ids = file_groups[group_idx]
            
            # Create waves within this group
            group_waves = self._create_waves_for_group(
                group_file_ids,
                file_dependency_graph,
                edges,
                nodes_dict,
                table_creators
            )
            
            # Identify tables involved in this group
            tables_involved = self._get_tables_for_group(
                group_file_ids, edges, nodes_dict
            )
            
            # Generate group name
            group_name = self._generate_group_name(
                tables_involved, nodes_dict, group_idx
            )
            
            groups.append({
                "group_number": group_idx + 1,
                "group_name": group_name,
                "files_count": len(group_file_ids),
                "tables_count": len(tables_involved),
                "waves": group_waves,
                "tables_involved": sorted([
                    nodes_dict.get(t_id, {}).get("name", t_id)
                    for t_id in tables_involved
                ]),
            })
        
        # Count only FILE nodes for total
        total_file_nodes = sum(1 for node in nodes if node.get("type") == "FILE")
        
        # Find tables that are referenced but never created (pre-existing tables)
        pre_existing_tables = self._identify_pre_existing_tables(
            nodes_dict, table_creators, table_readers, table_writers
        )
        
        # Build table dependency summary
        table_dependencies = {
            "created_tables": {
                table_id: {
                    "table_name": nodes_dict.get(table_id, {}).get("name", table_id),
                    "created_by_files": [
                        nodes_dict.get(f, {}).get("name", f) for f in files
                    ]
                }
                for table_id, files in table_creators.items()
            },
            "pre_existing_tables": {
                table["table_id"]: {
                    "table_name": table["table_name"],
                    "referenced_by_files": table["referencing_file_names"]
                }
                for table in pre_existing_tables
            }
        }
        
        log.info(
            f"Computed migration order: {len(groups)} groups, {total_file_nodes} files, "
            f"{len(pre_existing_tables)} pre-existing tables"
        )
        
        return {
            "groups": groups,
            "total_nodes": total_file_nodes,
            "total_groups": len(groups),
            "has_cycles": has_cycles,
            "cycle_info": cycle_info,
            "pre_existing_tables": pre_existing_tables,
            "table_dependencies": table_dependencies,
        }
    
    def _build_file_dependency_graph(
        self,
        nodes_dict: Dict[str, Any],
        table_creators: Dict[str, Set[str]],
        table_readers: Dict[str, Set[str]],
    ) -> nx.DiGraph:
        """
        Build FILE->FILE dependency graph based on table lineage.
        
        Args:
            nodes_dict: Dictionary mapping node IDs to node data
            table_creators: Mapping of table IDs to file IDs that create them
            table_readers: Mapping of table IDs to file IDs that read them
        
        Returns:
            NetworkX DiGraph with FILE nodes and dependency edges
        """
        G = nx.DiGraph()
        
        # Add all FILE nodes
        for node_id, node in nodes_dict.items():
            if node.get("type") == "FILE":
                G.add_node(node_id, **node)
        
        # Generate FILE->FILE dependencies
        # If FileA creates TableX and FileB reads TableX, then FileB depends on FileA
        dependencies_added = 0
        for table_id in table_creators:
            creator_files = table_creators[table_id]
            reader_files = table_readers.get(table_id, set())
            
            for creator_file in creator_files:
                for reader_file in reader_files:
                    if creator_file != reader_file:
                        if not G.has_edge(creator_file, reader_file):
                            G.add_edge(
                                creator_file,
                                reader_file,
                                relationship="DEPENDS_ON_TABLE",
                                table=table_id
                            )
                            dependencies_added += 1
        
        log.info(
            f"Generated {dependencies_added} file-to-file dependencies "
            f"based on table lineage"
        )
        
        return G
    
    def _identify_file_groups(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        nodes_dict: Dict[str, Any],
        table_creators: Dict[str, Set[str]],
        table_readers: Dict[str, Set[str]],
    ) -> List[Set[str]]:
        """
        Identify groups of files that share tables using connected components.
        
        Files are in the same group if they reference common tables (directly or indirectly).
        Uses undirected graph to find connected components.
        
        Args:
            nodes: List of all nodes
            edges: List of all edges
            nodes_dict: Dictionary mapping node IDs to node data
            table_creators: Mapping of table IDs to file IDs that create them
            table_readers: Mapping of table IDs to file IDs that read them
        
        Returns:
            List of sets, where each set contains file IDs in a group
        """
        # Build undirected graph where files are connected if they share tables
        G_undirected = nx.Graph()
        
        # Add all FILE nodes
        for node in nodes:
            if node.get("type") == "FILE":
                G_undirected.add_node(node["id"])
        
        # Connect files that share tables
        # If FileA and FileB both reference TableX (create/read/write), they're connected
        all_table_ids = set(table_creators.keys()) | set(table_readers.keys())
        
        for table_id in all_table_ids:
            # Get all files that reference this table
            files_referencing_table = set()
            if table_id in table_creators:
                files_referencing_table.update(table_creators[table_id])
            if table_id in table_readers:
                files_referencing_table.update(table_readers[table_id])
            
            # Connect all pairs of files that reference this table
            files_list = list(files_referencing_table)
            for i in range(len(files_list)):
                for j in range(i + 1, len(files_list)):
                    file_a = files_list[i]
                    file_b = files_list[j]
                    if not G_undirected.has_edge(file_a, file_b):
                        G_undirected.add_edge(file_a, file_b, shared_table=table_id)
        
        # Find connected components
        components = list(nx.connected_components(G_undirected))
        
        log.info(f"Identified {len(components)} file groups using connected components")
        
        return components
    
    def _create_waves_for_group(
        self,
        group_file_ids: Set[str],
        file_dependency_graph: nx.DiGraph,
        edges: List[Dict[str, Any]],
        nodes_dict: Dict[str, Any],
        table_creators: Dict[str, Set[str]],
    ) -> List[Dict[str, Any]]:
        """
        Create waves within a group using topological sort on dependencies.
        
        Args:
            group_file_ids: Set of file IDs in this group
            file_dependency_graph: Global FILE->FILE dependency graph
            edges: List of all edges (for pre-existing table lookup)
            nodes_dict: Dictionary mapping node IDs to node data
            table_creators: Mapping of table IDs to file IDs that create them
        
        Returns:
            List of wave dictionaries with wave_number and nodes
        """
        # Create subgraph for this group only
        group_subgraph = file_dependency_graph.subgraph(group_file_ids).copy()
        
        waves = []
        
        try:
            # Use topological generations to create waves
            generations = list(nx.topological_generations(group_subgraph))
            
            for wave_num, generation in enumerate(generations, start=1):
                wave_nodes = []
                
                for node_id in generation:
                    node = nodes_dict.get(node_id)
                    if not node:
                        continue
                    
                    # Count upstream and downstream within this group
                    upstream_files = [
                        nodes_dict.get(pred, {}).get("name", pred)
                        for pred in list(group_subgraph.predecessors(node_id))
                    ]
                    downstream_files = [
                        nodes_dict.get(succ, {}).get("name", succ)
                        for succ in list(group_subgraph.successors(node_id))
                    ]
                    upstream_count = len(upstream_files)
                    downstream_count = len(downstream_files)
                    
                    # Find pre-existing tables this file depends on
                    all_tables_read = EdgeRelationshipHelper.get_tables_read_by_file(
                        edges, node_id, nodes_dict
                    )
                    file_preexisting_tables = [
                        table_name for table_name in all_tables_read
                        if not any(
                            nodes_dict.get(t_id, {}).get("name") == table_name
                            for t_id in table_creators.keys()
                        )
                    ]
                    
                    # Determine rationale
                    if upstream_count == 0 and len(file_preexisting_tables) == 0:
                        rationale = "No dependencies - can be migrated first"
                    elif upstream_count == 0 and len(file_preexisting_tables) > 0:
                        rationale = (
                            f"Requires {len(file_preexisting_tables)} "
                            f"pre-existing table(s)"
                        )
                    elif len(file_preexisting_tables) > 0:
                        rationale = (
                            f"Depends on {upstream_count} file(s) and "
                            f"{len(file_preexisting_tables)} pre-existing table(s)"
                        )
                    else:
                        rationale = f"Depends on {upstream_count} file(s)"
                    
                    wave_nodes.append({
                        "node_id": node_id,
                        "name": node.get("name", node_id),
                        "type": node.get("type", "Unknown"),
                        "upstream_count": upstream_count,
                        "downstream_count": downstream_count,
                        "upstream_files": upstream_files,
                        "downstream_files": downstream_files,
                        "pre_existing_tables": file_preexisting_tables,
                        "pre_existing_table_count": len(file_preexisting_tables),
                        "rationale": rationale,
                        "source_files": node.get("sources", []),
                    })
                
                if wave_nodes:
                    waves.append({
                        "wave_number": wave_num,
                        "nodes": wave_nodes,
                    })
        
        except (nx.NetworkXError, RuntimeError, Exception) as e:
            # If topological sort fails due to cycles, create single wave
            log.warning(f"Topological sort failed for group (likely due to cycles): {e}")
            all_nodes = []
            for node_id in group_file_ids:
                node = nodes_dict.get(node_id)
                if not node or node.get("type") != "FILE":
                    continue
                
                if group_subgraph.has_node(node_id):
                    upstream_files = [
                        nodes_dict.get(pred, {}).get("name", pred)
                        for pred in list(group_subgraph.predecessors(node_id))
                    ]
                    downstream_files = [
                        nodes_dict.get(succ, {}).get("name", succ)
                        for succ in list(group_subgraph.successors(node_id))
                    ]
                else:
                    upstream_files = []
                    downstream_files = []
                
                upstream_count = len(upstream_files)
                downstream_count = len(downstream_files)
                
                # Find pre-existing tables this file depends on
                all_tables_read = EdgeRelationshipHelper.get_tables_read_by_file(
                    edges, node_id, nodes_dict
                )
                file_preexisting_tables = [
                    table_name for table_name in all_tables_read
                    if not any(
                        nodes_dict.get(t_id, {}).get("name") == table_name
                        for t_id in table_creators.keys()
                    )
                ]
                
                all_nodes.append({
                    "node_id": node_id,
                    "name": node.get("name", node_id),
                    "type": node.get("type", "Unknown"),
                    "upstream_count": upstream_count,
                    "downstream_count": downstream_count,
                    "upstream_files": upstream_files,
                    "downstream_files": downstream_files,
                    "pre_existing_tables": file_preexisting_tables,
                    "pre_existing_table_count": len(file_preexisting_tables),
                    "rationale": "Circular dependencies detected - manual review required",
                    "source_files": node.get("sources", []),
                })
            
            waves = [{
                "wave_number": 1,
                "nodes": all_nodes,
            }]
        
        return waves
    
    def _order_groups(
        self,
        file_groups: List[Set[str]],
        file_dependency_graph: nx.DiGraph,
        nodes_dict: Dict[str, Any],
        table_creators: Dict[str, Set[str]],
    ) -> List[int]:
        """
        Order groups based on inter-group dependencies.
        
        If files in Group A depend on tables created by files in Group B,
        then Group B should come before Group A.
        
        Args:
            file_groups: List of file ID sets (each set is a group)
            file_dependency_graph: FILE->FILE dependency graph
            nodes_dict: Dictionary mapping node IDs to node data
            table_creators: Mapping of table IDs to file IDs that create them
        
        Returns:
            Ordered list of group indices
        """
        # Build group-to-group dependency graph
        group_graph = nx.DiGraph()
        
        # Add all groups as nodes
        for i in range(len(file_groups)):
            group_graph.add_node(i)
        
        # Add edges between groups based on file dependencies
        for i, group_a in enumerate(file_groups):
            for j, group_b in enumerate(file_groups):
                if i == j:
                    continue
                
                # Check if any file in group_a depends on any file in group_b
                has_dependency = False
                for file_a in group_a:
                    for file_b in group_b:
                        if file_dependency_graph.has_edge(file_b, file_a):
                            has_dependency = True
                            break
                    if has_dependency:
                        break
                
                if has_dependency:
                    # group_a depends on group_b, so add edge group_b -> group_a
                    if not group_graph.has_edge(j, i):
                        group_graph.add_edge(j, i)
        
        # Use topological sort to order groups
        try:
            ordered_indices = list(nx.topological_sort(group_graph))
            log.info(f"Ordered {len(file_groups)} groups based on dependencies")
        except nx.NetworkXError:
            # If cycles exist at group level, use default order
            log.warning("Cycles detected at group level, using default ordering")
            ordered_indices = list(range(len(file_groups)))
        
        return ordered_indices
    
    def _get_tables_for_group(
        self,
        group_file_ids: Set[str],
        edges: List[Dict[str, Any]],
        nodes_dict: Dict[str, Any],
    ) -> Set[str]:
        """
        Get all table IDs referenced by files in this group.
        
        Args:
            group_file_ids: Set of file IDs in the group
            edges: List of all edges
            nodes_dict: Dictionary mapping node IDs to node data
        
        Returns:
            Set of table IDs referenced by this group
        """
        tables = set()
        
        for edge in edges:
            source = edge.get("source")
            target = edge.get("target")
            
            # Check if source is a file in this group
            if source in group_file_ids:
                target_node = nodes_dict.get(target)
                if target_node and NodeTypeHelper.is_table_node(target_node):
                    tables.add(target)
        
        return tables
    
    def _generate_group_name(
        self,
        table_ids: Set[str],
        nodes_dict: Dict[str, Any],
        group_idx: int,
    ) -> str:
        """
        Generate a human-readable name for a migration group.
        
        Uses the most common table name prefix if available,
        otherwise falls back to "Group N".
        
        Args:
            table_ids: Set of table IDs in this group
            nodes_dict: Dictionary mapping node IDs to node data
            group_idx: Index of this group
        
        Returns:
            Generated group name
        """
        if not table_ids:
            return f"Group {group_idx + 1}"
        
        # Get table names
        table_names = [
            nodes_dict.get(t_id, {}).get("name", t_id)
            for t_id in table_ids
        ]
        
        # Try to find common prefix or pattern
        if len(table_names) <= 3:
            # For small groups, use actual table names
            return "_".join(sorted(table_names)[:3])
        else:
            # For larger groups, try to find common prefix
            if table_names:
                # Get first table name as potential base
                first_table = sorted(table_names)[0]
                # Use first part if underscore-separated
                parts = first_table.split("_")
                if len(parts) > 1:
                    prefix = parts[0]
                    # Check if this prefix is common
                    matching = sum(1 for name in table_names if name.startswith(prefix))
                    if matching > len(table_names) * 0.5:  # More than 50% share prefix
                        return f"{prefix}_group"
            
            # Fallback to generic name
            return f"Group {group_idx + 1}"
    
    def _identify_pre_existing_tables(
        self,
        nodes_dict: Dict[str, Any],
        table_creators: Dict[str, Set[str]],
        table_readers: Dict[str, Set[str]],
        table_writers: Dict[str, Set[str]],
    ) -> List[Dict[str, Any]]:
        """
        Identify tables that are referenced but never created.
        
        These are pre-existing tables that must already exist in the target
        environment before migration begins.
        
        Args:
            nodes_dict: Dictionary mapping node IDs to node data
            table_creators: Mapping of table IDs to file IDs that create them
            table_readers: Mapping of table IDs to file IDs that read them
            table_writers: Mapping of table IDs to file IDs that write them
        
        Returns:
            List of pre-existing table info with references
        """
        pre_existing_tables = []
        all_referenced_tables = set(
            list(table_readers.keys()) + list(table_writers.keys())
        )
        
        for table_id in all_referenced_tables:
            if table_id not in table_creators:
                table_node = nodes_dict.get(table_id)
                if table_node and NodeTypeHelper.is_table_node(table_node):
                    # Get files that reference this table
                    reading_files = table_readers.get(table_id, set())
                    writing_files = table_writers.get(table_id, set())
                    all_referencing_files = reading_files | writing_files
                    
                    # Get file names for the references
                    referencing_file_names = [
                        nodes_dict.get(file_id, {}).get("name", file_id)
                        for file_id in all_referencing_files
                    ]
                    
                    pre_existing_tables.append({
                        "table_id": table_id,
                        "table_name": table_node.get("name", table_id),
                        "type": table_node.get("type", "TABLE_OR_VIEW"),
                        "referenced_by_files": list(all_referencing_files),
                        "referencing_file_names": referencing_file_names,
                        "read_by_count": len(reading_files),
                        "written_by_count": len(writing_files),
                        "total_references": len(all_referencing_files)
                    })
        
        # Sort by most referenced
        pre_existing_tables.sort(key=lambda x: x["total_references"], reverse=True)
        
        return pre_existing_tables




