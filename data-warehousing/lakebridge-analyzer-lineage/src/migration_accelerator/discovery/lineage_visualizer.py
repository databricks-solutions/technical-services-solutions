# flake8: noqa
"""
Interactive Knowledge Graph Visualizer for Data Lineage

This module provides comprehensive functionality for converting pandas DataFrames
into interactive knowledge graph visualizations, specifically designed for
data lineage analysis showing upstream/downstream relationships between
scripts, tables, and files.
"""

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

import networkx as nx
import pandas as pd

from migration_accelerator.configs.modules import LLMConfig
from migration_accelerator.core.graph_transformer import LLMGraphTransformer
from migration_accelerator.core.llms import LLMManager
from migration_accelerator.utils.logger import get_logger

# Optional imports for visualization
try:
    from pyvis.network import Network

    PYVIS_AVAILABLE = True
except ImportError:
    PYVIS_AVAILABLE = False

try:
    import plotly.graph_objects as go

    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

log = get_logger()


@dataclass
class LineageNode:
    """Represents a node in the lineage graph"""

    id: str
    name: str
    type: str  # 'script', 'table', 'file', 'database', 'view'
    properties: Dict[str, Any] = None

    def __post_init__(self):
        if self.properties is None:
            self.properties = {}


@dataclass
class LineageEdge:
    """Represents an edge in the lineage graph"""

    source: str
    target: str
    relationship: str  # 'reads', 'writes', 'transforms', 'depends_on'
    properties: Dict[str, Any] = None

    def __post_init__(self):
        if self.properties is None:
            self.properties = {}


