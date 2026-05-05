"""
Migration Planner Service for computing migration order.

This is a PURE FUNCTION SERVICE - receives graph data and processes it in-memory.
Does NOT perform any I/O operations.
"""

import asyncio
import re
from typing import Any, Dict, List, Optional, Set

import networkx as nx

from migration_accelerator.app.services.edge_relationship_helper import (
    EdgeRelationshipHelper,
)
from migration_accelerator.app.services.node_type_helper import NodeTypeHelper
from migration_accelerator.utils.logger import get_logger

log = get_logger()

# Fallback names from _generate_group_name; must stay in sync after mixed-mode renumbering.
_GENERIC_GROUP_NAME_RE = re.compile(r"^Group\s+(\d+)(\s*\(error\))?\s*$", re.IGNORECASE)


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
        self,
        graph_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Compute recommended migration order with grouped structure.

        Runs in thread pool to avoid blocking the event loop with CPU-heavy
        NetworkX operations on large graphs.
        """
        return await asyncio.to_thread(
            self._compute_migration_order_sync, graph_data
        )

    def _compute_migration_order_sync(
        self,
        graph_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Synchronous implementation of compute_migration_order."""
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

        # Dispatch to the right strategy
        dialect = NodeTypeHelper.detect_graph_dialect(nodes_dict)
        if dialect == "informatica":
            if self._has_direct_file_table_edges(edges, nodes_dict):
                return self._compute_mixed_migration_order(
                    nodes, edges, nodes_dict
                )
            return self._compute_informatica_migration_order(
                nodes, edges, nodes_dict
            )
        return self._compute_sql_migration_order(
            nodes, edges, nodes_dict
        )

    # ------------------------------------------------------------------
    # SQL: FILE-level migration planning
    # ------------------------------------------------------------------

    def _compute_sql_migration_order(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        nodes_dict: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Compute migration order for SQL (FILE-level) graphs."""
        actor_type = NodeTypeHelper.detect_actor_type(nodes_dict)

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

        # Check for cycles globally (O(V+E), no cycle enumeration)
        has_cycles = False
        cycle_info = None
        try:
            has_cycles = not nx.is_directed_acyclic_graph(file_dependency_graph)
            if has_cycles:
                cycle_participants = self._get_cycle_participants(file_dependency_graph)
                cycle_info = self._summarize_cycle_info(cycle_participants, nodes_dict)
                log.warning(
                    "Circular dependencies detected: %s cycle participant(s)",
                    len(cycle_participants),
                )
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
            try:
                # Create waves within this group
                group_waves = self._create_waves_for_group(
                    group_file_ids,
                    file_dependency_graph,
                    edges,
                    nodes_dict,
                    table_creators
                )

                # Identify tables involved in this group
                tables_involved_set = self._get_tables_for_group(
                    group_file_ids, edges, nodes_dict
                )
                tables_involved_list = sorted(tables_involved_set)

                # Generate group name
                group_name = self._generate_group_name(
                    tables_involved_set, nodes_dict, group_idx
                )

                groups.append({
                    "group_number": group_idx + 1,
                    "group_name": group_name,
                    "files_count": len(group_file_ids),
                    "tables_count": len(tables_involved_list),
                    "tables_involved": tables_involved_list,
                    "waves": group_waves,
                })
            except Exception as e:
                log.error("Failed to build group %s: %s", group_idx + 1, e)
                groups.append({
                    "group_number": group_idx + 1,
                    "group_name": f"Group {group_idx + 1} (error)",
                    "files_count": len(group_file_ids),
                    "tables_count": 0,
                    "tables_involved": [],
                    "waves": [],
                })

        # Count only actor nodes for total
        total_file_nodes = sum(1 for node in nodes if node.get("type") == actor_type)

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
            "migration_unit": "FILE",
            "groups": groups,
            "total_nodes": total_file_nodes,
            "total_groups": len(groups),
            "has_cycles": has_cycles,
            "cycle_info": cycle_info,
            "pre_existing_tables": pre_existing_tables,
            "table_dependencies": table_dependencies,
        }
    
    # ------------------------------------------------------------------
    # Helpers for dialect detection
    # ------------------------------------------------------------------

    @staticmethod
    def _has_direct_file_table_edges(
        edges: List[Dict[str, Any]], nodes_dict: Dict[str, Any]
    ) -> bool:
        """Return True if any edge links a FILE node directly to a TABLE_OR_VIEW.

        This distinguishes mixed SQL+Informatica graphs from pure-Informatica
        graphs.  In Informatica-only graphs, FILE nodes only have CONTAINS
        edges to MAPPING nodes — never direct READ/WRITE/CREATE edges to tables.
        """
        direct_relationships = (
            EdgeRelationshipHelper.READ_RELATIONSHIPS
            | EdgeRelationshipHelper.WRITE_RELATIONSHIPS
            | EdgeRelationshipHelper.CREATE_RELATIONSHIPS
        )
        for edge in edges:
            if edge.get("relationship") not in direct_relationships:
                continue
            src_node = nodes_dict.get(edge["source"])
            tgt_node = nodes_dict.get(edge["target"])
            if (
                src_node
                and tgt_node
                and src_node.get("type") == NodeTypeHelper.FILE
                and NodeTypeHelper.is_table_node(tgt_node)
            ):
                return True
        return False

    @staticmethod
    def _get_cycle_participants(graph: nx.DiGraph) -> List[Set[str]]:
        """Return non-trivial strongly connected components (cycle participants). O(V+E)."""
        sccs = list(nx.strongly_connected_components(graph))
        return [scc for scc in sccs if len(scc) > 1]

    _MAX_CYCLE_GROUPS_IN_SUMMARY = 10

    @classmethod
    def _summarize_cycle_info(
        cls,
        cycle_participants: List[Set[str]],
        nodes_dict: Dict[str, Any],
    ) -> Optional[str]:
        """Build human-readable cycle summary from SCC participants.

        Lists at most _MAX_CYCLE_GROUPS_IN_SUMMARY groups (stable order) and
        reports how many additional cycle groups exist.
        """
        if not cycle_participants:
            return None
        max_groups = cls._MAX_CYCLE_GROUPS_IN_SUMMARY
        sorted_sccs = sorted(
            cycle_participants,
            key=lambda scc: (
                min(
                    nodes_dict.get(nid, {}).get("name", str(nid)) for nid in scc
                ),
                min(scc),
            ),
        )
        parts = []
        for scc in sorted_sccs[:max_groups]:
            names = sorted(
                nodes_dict.get(nid, {}).get("name", nid) for nid in scc
            )
            parts.append(", ".join(names[:5]))
            if len(names) > 5:
                parts[-1] += f" (+{len(names) - 5} more)"
        remainder = len(sorted_sccs) - max_groups
        suffix = ""
        if remainder > 0:
            suffix = (
                f" ({remainder} more circular dependency "
                f"group{'s' if remainder != 1 else ''} not shown)"
            )
        return (
            "Found circular dependencies. "
            "Consider breaking dependencies in: " + "; ".join(parts) + suffix
        )

    @staticmethod
    def _node_sort_key(
        node_id: Any,
        nodes_dict: Dict[str, Any],
    ) -> tuple:
        """Return (node_name, node_id) for stable deterministic sort."""
        name = nodes_dict.get(node_id, {}).get("name", str(node_id))
        return (name, node_id)

    @staticmethod
    def _sorted_components(
        components: List[Set[str]],
        nodes_dict: Dict[str, Any],
    ) -> List[List[str]]:
        """Sort each component by node name/id and sort the list of components by first element."""
        sorted_component_lists = []
        for comp in components:
            sorted_component_lists.append(
                sorted(comp, key=lambda n: MigrationPlanner._node_sort_key(n, nodes_dict))
            )
        sorted_component_lists.sort(
            key=lambda c: MigrationPlanner._node_sort_key(c[0], nodes_dict)
            if c else ("", "")
        )
        return sorted_component_lists

    @staticmethod
    def _sorted_generations(
        generations: List[List[str]],
        nodes_dict: Dict[str, Any],
    ) -> List[List[str]]:
        """Sort nodes within each topological generation for deterministic output."""
        return [
            sorted(gen, key=lambda n: MigrationPlanner._node_sort_key(n, nodes_dict))
            for gen in generations
        ]

    @staticmethod
    def _sorted_topo(
        graph: nx.DiGraph,
        nodes_dict: Dict[str, Any],
    ) -> List[Any]:
        """Topological sort with deterministic tie-breaking by node name/id."""
        try:
            generations = list(nx.topological_generations(graph))
            return [
                n
                for gen in MigrationPlanner._sorted_generations(
                    generations, nodes_dict
                )
                for n in gen
            ]
        except Exception as e:
            log.warning(
                "Topological ordering unavailable (%s); using sorted-node fallback",
                e,
            )
            return sorted(
                graph.nodes,
                key=lambda n: MigrationPlanner._node_sort_key(n, nodes_dict),
            )

    # ------------------------------------------------------------------
    # Mixed SQL + Informatica
    # ------------------------------------------------------------------

    def _compute_mixed_migration_order(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        nodes_dict: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Compute migration order when both SQL and Informatica nodes exist.

        Partitions the graph into SQL and Informatica subgraphs, runs each
        strategy independently, then combines groups with cross-dialect
        dependency ordering via shared TABLE_OR_VIEW nodes.
        """
        # 1. Identify Informatica-owned FILE IDs
        workflow_to_file = EdgeRelationshipHelper.build_workflow_to_file_map(
            edges, nodes_dict
        )
        infa_file_ids: Set[str] = set(workflow_to_file.values())

        infa_node_types = {
            NodeTypeHelper.WORKFLOW,
            NodeTypeHelper.SESSION,
            NodeTypeHelper.MAPPING,
        }

        # 2. Build SQL subgraph (exclude Informatica actors + Informatica FILEs)
        sql_node_ids = {
            nid
            for nid, n in nodes_dict.items()
            if n.get("type") not in infa_node_types and nid not in infa_file_ids
        }
        sql_nodes = [n for n in nodes if n["id"] in sql_node_ids]
        sql_edges = [
            e
            for e in edges
            if e["source"] in sql_node_ids and e["target"] in sql_node_ids
        ]
        sql_nodes_dict = {nid: nodes_dict[nid] for nid in sql_node_ids}

        # 3. Run SQL strategy on SQL subgraph
        sql_result = self._compute_sql_migration_order(
            sql_nodes, sql_edges, sql_nodes_dict
        )

        # 4. Run Informatica strategy on full graph (it naturally ignores SQL nodes)
        infa_result = self._compute_informatica_migration_order(
            nodes, edges, nodes_dict
        )

        # 5. Tag groups with dialect
        sql_groups = sql_result.get("groups", [])
        infa_groups = infa_result.get("groups", [])
        for g in sql_groups:
            g["dialect"] = "sql"
        for g in infa_groups:
            g["dialect"] = "informatica"

        # 6. Build cross-dialect group ordering via shared tables
        #    Collect table read/write sets per group
        sql_table_creators, sql_table_readers, _ = (
            EdgeRelationshipHelper.build_table_file_maps(sql_edges, sql_nodes_dict)
        )
        infa_table_creators, infa_table_readers, infa_table_writers = (
            EdgeRelationshipHelper.build_table_workflow_maps(edges, nodes_dict)
        )

        # Tables written by each dialect (keyed by table_id)
        infa_tables_written: Set[str] = set(infa_table_writers.keys()) | set(
            infa_table_creators.keys()
        )
        sql_tables_written: Set[str] = set(sql_table_creators.keys())

        # For each SQL group, find which tables it reads
        sql_group_reads: List[Set[str]] = []
        for g in sql_groups:
            tables = set()
            for wave in g.get("waves", []):
                for node in wave.get("nodes", []):
                    nid = node["node_id"]
                    for tbl_id, readers in sql_table_readers.items():
                        if nid in readers:
                            tables.add(tbl_id)
            sql_group_reads.append(tables)

        # For each Informatica group, find which tables it reads
        infa_group_reads: List[Set[str]] = []
        for g in infa_groups:
            tables = set()
            for tbl_id, readers in infa_table_readers.items():
                # Check if any reader workflow is in this group
                for file_entry in g.get("files", []):
                    for wave in file_entry.get("waves", []):
                        for node in wave.get("nodes", []):
                            wf_id = node["node_id"]
                            if wf_id in readers:
                                tables.add(tbl_id)
            infa_group_reads.append(tables)

        # Build combined group list and group-level dependency graph
        all_groups = sql_groups + infa_groups
        n_sql = len(sql_groups)
        n_total = len(all_groups)

        group_dep = nx.DiGraph()
        for i in range(n_total):
            group_dep.add_node(i)

        # SQL group depends on Informatica group if it reads a table Informatica writes
        for si, reads in enumerate(sql_group_reads):
            if reads & infa_tables_written:
                for ii in range(len(infa_groups)):
                    gi = n_sql + ii  # index in all_groups
                    # Check if this Informatica group actually writes one of those tables
                    for file_entry in infa_groups[ii].get("files", []):
                        for wave in file_entry.get("waves", []):
                            for node in wave.get("nodes", []):
                                wf_id = node["node_id"]
                                for tbl_id in reads & infa_tables_written:
                                    writers = infa_table_writers.get(
                                        tbl_id, set()
                                    ) | infa_table_creators.get(tbl_id, set())
                                    if wf_id in writers:
                                        if not group_dep.has_edge(gi, si):
                                            group_dep.add_edge(gi, si)

        # Informatica group depends on SQL group if it reads a table SQL writes
        for ii, reads in enumerate(infa_group_reads):
            gi = n_sql + ii
            if reads & sql_tables_written:
                for si in range(n_sql):
                    for wave in sql_groups[si].get("waves", []):
                        for node in wave.get("nodes", []):
                            nid = node["node_id"]
                            for tbl_id in reads & sql_tables_written:
                                if nid in sql_table_creators.get(tbl_id, set()):
                                    if not group_dep.has_edge(si, gi):
                                        group_dep.add_edge(si, gi)

        # 7. Topological sort with deterministic tie-breaking, then re-number
        try:
            ordered_indices = self._sorted_topo(group_dep, nodes_dict)
        except nx.NetworkXError:
            ordered_indices = list(range(n_total))

        ordered_groups = []
        for new_num, idx in enumerate(ordered_indices, start=1):
            g = all_groups[idx]
            g["group_number"] = new_num
            name = (g.get("group_name") or "").strip()
            m = _GENERIC_GROUP_NAME_RE.match(name)
            if m:
                g["group_name"] = (
                    f"Group {new_num} (error)" if m.group(2) else f"Group {new_num}"
                )
            ordered_groups.append(g)

        # 8. Merge pre-existing tables and table_dependencies
        pre_existing_combined = (
            sql_result.get("pre_existing_tables", [])
            + infa_result.get("pre_existing_tables", [])
        )
        # Deduplicate by table_id
        seen_table_ids: Set[str] = set()
        unique_pre_existing = []
        for t in pre_existing_combined:
            if t["table_id"] not in seen_table_ids:
                seen_table_ids.add(t["table_id"])
                unique_pre_existing.append(t)

        table_deps_combined: Dict[str, Any] = {}
        for key in ("created_tables", "pre_existing_tables"):
            merged: Dict[str, Any] = {}
            merged.update(
                sql_result.get("table_dependencies", {}).get(key, {})
            )
            merged.update(
                infa_result.get("table_dependencies", {}).get(key, {})
            )
            table_deps_combined[key] = merged

        has_cycles = sql_result.get("has_cycles", False) or infa_result.get(
            "has_cycles", False
        )
        cycle_parts = [
            p
            for p in [
                sql_result.get("cycle_info"),
                infa_result.get("cycle_info"),
            ]
            if p
        ]
        cycle_info = "; ".join(cycle_parts) if cycle_parts else None

        total_nodes = sql_result.get("total_nodes", 0) + infa_result.get(
            "total_nodes", 0
        )

        log.info(
            f"Computed mixed migration order: {len(ordered_groups)} groups "
            f"({n_sql} SQL, {len(infa_groups)} Informatica), "
            f"{total_nodes} total actors"
        )

        return {
            "migration_unit": "MIXED",
            "groups": ordered_groups,
            "total_nodes": total_nodes,
            "total_groups": len(ordered_groups),
            "has_cycles": has_cycles,
            "cycle_info": cycle_info,
            "pre_existing_tables": unique_pre_existing,
            "table_dependencies": table_deps_combined,
        }

    # ------------------------------------------------------------------
    # Informatica: Group -> File -> Waves of Workflows
    # ------------------------------------------------------------------

    def _compute_informatica_migration_order(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        nodes_dict: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Compute migration order for Informatica graphs.

        Produces Group -> File -> Waves-of-Workflows structure where
        workflows within each file are ordered by data dependencies
        (shared tables).
        """
        # 1. Build table-workflow maps
        table_creators, table_readers, table_writers = (
            EdgeRelationshipHelper.build_table_workflow_maps(edges, nodes_dict)
        )

        # 2. Build workflow-to-file map
        workflow_to_file = EdgeRelationshipHelper.build_workflow_to_file_map(
            edges, nodes_dict
        )

        # Collect all workflow node IDs
        workflow_ids = {
            nid
            for nid, n in nodes_dict.items()
            if n.get("type") == NodeTypeHelper.WORKFLOW
        }

        if not workflow_ids:
            return {
                "migration_unit": "WORKFLOW",
                "groups": [],
                "total_nodes": 0,
                "total_groups": 0,
                "has_cycles": False,
                "cycle_info": None,
                "pre_existing_tables": [],
                "table_dependencies": {},
            }

        # 3. Build WORKFLOW->WORKFLOW dependency graph from shared tables.
        #    If WF_A writes TableX and WF_B reads TableX -> B depends on A.
        wf_graph = nx.DiGraph()
        for wf_id in workflow_ids:
            wf_graph.add_node(wf_id, **nodes_dict[wf_id])

        for table_id, writer_wfs in table_writers.items():
            reader_wfs = table_readers.get(table_id, set())
            for writer in writer_wfs:
                for reader in reader_wfs:
                    if writer != reader:
                        if not wf_graph.has_edge(writer, reader):
                            wf_graph.add_edge(
                                writer, reader, table=table_id
                            )

        # Check for cycles (O(V+E), no cycle enumeration)
        has_cycles = False
        cycle_info = None
        try:
            has_cycles = not nx.is_directed_acyclic_graph(wf_graph)
            if has_cycles:
                cycle_participants = self._get_cycle_participants(wf_graph)
                cycle_info = self._summarize_cycle_info(cycle_participants, nodes_dict)
                log.warning(
                    "Circular dependencies detected: %s cycle participant(s)",
                    len(cycle_participants),
                )
        except Exception as e:
            log.warning(f"Failed to detect cycles: {e}")

        # 4. Find connected components (groups) using an undirected
        #    "shared-reference" graph.  Two workflows belong in the same
        #    migration group when they reference **any** common table —
        #    regardless of whether one writes and the other reads.  The
        #    directed wf_graph (writer→reader only) is kept for wave
        #    ordering inside each group.
        grouping_graph = nx.Graph()
        for wf_id in workflow_ids:
            grouping_graph.add_node(wf_id)

        all_table_ids = (
            set(table_creators.keys())
            | set(table_readers.keys())
            | set(table_writers.keys())
        )
        for table_id in all_table_ids:
            wfs_referencing_table: Set[str] = set()
            wfs_referencing_table.update(
                table_creators.get(table_id, set())
            )
            wfs_referencing_table.update(
                table_readers.get(table_id, set())
            )
            wfs_referencing_table.update(
                table_writers.get(table_id, set())
            )
            wfs_list = list(wfs_referencing_table)
            for i in range(len(wfs_list)):
                for j in range(i + 1, len(wfs_list)):
                    if not grouping_graph.has_edge(wfs_list[i], wfs_list[j]):
                        grouping_graph.add_edge(
                            wfs_list[i], wfs_list[j],
                            shared_table=table_id,
                        )

        components_list = list(nx.connected_components(grouping_graph))
        sorted_components = self._sorted_components(components_list, nodes_dict)
        components_list = [set(c) for c in sorted_components]

        # 5. Order groups by inter-group dependencies (topological sort)
        ordered_indices = self._order_groups(
            components_list, wf_graph, nodes_dict, table_creators
        )

        # 6-7. Build group structures: sub-group by FILE, wave within file
        groups = []
        for group_idx in ordered_indices:
            group_wf_ids = components_list[group_idx]
            try:
                group_subgraph = wf_graph.subgraph(group_wf_ids).copy()

                # Sub-group workflows by FILE
                file_groups: Dict[str, List[str]] = {}
                unassigned: List[str] = []
                for wf_id in group_wf_ids:
                    file_id = workflow_to_file.get(wf_id)
                    if file_id:
                        file_groups.setdefault(file_id, []).append(wf_id)
                    else:
                        unassigned.append(wf_id)

                # Fallback: synthetic file when no FILE nodes
                if not file_groups:
                    file_groups["_synthetic_"] = list(group_wf_ids)
                elif unassigned:
                    file_groups["_unassigned_"] = unassigned

                # Order files within the group by inter-file deps
                ordered_file_ids = self._order_files_in_group(
                    file_groups, group_subgraph, nodes_dict
                )

                # Build file entries with waves
                file_entries = []
                for file_id in ordered_file_ids:
                    file_wf_ids = file_groups[file_id]
                    file_node = nodes_dict.get(file_id, {})
                    file_name = (
                        file_node.get("name", file_id)
                        if file_id not in ("_synthetic_", "_unassigned_")
                        else file_id
                    )

                    waves = self._create_informatica_waves(
                        file_wf_ids,
                        group_subgraph,
                        edges,
                        nodes_dict,
                        table_creators,
                        table_readers,
                    )

                    file_entries.append(
                        {
                            "file_id": file_id,
                            "file_name": file_name,
                            "workflows_count": len(file_wf_ids),
                            "waves": waves,
                        }
                    )

                # Group name from tables referenced by this group (for naming only)
                tables_involved: Set[str] = set()
                all_table_ids = (
                    set(table_creators.keys())
                    | set(table_readers.keys())
                    | set(table_writers.keys())
                )
                for table_id in all_table_ids:
                    referencing_wfs: Set[str] = set()
                    referencing_wfs.update(table_creators.get(table_id, set()))
                    referencing_wfs.update(table_readers.get(table_id, set()))
                    referencing_wfs.update(table_writers.get(table_id, set()))
                    if referencing_wfs & group_wf_ids:
                        tables_involved.add(table_id)

                group_name = self._generate_group_name(
                    tables_involved, nodes_dict, group_idx
                )

                groups.append(
                    {
                        "group_number": group_idx + 1,
                        "group_name": group_name,
                        "workflows_count": len(group_wf_ids),
                        "files_count": len(file_entries),
                        "files": file_entries,
                        "waves": [],  # empty, kept for backward compat
                    }
                )
            except Exception as e:
                log.error("Failed to build group %s: %s", group_idx + 1, e)
                groups.append(
                    {
                        "group_number": group_idx + 1,
                        "group_name": f"Group {group_idx + 1} (error)",
                        "workflows_count": len(group_wf_ids),
                        "files_count": 0,
                        "files": [],
                        "waves": [],
                    }
                )

        # Pre-existing tables: referenced but never explicitly CREATEd.
        # WRITES_TO does not imply DDL — only CREATES edges do.
        pre_existing_tables = self._identify_pre_existing_tables(
            nodes_dict, table_creators, table_readers, table_writers
        )

        table_dependencies = {
            "created_tables": {
                table_id: {
                    "table_name": nodes_dict.get(table_id, {}).get(
                        "name", table_id
                    ),
                    "created_by_workflows": [
                        nodes_dict.get(wf, {}).get("name", wf) for wf in wfs
                    ],
                }
                for table_id, wfs in table_creators.items()
            },
            "pre_existing_tables": {
                t["table_id"]: {
                    "table_name": t["table_name"],
                    "referenced_by": t["referencing_file_names"],
                }
                for t in pre_existing_tables
            },
        }

        log.info(
            f"Computed Informatica migration order: {len(groups)} groups, "
            f"{len(workflow_ids)} workflows, "
            f"{len(pre_existing_tables)} pre-existing tables"
        )

        return {
            "migration_unit": "WORKFLOW",
            "groups": groups,
            "total_nodes": len(workflow_ids),
            "total_groups": len(groups),
            "has_cycles": has_cycles,
            "cycle_info": cycle_info,
            "pre_existing_tables": pre_existing_tables,
            "table_dependencies": table_dependencies,
        }

    def _order_files_in_group(
        self,
        file_groups: Dict[str, List[str]],
        group_subgraph: nx.DiGraph,
        nodes_dict: Dict[str, Any],
    ) -> List[str]:
        """Order files within a group by inter-file workflow dependencies."""
        file_dep = nx.DiGraph()
        for fid in file_groups:
            file_dep.add_node(fid)

        for fid_a, wfs_a in file_groups.items():
            for fid_b, wfs_b in file_groups.items():
                if fid_a == fid_b:
                    continue
                # If any workflow in fid_a depends on a workflow in fid_b
                for wf_a in wfs_a:
                    for wf_b in wfs_b:
                        if group_subgraph.has_edge(wf_b, wf_a):
                            if not file_dep.has_edge(fid_b, fid_a):
                                file_dep.add_edge(fid_b, fid_a)

        try:
            return self._sorted_topo(file_dep, nodes_dict)
        except nx.NetworkXError:
            return sorted(file_groups.keys())

    def _create_informatica_waves(
        self,
        file_wf_ids: List[str],
        group_subgraph: nx.DiGraph,
        edges: List[Dict[str, Any]],
        nodes_dict: Dict[str, Any],
        table_creators: Dict[str, Set[str]],
        table_readers: Dict[str, Set[str]],
    ) -> List[Dict[str, Any]]:
        """Create waves of workflows within a single file."""
        file_subgraph = group_subgraph.subgraph(file_wf_ids).copy()

        try:
            generations = list(nx.topological_generations(file_subgraph))
            generations = self._sorted_generations(generations, nodes_dict)
        except (nx.NetworkXError, RuntimeError, Exception):
            generations = [file_wf_ids]

        waves: List[Dict[str, Any]] = []
        for wave_num, generation in enumerate(generations, start=1):
            wave_nodes = []
            for wf_id in generation:
                wf_node = nodes_dict.get(wf_id)
                if not wf_node:
                    continue

                sessions = self._get_workflow_children(
                    wf_id, edges, nodes_dict, NodeTypeHelper.SESSION
                )
                mappings = self._get_workflow_mappings(
                    wf_id, edges, nodes_dict
                )

                upstream = [
                    nodes_dict.get(p, {}).get("name", p)
                    for p in group_subgraph.predecessors(wf_id)
                ]
                downstream = [
                    nodes_dict.get(s, {}).get("name", s)
                    for s in group_subgraph.successors(wf_id)
                ]

                # Pre-existing tables: tables this workflow reads that are not created in lineage
                wf_reads_tables = {
                    table_id
                    for table_id, readers in table_readers.items()
                    if wf_id in readers
                }
                pre_existing_table_ids = wf_reads_tables - set(table_creators.keys())
                pre_existing_tables = [
                    nodes_dict.get(t_id, {}).get("name", t_id)
                    for t_id in pre_existing_table_ids
                ]

                if not upstream:
                    rationale = "No dependencies - can be migrated first"
                else:
                    rationale = f"Depends on {len(upstream)} workflow(s)"

                wave_nodes.append(
                    {
                        "node_id": wf_id,
                        "name": wf_node.get("name", wf_id),
                        "type": "WORKFLOW",
                        "sessions": sessions,
                        "mappings": mappings,
                        "upstream_count": len(upstream),
                        "downstream_count": len(downstream),
                        "upstream_workflows": upstream,
                        "downstream_workflows": downstream,
                        "pre_existing_tables": pre_existing_tables,
                        "pre_existing_table_count": len(pre_existing_tables),
                        "rationale": rationale,
                    }
                )

            if wave_nodes:
                wave_pre_existing: Set[str] = set()
                for n in wave_nodes:
                    wave_pre_existing.update(n.get("pre_existing_tables", []))
                waves.append({
                    "wave_number": wave_num,
                    "nodes": wave_nodes,
                    "pre_existing_tables": sorted(wave_pre_existing),
                    "pre_existing_table_count": len(wave_pre_existing),
                })

        return waves

    @staticmethod
    def _get_workflow_children(
        wf_id: str,
        edges: List[Dict[str, Any]],
        nodes_dict: Dict[str, Any],
        child_type: str,
    ) -> List[str]:
        """Return names of direct CONTAINS children of *wf_id* with given type."""
        children = []
        for edge in edges:
            if (
                edge.get("relationship") == EdgeRelationshipHelper.CONTAINS_RELATIONSHIP
                and edge["source"] == wf_id
            ):
                child = nodes_dict.get(edge["target"])
                if child and child.get("type") == child_type:
                    children.append(child.get("name", edge["target"]))
        return children

    @staticmethod
    def _get_workflow_mappings(
        wf_id: str,
        edges: List[Dict[str, Any]],
        nodes_dict: Dict[str, Any],
    ) -> List[str]:
        """Return mapping names for a workflow via SESSION CONTAINS chain."""
        sessions: Set[str] = set()
        for edge in edges:
            if (
                edge.get("relationship") == EdgeRelationshipHelper.CONTAINS_RELATIONSHIP
                and edge["source"] == wf_id
            ):
                child = nodes_dict.get(edge["target"])
                if child and child.get("type") == NodeTypeHelper.SESSION:
                    sessions.add(edge["target"])

        mappings: List[str] = []
        for edge in edges:
            if (
                edge.get("relationship") == EdgeRelationshipHelper.CONTAINS_RELATIONSHIP
                and edge["source"] in sessions
            ):
                child = nodes_dict.get(edge["target"])
                if child and child.get("type") == NodeTypeHelper.MAPPING:
                    mappings.append(child.get("name", edge["target"]))
        return mappings

    # ------------------------------------------------------------------
    # SQL: existing FILE-level helpers
    # ------------------------------------------------------------------

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
        actor_type = NodeTypeHelper.detect_actor_type(nodes_dict)

        # Add all actor nodes
        for node_id, node in nodes_dict.items():
            if node.get("type") == actor_type:
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
        actor_type = NodeTypeHelper.detect_actor_type(nodes_dict)

        # Add all actor nodes
        for node in nodes:
            if node.get("type") == actor_type:
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
        
        # Find connected components (sorted for deterministic output)
        components = list(nx.connected_components(G_undirected))
        sorted_components = self._sorted_components(components, nodes_dict)
        result = [set(c) for c in sorted_components]

        log.info(f"Identified {len(result)} file groups using connected components")

        return result
    
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
            # Use topological generations (sorted for deterministic output)
            generations = list(nx.topological_generations(group_subgraph))
            generations = self._sorted_generations(generations, nodes_dict)

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
                    wave_pre_existing: Set[str] = set()
                    for n in wave_nodes:
                        wave_pre_existing.update(n.get("pre_existing_tables", []))
                    waves.append({
                        "wave_number": wave_num,
                        "nodes": wave_nodes,
                        "pre_existing_tables": sorted(wave_pre_existing),
                        "pre_existing_table_count": len(wave_pre_existing),
                    })
        
        except (nx.NetworkXError, RuntimeError, Exception) as e:
            # If topological sort fails due to cycles, create single wave
            log.warning(f"Topological sort failed for group (likely due to cycles): {e}")
            all_nodes = []
            actor_type = NodeTypeHelper.detect_actor_type(nodes_dict)
            for node_id in group_file_ids:
                node = nodes_dict.get(node_id)
                if not node or node.get("type") != actor_type:
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
            
            wave_pre_existing: Set[str] = set()
            for n in all_nodes:
                wave_pre_existing.update(n.get("pre_existing_tables", []))
            waves = [{
                "wave_number": 1,
                "nodes": all_nodes,
                "pre_existing_tables": sorted(wave_pre_existing),
                "pre_existing_table_count": len(wave_pre_existing),
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
        
        # Use topological sort with deterministic tie-breaking
        try:
            ordered_indices = self._sorted_topo(group_graph, nodes_dict)
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