class DataLineageVisualizer:
    """
    Interactive Knowledge Graph Visualizer for Data Lineage

    This class transforms pandas DataFrames containing script-table/file relationships
    into interactive knowledge graphs, supporting multiple visualization backends
    and optional LLM-based enhancement.
    """

    def __init__(
        self,
        llm_config: Optional[LLMConfig] = None,
        enable_llm_enhancement: bool = False,
    ):
        """
        Initialize the Data Lineage Visualizer

        Args:
            llm_config: Configuration for LLM integration (optional)
            enable_llm_enhancement: Whether to use LLM for graph enhancement
        """
        self.llm_config = llm_config
        self.enable_llm_enhancement = enable_llm_enhancement
        self.graph = nx.DiGraph()
        self.nodes: Dict[str, LineageNode] = {}
        self.edges: List[LineageEdge] = []

        if self.enable_llm_enhancement and self.llm_config:
            self.llm_manager = LLMManager(self.llm_config)
            self.graph_transformer = LLMGraphTransformer(
                llm=self.llm_manager.get_llm(),
                allowed_nodes=["Script", "Table", "File", "Database", "View", "Column"],
                allowed_relationships=[
                    "READS_FROM",
                    "WRITES_TO",
                    "DELETES_FROM",
                    "CREATES",
                    "DROPS",
                    "TRANSFORMS",
                    "DEPENDS_ON",
                    "CONTAINS",
                ],
                node_properties=True,
                relationship_properties=True,
            )

    def parse_dataframe_lineage(
        self,
        df: pd.DataFrame,
        script_column: str = None,
        relationship_indicator: str = "src",
        table_file_columns: List[str] = None,
    ) -> None:
        """
        Parse pandas DataFrame to extract lineage relationships

        Args:
            df: DataFrame with scripts in rows and tables/files in columns
            script_column: Name of column containing script names (default: first column)
            relationship_indicator: Value indicating a relationship exists (default: 'src')
            table_file_columns: List of column names representing tables/files (default: all except first)
        """
        log.info("Parsing DataFrame for lineage relationships")

        # Determine script column
        if script_column is None:
            script_column = df.columns[0]

        # Determine table/file columns
        if table_file_columns is None:
            table_file_columns = [col for col in df.columns if col != script_column]

        # Clear existing graph data
        self.graph.clear()
        self.nodes.clear()
        self.edges.clear()

        # Process each row (script)
        for idx, row in df.iterrows():
            script_name = str(row[script_column])
            if pd.isna(script_name) or script_name.strip() == "":
                continue

            # Add script node
            self._add_node(script_name, "Script")

            # Process relationships with tables/files
            for table_col in table_file_columns:
                relationship_value = str(row[table_col]).lower().strip()

                if relationship_value and relationship_value not in ["nan", "", "none"]:
                    # Add table/file node
                    self._add_node(table_col, self._infer_node_type(table_col))

                    # Parse relationship value - handle comma-separated values and complex patterns
                    relationship_parts = [
                        part.strip().lower() for part in relationship_value.split(",")
                    ]

                    # Track what types of relationships we found
                    has_read = False
                    has_write = False

                    for part in relationship_parts:
                        # Handle 'READ: 1' or 'WRITE: 1' patterns
                        if ":" in part:
                            rel_type, value = part.split(":", 1)
                            rel_type = rel_type.strip().lower()
                            value = value.strip()

                            if rel_type == "read" and value in ["1", "true", "yes"]:
                                has_read = True
                            elif rel_type == "write" and value in ["1", "true", "yes"]:
                                has_write = True
                        else:
                            # Handle simple relationship indicators
                            # 'src', 'lkp' (lookup) both indicate reading from table/file
                            if part in ["src", "lkp", "source", "lookup"]:
                                has_read = True
                            elif part in ["tgt", "target", "write", "output"]:
                                has_write = True
                            elif part in ["both", "read_write"]:
                                has_read = True
                                has_write = True

                    # Add edges based on what relationships we found
                    if has_read:
                        # Script reads from table/file (including lookups)
                        self._add_edge(table_col, script_name, "READS_FROM")
                    if has_write:
                        # Script writes to table/file
                        self._add_edge(script_name, table_col, "WRITES_TO")

                    # If no recognized pattern, create generic dependency
                    if not has_read and not has_write:
                        self._add_edge(table_col, script_name, "DEPENDS_ON")

        log.info(f"Parsed lineage: {len(self.nodes)} nodes, {len(self.edges)} edges")

    def parse_cross_reference_dataframe(
        self,
        df: pd.DataFrame,
        source_column: str,
        target_column: str,
        relationship_column: Optional[str] = None,
        default_relationship: str = "DEPENDS_ON",
    ) -> None:
        """
        Parse cross-reference style DataFrame (e.g., Jobs Transformations Xref)

        Args:
            df: DataFrame with explicit source-target relationships
            source_column: Column name for source entities
            target_column: Column name for target entities
            relationship_column: Column name for relationship type (optional)
            default_relationship: Default relationship if none specified
        """
        log.info("Parsing cross-reference DataFrame for lineage")

        # Clear existing graph data
        self.graph.clear()
        self.nodes.clear()
        self.edges.clear()
        
        temp_tables_filtered = 0

        for idx, row in df.iterrows():
            source = str(row[source_column])
            target = str(row[target_column])

            if (
                pd.isna(source)
                or pd.isna(target)
                or source.strip() == ""
                or target.strip() == ""
            ):
                continue
            
            # Filter temporary tables (single # = local temp, skip them)
            # Global temp tables (##) are kept with special type
            if source.startswith('#') and not source.startswith('##'):
                temp_tables_filtered += 1
                continue
            if target.startswith('#') and not target.startswith('##'):
                temp_tables_filtered += 1
                continue

            # Add nodes
            source_type = "GLOBAL_TEMP_TABLE" if source.startswith('##') else self._infer_node_type(source)
            target_type = "GLOBAL_TEMP_TABLE" if target.startswith('##') else self._infer_node_type(target)
            
            self._add_node(source, source_type)
            self._add_node(target, target_type)

            # Determine relationship
            relationship = default_relationship
            if relationship_column and relationship_column in df.columns:
                rel_value = str(row[relationship_column])
                if not pd.isna(rel_value) and rel_value.strip():
                    relationship = rel_value.upper().replace(" ", "_")

            # Add edge
            self._add_edge(source, target, relationship)
        
        if temp_tables_filtered > 0:
            log.info(f"Filtered {temp_tables_filtered} local temp tables (starting with #)")

        log.info(
            f"Parsed cross-reference lineage: {len(self.nodes)} nodes, {len(self.edges)} edges"
        )

    def _add_node(
        self, node_id: str, node_type: str, properties: Dict[str, Any] = None
    ) -> None:
        """Add a node to the graph"""
        if node_id not in self.nodes:
            self.nodes[node_id] = LineageNode(
                id=node_id, name=node_id, type=node_type, properties=properties or {}
            )
            self.graph.add_node(node_id, type=node_type, **(properties or {}))

    def _add_edge(
        self,
        source: str,
        target: str,
        relationship: str,
        properties: Dict[str, Any] = None,
    ) -> None:
        """Add an edge to the graph"""
        edge = LineageEdge(
            source=source,
            target=target,
            relationship=relationship,
            properties=properties or {},
        )
        self.edges.append(edge)
        self.graph.add_edge(
            source, target, relationship=relationship, **(properties or {})
        )

    def _infer_node_type(self, node_name: str) -> str:
        """Infer node type from name patterns"""
        name_lower = node_name.lower()

        if any(
            keyword in name_lower
            for keyword in ["job", "script", "proc", "package", "mapping"]
        ):
            return "Script"
        elif any(
            keyword in name_lower for keyword in ["table", "tbl", "_t", "_fact", "_dim"]
        ):
            return "Table"
        elif any(keyword in name_lower for keyword in ["view", "_v", "_vw"]):
            return "View"
        elif any(
            keyword in name_lower
            for keyword in ["file", ".csv", ".txt", ".xml", ".json", ".parquet"]
        ):
            return "File"
        elif any(keyword in name_lower for keyword in ["db", "database", "schema"]):
            return "Database"
        else:
            # Default to table for unknown patterns
            return "Table"

    def enhance_with_llm(self, additional_context: str = "") -> None:
        """
        Use LLM to enhance the graph with additional insights using NetworkxEntityGraph

        Args:
            additional_context: Additional context about the data lineage
        """
        if not self.enable_llm_enhancement or not self.llm_config:
            log.warning("LLM enhancement not available - missing configuration")
            return

        log.info("Enhancing graph with LLM analysis using NetworkxEntityGraph")

        try:
            from langchain.chains import GraphQAChain
            from langchain_community.graphs import NetworkxEntityGraph
        except ImportError:
            log.warning(
                "NetworkxEntityGraph not available - falling back to basic enhancement"
            )
            self._basic_llm_enhancement(additional_context)
            return

        # Create NetworkxEntityGraph from our existing graph
        entity_graph = NetworkxEntityGraph()

        # Add all existing nodes and relationships to the entity graph
        for node in self.nodes.values():
            entity_graph.add_node(node.id)

        for edge in self.edges:
            entity_graph.add_triple((edge.source, edge.relationship, edge.target))

        # Create GraphQA chain for intelligent querying
        llm = self.llm_manager.get_llm()
        graph_qa_chain = GraphQAChain.from_llm(llm, graph=entity_graph, verbose=True)

        # Generate enhancement queries based on graph structure and context
        enhancement_queries = self._generate_enhancement_queries(additional_context)

        # Process each enhancement query
        for query in enhancement_queries:
            try:
                log.info(f"Processing enhancement query: {query}")
                response = graph_qa_chain.run(query)
                self._process_enhancement_response(response, query)
            except Exception as e:
                log.warning(f"Enhancement query failed: {query}. Error: {e}")
                continue

        # Use LLMGraphTransformer for additional relationship discovery
        self._discover_additional_relationships(additional_context)

        log.info("LLM enhancement completed")

    def _basic_llm_enhancement(self, additional_context: str) -> None:
        """Fallback enhancement method when NetworkxEntityGraph is not available"""
        log.info("Using basic LLM enhancement (text-based)")

        # Create context document for LLM analysis
        context = self._create_graph_context(additional_context)

        # Use LLMGraphTransformer to extract additional relationships
        from langchain_core.documents import Document

        doc = Document(page_content=context)

        graph_documents = self.graph_transformer.convert_to_graph_documents([doc])

        # Merge LLM-generated insights into existing graph
        for graph_doc in graph_documents:
            for node in graph_doc.nodes:
                if node.id not in self.nodes:
                    self._add_node(node.id, node.type, node.properties)

            for rel in graph_doc.relationships:
                self._add_edge(rel.source.id, rel.target.id, rel.type, rel.properties)

    def _generate_enhancement_queries(self, additional_context: str) -> List[str]:
        """Generate intelligent queries for graph enhancement"""
        base_queries = [
            "What are the most critical data sources in this lineage?",
            "Which scripts have the most complex dependencies?",
            "Are there any potential circular dependencies?",
            "What tables are only written to but never read from?",
            "What scripts read from the most data sources?",
            "Are there any orphaned tables or scripts?",
            "What are the main data flow paths in this system?",
        ]

        # Add context-specific queries
        context_queries = []
        if additional_context:
            context_lower = additional_context.lower()
            if "etl" in context_lower or "staging" in context_lower:
                context_queries.extend(
                    [
                        "Which scripts are part of the staging layer?",
                        "What is the data flow from staging to final tables?",
                    ]
                )
            if "migration" in context_lower:
                context_queries.extend(
                    [
                        "What are the key migration dependencies?",
                        "Which components need to be migrated first?",
                    ]
                )
            if "fact" in context_lower or "dimension" in context_lower:
                context_queries.extend(
                    [
                        "What are the fact and dimension table relationships?",
                        "How do dimension tables feed into fact tables?",
                    ]
                )

        return base_queries + context_queries

    def _process_enhancement_response(self, response: str, query: str) -> None:
        """Process LLM response and enhance graph with insights"""
        if not response or response.strip().lower() in ["none", "n/a", "not found"]:
            return

        # Extract entities mentioned in response
        response_lower = response.lower()

        # Look for mentioned entities that might be new or need property updates
        mentioned_entities = []
        for node_id in self.nodes.keys():
            if node_id.lower() in response_lower:
                mentioned_entities.append(node_id)

        # Add insights as node properties
        query_type = self._classify_query(query)

        for entity in mentioned_entities:
            if entity in self.nodes:
                # Add insight as node property
                insight_key = f"llm_insight_{query_type}"
                if insight_key not in self.nodes[entity].properties:
                    self.nodes[entity].properties[insight_key] = []

                # Store the insight
                self.nodes[entity].properties[insight_key].append(
                    {
                        "query": query,
                        "response": response[:200],  # Truncate long responses
                        "timestamp": pd.Timestamp.now().isoformat(),
                    }
                )

                # Update NetworkX graph properties
                self.graph.nodes[entity][insight_key] = self.nodes[entity].properties[
                    insight_key
                ]

    def _classify_query(self, query: str) -> str:
        """Classify the type of enhancement query"""
        query_lower = query.lower()

        if "critical" in query_lower or "important" in query_lower:
            return "criticality"
        elif "complex" in query_lower or "dependencies" in query_lower:
            return "complexity"
        elif "circular" in query_lower or "cycle" in query_lower:
            return "circular_dependency"
        elif "orphaned" in query_lower or "unused" in query_lower:
            return "utilization"
        elif "flow" in query_lower or "path" in query_lower:
            return "data_flow"
        else:
            return "general"

    def _discover_additional_relationships(self, additional_context: str) -> None:
        """Use LLMGraphTransformer to discover additional relationships"""

        # Create rich context including actual graph structure
        context = self._create_graph_context(additional_context)

        # Use LLMGraphTransformer with more specific instructions
        enhanced_transformer = LLMGraphTransformer(
            llm=self.llm_manager.get_llm(),
            allowed_nodes=[
                "Script",
                "Table",
                "File",
                "Database",
                "View",
                "Column",
                "Process",
                "System",
            ],
            allowed_relationships=[
                "READS_FROM",
                "WRITES_TO",
                "DELETES_FROM",
                "CREATES",
                "DROPS",
                "TRANSFORMS",
                "DEPENDS_ON",
                "FEEDS_INTO",
                "DERIVES_FROM",
                "VALIDATES",
                "TRIGGERS",
            ],
            node_properties=True,
            relationship_properties=True,
            additional_instructions=f"""
            Analyze this data lineage graph and identify:
            1. Missing implicit relationships between entities
            2. Transformation patterns not explicitly captured
            3. Data quality or validation relationships
            4. Business process flows
            5. System-level dependencies
            
            Focus on relationships that would be valuable for:
            - Migration impact analysis
            - Data quality assessment  
            - Performance optimization
            - Dependency management
            
            Context: {additional_context}
            """,
        )

        from langchain_core.documents import Document

        doc = Document(page_content=context)

        try:
            graph_documents = enhanced_transformer.convert_to_graph_documents([doc])

            # Merge discovered relationships
            for graph_doc in graph_documents:
                for node in graph_doc.nodes:
                    if node.id not in self.nodes:
                        # Add new discovered nodes
                        self._add_node(node.id, node.type, node.properties or {})

                for rel in graph_doc.relationships:
                    # Only add if relationship doesn't already exist
                    existing_edge = any(
                        e.source == rel.source.id and e.target == rel.target.id
                        for e in self.edges
                    )
                    if not existing_edge:
                        self._add_edge(
                            rel.source.id, rel.target.id, rel.type, rel.properties or {}
                        )
                        log.info(
                            f"Discovered new relationship: {rel.source.id} --{rel.type}--> {rel.target.id}"
                        )

        except Exception as e:
            log.warning(f"Additional relationship discovery failed: {e}")

    def _create_graph_context(self, additional_context: str) -> str:
        """Create comprehensive context including actual graph structure"""
        context_parts = [
            "Data Lineage Graph Analysis",
            "=" * 50,
            f"Total Entities: {len(self.nodes)}",
            f"Total Relationships: {len(self.edges)}",
            "",
            "ENTITIES BY TYPE:",
        ]

        # Add detailed node information
        type_counts = {}
        for node in self.nodes.values():
            type_counts[node.type] = type_counts.get(node.type, 0) + 1

        for node_type, count in type_counts.items():
            context_parts.append(f"- {node_type}: {count}")
            # Add examples of this type
            examples = [n.id for n in self.nodes.values() if n.type == node_type][:3]
            context_parts.append(f"  Examples: {', '.join(examples)}")

        context_parts.extend(
            [
                "",
                "RELATIONSHIPS:",
            ]
        )

        # Add detailed relationship information
        rel_counts = {}
        for edge in self.edges:
            rel_counts[edge.relationship] = rel_counts.get(edge.relationship, 0) + 1

        for rel_type, count in rel_counts.items():
            context_parts.append(f"- {rel_type}: {count}")
            # Add examples
            examples = [
                f"{e.source} -> {e.target}"
                for e in self.edges
                if e.relationship == rel_type
            ][:3]
            context_parts.append(f"  Examples: {'; '.join(examples)}")

        context_parts.extend(
            [
                "",
                "SAMPLE DATA FLOWS:",
            ]
        )

        # Add sample data flow paths
        try:
            # Find some interesting paths through the graph
            script_nodes = [n for n in self.nodes.values() if n.type == "Script"][:5]
            for script in script_nodes:
                # Find upstream and downstream for this script
                upstream = self.find_upstream_dependencies(script.id, max_depth=2)
                downstream = self.find_downstream_dependencies(script.id, max_depth=2)

                if upstream or downstream:
                    flow_desc = f"{script.id}:"
                    if upstream:
                        flow_desc += f" reads from {', '.join(upstream[:3])}"
                    if downstream:
                        flow_desc += f" writes to {', '.join(downstream[:3])}"
                    context_parts.append(f"- {flow_desc}")
        except Exception:
            pass  # Skip if graph analysis fails

        if additional_context:
            context_parts.extend(["", "ADDITIONAL CONTEXT:", additional_context])

        return "\n".join(context_parts)

    def create_pyvis_visualization(
        self,
        output_path: str = "lineage_graph.html",
        physics_enabled: bool = True,
        node_colors: Dict[str, str] = None,
        height: str = "800px",
        width: str = "100%",
    ) -> str:
        """
        Create interactive Pyvis visualization

        Args:
            output_path: Path to save HTML file
            physics_enabled: Enable physics simulation
            node_colors: Color mapping for different node types
            height: Height of visualization
            width: Width of visualization

        Returns:
            Path to generated HTML file
        """
        if not PYVIS_AVAILABLE:
            raise ImportError("Pyvis not available. Install with: pip install pyvis")

        log.info(f"Creating Pyvis visualization: {output_path}")

        # Default colors for different node types
        default_colors = {
            "Script": "#FF6B6B",  # Red
            "Table": "#4ECDC4",  # Teal
            "File": "#45B7D1",  # Blue
            "View": "#96CEB4",  # Green
            "Database": "#FFEAA7",  # Yellow
            "Column": "#DDA0DD",  # Plum
        }

        colors = {**default_colors, **(node_colors or {})}

        # Initialize network
        net = Network(
            height=height,
            width=width,
            directed=True,
            bgcolor="#ffffff",
            font_color="#000000",
        )

        if physics_enabled:
            net.set_options(
                """
            var options = {
              "physics": {
                "enabled": true,
                "hierarchicalRepulsion": {
                  "centralGravity": 0.0,
                  "springLength": 100,
                  "springConstant": 0.01,
                  "nodeDistance": 120,
                  "damping": 0.09
                },
                "maxVelocity": 50,
                "minVelocity": 0.1,
                "solver": "hierarchicalRepulsion",
                "timestep": 0.35,
                "stabilization": {"iterations": 150}
              }
            }
            """
            )

        # Add nodes
        for node in self.nodes.values():
            color = colors.get(node.type, "#97C2FC")

            # Create hover title with properties
            title_parts = [f"Type: {node.type}"]
            if node.properties:
                for key, value in node.properties.items():
                    title_parts.append(f"{key}: {value}")
            title = "\n".join(title_parts)

            net.add_node(
                node.id,
                label=node.name,
                title=title,
                color=color,
                size=25,
                font={"size": 14},
            )

        # Add edges with relationship labels
        edge_colors = {
            "READS_FROM": "#85C1E9",  # Light Blue
            "WRITES_TO": "#F1948A",  # Light Red (INSERT/UPDATE)
            "DELETES_FROM": "#E74C3C",  # Dark Red (DELETE/TRUNCATE - destructive)
            "DROPS": "#8E44AD",  # Purple (DROP - metadata destruction)
            "CREATES": "#52BE80",  # Green (CREATE)
            "TRANSFORMS": "#82E0AA",  # Light Green
            "DEPENDS_ON": "#D7DBDD",  # Light Gray
        }

        for edge in self.edges:
            color = edge_colors.get(edge.relationship, "#848484")

            # Create edge title
            title = f"{edge.relationship}"
            if edge.properties:
                prop_strs = [f"{k}: {v}" for k, v in edge.properties.items()]
                title += "\n" + "\n".join(prop_strs)

            net.add_edge(
                edge.source,
                edge.target,
                title=title,
                label=edge.relationship,
                color=color,
                width=2,
                arrows="to",
                font={"size": 10, "align": "middle"},
            )

        # Save and return path
        net.save_graph(output_path)
        log.info(f"Pyvis visualization saved to: {output_path}")

        return output_path

    def create_plotly_visualization(
        self, output_path: Optional[str] = None, layout_algorithm: str = "spring"
    ) -> Any:
        """
        Create Plotly-based interactive visualization

        Args:
            output_path: Optional path to save HTML file
            layout_algorithm: Layout algorithm ('spring', 'circular', 'random')

        Returns:
            Plotly figure object
        """
        if not PLOTLY_AVAILABLE:
            raise ImportError("Plotly not available. Install with: pip install plotly")

        log.info("Creating Plotly visualization")

        # Calculate layout positions
        if layout_algorithm == "spring":
            pos = nx.spring_layout(self.graph, k=3, iterations=50)
        elif layout_algorithm == "circular":
            pos = nx.circular_layout(self.graph)
        else:
            pos = nx.random_layout(self.graph)

        # Prepare node traces
        node_traces = {}
        node_colors = {
            "Script": "#FF6B6B",
            "Table": "#4ECDC4",
            "File": "#45B7D1",
            "View": "#96CEB4",
            "Database": "#FFEAA7",
            "Column": "#DDA0DD",
        }

        for node_type in set(node.type for node in self.nodes.values()):
            node_traces[node_type] = go.Scatter(
                x=[],
                y=[],
                mode="markers+text",
                name=node_type,
                text=[],
                textposition="middle center",
                hovertext=[],
                marker=dict(
                    size=20,
                    color=node_colors.get(node_type, "#97C2FC"),
                    line=dict(width=2, color="#000000"),
                ),
            )

        # Add node data
        for node in self.nodes.values():
            if node.id in pos:
                x, y = pos[node.id]
                node_trace = node_traces[node.type]
                node_trace.x = node_trace.x + (x,)
                node_trace.y = node_trace.y + (y,)
                node_trace.text = node_trace.text + (node.name,)

                # Create hover text
                hover_text = f"{node.name}<br>Type: {node.type}"
                if node.properties:
                    for key, value in node.properties.items():
                        hover_text += f"<br>{key}: {value}"
                node_trace.hovertext = node_trace.hovertext + (hover_text,)

        # Create edge traces
        edge_x, edge_y = [], []
        edge_info = []

        for edge in self.edges:
            if edge.source in pos and edge.target in pos:
                x0, y0 = pos[edge.source]
                x1, y1 = pos[edge.target]

                edge_x.extend([x0, x1, None])
                edge_y.extend([y0, y1, None])
                edge_info.append(
                    f"{edge.source} -> {edge.target} ({edge.relationship})"
                )

        edge_trace = go.Scatter(
            x=edge_x,
            y=edge_y,
            line=dict(width=1, color="#888"),
            hoverinfo="none",
            mode="lines",
            name="Relationships",
        )

        # Create figure
        fig = go.Figure()

        # Add edge trace first (so it appears behind nodes)
        fig.add_trace(edge_trace)

        # Add node traces
        for trace in node_traces.values():
            fig.add_trace(trace)

        # Update layout
        fig.update_layout(
            title="Data Lineage Knowledge Graph",
            titlefont_size=16,
            showlegend=True,
            hovermode="closest",
            margin=dict(b=20, l=5, r=5, t=40),
            annotations=[
                dict(
                    text="Interactive Data Lineage Visualization",
                    showarrow=False,
                    xref="paper",
                    yref="paper",
                    x=0.005,
                    y=-0.002,
                    xanchor="left",
                    yanchor="bottom",
                    font=dict(color="#000000", size=12),
                )
            ],
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            plot_bgcolor="white",
        )

        if output_path:
            fig.write_html(output_path)
            log.info(f"Plotly visualization saved to: {output_path}")

        return fig

    def get_lineage_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics about the lineage graph"""
        stats = {
            "nodes": {"total": len(self.nodes), "by_type": {}},
            "edges": {"total": len(self.edges), "by_relationship": {}},
            "graph_metrics": {},
        }

        # Node statistics
        for node in self.nodes.values():
            node_type = node.type
            stats["nodes"]["by_type"][node_type] = (
                stats["nodes"]["by_type"].get(node_type, 0) + 1
            )

        # Edge statistics
        for edge in self.edges:
            rel_type = edge.relationship
            stats["edges"]["by_relationship"][rel_type] = (
                stats["edges"]["by_relationship"].get(rel_type, 0) + 1
            )

        # Graph metrics
        if len(self.graph.nodes) > 0:
            stats["graph_metrics"] = {
                "density": nx.density(self.graph),
                "number_of_components": nx.number_weakly_connected_components(
                    self.graph
                ),
                "average_degree": sum(dict(self.graph.degree()).values())
                / len(self.graph.nodes),
            }

            # Find most connected nodes
            degree_centrality = nx.degree_centrality(self.graph)
            stats["graph_metrics"]["most_connected"] = sorted(
                degree_centrality.items(), key=lambda x: x[1], reverse=True
            )[:5]

        return stats

    def export_graph(
        self, format: str = "json", output_path: str = None
    ) -> Union[str, Dict]:
        """
        Export graph data in various formats

        Args:
            format: Export format ('json', 'graphml', 'gexf', 'edgelist')
            output_path: Path to save file (optional)

        Returns:
            Exported data or file path
        """
        if format.lower() == "json":
            graph_data = {
                "nodes": [
                    {
                        "id": node.id,
                        "name": node.name,
                        "type": node.type,
                        "properties": node.properties,
                    }
                    for node in self.nodes.values()
                ],
                "edges": [
                    {
                        "source": edge.source,
                        "target": edge.target,
                        "relationship": edge.relationship,
                        "properties": edge.properties,
                    }
                    for edge in self.edges
                ],
            }

            if output_path:
                with open(output_path, "w") as f:
                    json.dump(graph_data, f, indent=2)
                log.info(f"Graph exported to JSON: {output_path}")
                return output_path
            else:
                return graph_data

        elif format.lower() in ["graphml", "gexf", "edgelist"]:
            if not output_path:
                output_path = f"lineage_graph.{format.lower()}"

            if format.lower() == "graphml":
                nx.write_graphml(self.graph, output_path)
            elif format.lower() == "gexf":
                nx.write_gexf(self.graph, output_path)
            elif format.lower() == "edgelist":
                nx.write_edgelist(self.graph, output_path)

            log.info(f"Graph exported to {format.upper()}: {output_path}")
            return output_path

        else:
            raise ValueError(f"Unsupported export format: {format}")

    def find_upstream_dependencies(
        self, node_id: str, max_depth: int = None
    ) -> List[str]:
        """Find all upstream dependencies for a given node"""
        if node_id not in self.graph:
            return []

        upstream = []
        if max_depth:
            for source, _ in self.graph.in_edges(node_id):
                upstream.extend(self._traverse_upstream(source, max_depth - 1))
        else:
            upstream = list(nx.ancestors(self.graph, node_id))

        return list(set(upstream))

    def find_downstream_dependencies(
        self, node_id: str, max_depth: int = None
    ) -> List[str]:
        """Find all downstream dependencies for a given node"""
        if node_id not in self.graph:
            return []

        downstream = []
        if max_depth:
            for _, target in self.graph.out_edges(node_id):
                downstream.extend(self._traverse_downstream(target, max_depth - 1))
        else:
            downstream = list(nx.descendants(self.graph, node_id))

        return list(set(downstream))

    def _traverse_upstream(self, node_id: str, depth: int) -> List[str]:
        """Helper method for upstream traversal with depth limit"""
        if depth <= 0 or node_id not in self.graph:
            return [node_id] if node_id in self.graph else []

        result = [node_id]
        for source, _ in self.graph.in_edges(node_id):
            result.extend(self._traverse_upstream(source, depth - 1))

        return result

    def _traverse_downstream(self, node_id: str, depth: int) -> List[str]:
        """Helper method for downstream traversal with depth limit"""
        if depth <= 0 or node_id not in self.graph:
            return [node_id] if node_id in self.graph else []

        result = [node_id]
        for _, target in self.graph.out_edges(node_id):
            result.extend(self._traverse_downstream(target, depth - 1))

        return result
