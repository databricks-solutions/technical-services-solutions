"""Talend-specific intent builder.

This module implements intent generation specifically for Talend ETL jobs.
"""

from typing import Any, Dict, List

from migration_accelerator.discovery.intent.base import BaseIntentBuilder
from migration_accelerator.discovery.intent.registry import register_intent_builder
from migration_accelerator.utils.files import read_json
from migration_accelerator.utils.logger import get_logger

log = get_logger()


@register_intent_builder("talend")
class TalendIntentBuilder(BaseIntentBuilder):
    """Intent builder specifically for Talend ETL jobs.

    This builder reads parsed Talend .item files and generates
    comprehensive intent including ETL flow, sources, targets,
    transformations, and functional summary.
    """

    def _load_parsed_content(self) -> Dict[str, Any]:
        """Load parsed Talend content from the parsing step.

        Returns:
            Dict[str, Any]: Parsed Talend content

        Raises:
            FileNotFoundError: If parsed content not found
        """
        log.info("Loading parsed Talend content")

        if not self.parsed_content_path:
            # Try to find parsed content based on source file
            from migration_accelerator.utils.environment import (
                get_migration_accelerator_base_directory,
            )

            base_dir = get_migration_accelerator_base_directory()
            parsed_dir = base_dir / "executor_output" / "talend"
            parsed_filename = f"{self.source_file.stem}_parsed.json"
            self.parsed_content_path = parsed_dir / parsed_filename

        if not self.parsed_content_path.exists():
            raise FileNotFoundError(
                f"Parsed content not found at: {self.parsed_content_path}. "
                "Please run the parsing step first."
            )

        log.info(f"Loading from: {self.parsed_content_path}")
        parsed_content = read_json(self.parsed_content_path)

        return parsed_content

    def _extract_etl_components(self, parsed_content: Dict[str, Any]) -> Dict[str, Any]:
        """Extract ETL components from parsed Talend content.

        For Talend, this involves:
        - Extracting nodes (components)
        - Extracting connections between nodes
        - Extracting subjobs
        - Extracting context variables

        Args:
            parsed_content: Parsed Talend content

        Returns:
            Dict[str, Any]: Extracted ETL components
        """
        log.info("Extracting ETL components from Talend job")

        # TODO: Implement extraction logic using LLM or rule-based approach
        # This is a placeholder structure showing what should be extracted

        components = {
            "nodes": [],  # Talend components (tFileInputDelimited, tMap, etc.)
            "connections": [],  # Connections between components
            "subjobs": [],  # Subjobs
            "context_variables": [],  # Context variables
            "metadata": {},  # Metadata from parsed content
        }

        # Extract from parsed content
        if "content" in parsed_content:
            content = parsed_content["content"]

            # Extract nodes
            if "node" in content:
                components["nodes"] = self._process_talend_nodes(content["node"])

            # Extract connections
            if "connection" in content:
                components["connections"] = self._process_talend_connections(
                    content["connection"]
                )

            # Extract subjobs
            if "subjob" in content:
                components["subjobs"] = content["subjob"]

            # Extract context variables
            if "context_variables" in content:
                components["context_variables"] = content["context_variables"]

        if "metadata" in parsed_content:
            components["metadata"] = parsed_content["metadata"]

        log.info(
            f"Extracted {len(components['nodes'])} nodes, "
            f"{len(components['connections'])} connections"
        )

        return components

    def _process_talend_nodes(self, nodes: Any) -> List[Dict[str, Any]]:
        """Process Talend nodes into structured format.

        Args:
            nodes: Raw nodes from parsed content

        Returns:
            List[Dict[str, Any]]: Processed nodes
        """
        # TODO: Implement using LLM to understand node configurations
        # Placeholder implementation
        processed_nodes = []

        if isinstance(nodes, dict):
            # Single node or dict of nodes
            for node_name, node_info in nodes.items():
                processed_nodes.append(
                    {
                        "name": node_name,
                        "type": self._extract_node_type(node_name),
                        "config": node_info if isinstance(node_info, dict) else {},
                    }
                )
        elif isinstance(nodes, list):
            for node in nodes:
                if isinstance(node, dict) and "name" in node:
                    processed_nodes.append(node)

        return processed_nodes

    def _process_talend_connections(self, connections: Any) -> List[Dict[str, Any]]:
        """Process Talend connections into structured format.

        Args:
            connections: Raw connections from parsed content

        Returns:
            List[Dict[str, Any]]: Processed connections
        """
        # TODO: Implement connection processing
        processed_connections = []

        if isinstance(connections, list):
            for conn in connections:
                if isinstance(conn, dict) and "attributes" in conn:
                    processed_connections.append(
                        {
                            "source": conn["attributes"].get("source"),
                            "target": conn["attributes"].get("target"),
                            "type": conn["attributes"].get("connectorName"),
                            "label": conn["attributes"].get("label"),
                        }
                    )

        return processed_connections

    def _extract_node_type(self, node_name: str) -> str:
        """Extract Talend component type from node name.

        Args:
            node_name: Node name (e.g., tFileInputDelimited_1)

        Returns:
            str: Component type (e.g., tFileInputDelimited)
        """
        # Remove trailing numbers and underscores
        import re

        match = re.match(r"([a-zA-Z]+)", node_name)
        return match.group(1) if match else node_name

    def _extract_sources(self, etl_components: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract source systems from Talend components.

        Talend input components typically include:
        - tFileInputDelimited
        - tDBInput
        - tOracleInput
        - tMySQLInput
        - etc.

        Args:
            etl_components: Extracted ETL components

        Returns:
            List[Dict[str, Any]]: List of sources
        """
        log.info("Extracting sources from Talend components")

        # TODO: Implement using LLM to understand source configurations
        sources = []

        source_component_types = [
            "tFileInput",
            "tDBInput",
            "tOracleInput",
            "tMySQLInput",
            "tPostgresqlInput",
            "tS3Input",
            "tHDFSInput",
        ]

        for node in etl_components.get("nodes", []):
            node_type = node.get("type", "")

            # Check if it's a source component
            if any(src_type in node_type for src_type in source_component_types):
                sources.append(
                    {
                        "name": node.get("name"),
                        "type": node_type,
                        "component": node_type,
                        "connection": {},  # TODO: Extract connection details
                        "schema": {},  # TODO: Extract schema if available
                    }
                )

        log.info(f"Extracted {len(sources)} sources")
        return sources

    def _extract_targets(self, etl_components: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract target systems from Talend components.

        Talend output components typically include:
        - tFileOutputDelimited
        - tDBOutput
        - tOracleOutput
        - tMySQLOutput
        - etc.

        Args:
            etl_components: Extracted ETL components

        Returns:
            List[Dict[str, Any]]: List of targets
        """
        log.info("Extracting targets from Talend components")

        # TODO: Implement using LLM to understand target configurations
        targets = []

        target_component_types = [
            "tFileOutput",
            "tDBOutput",
            "tOracleOutput",
            "tMySQLOutput",
            "tPostgresqlOutput",
            "tS3Output",
            "tHDFSOutput",
        ]

        for node in etl_components.get("nodes", []):
            node_type = node.get("type", "")

            # Check if it's a target component
            if any(tgt_type in node_type for tgt_type in target_component_types):
                targets.append(
                    {
                        "name": node.get("name"),
                        "type": node_type,
                        "component": node_type,
                        "connection": {},  # TODO: Extract connection details
                        "schema": {},  # TODO: Extract schema if available
                    }
                )

        log.info(f"Extracted {len(targets)} targets")
        return targets

    def _extract_transformations(
        self, etl_components: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Extract transformations from Talend components.

        Talend transformation components include:
        - tMap
        - tFilterRow
        - tAggregateRow
        - tJoin
        - tSortRow
        - etc.

        Args:
            etl_components: Extracted ETL components

        Returns:
            List[Dict[str, Any]]: List of transformations
        """
        log.info("Extracting transformations from Talend components")

        # TODO: Implement using LLM to understand transformation logic
        transformations = []

        transformation_types = [
            "tMap",
            "tFilterRow",
            "tAggregateRow",
            "tJoin",
            "tSortRow",
            "tUnite",
            "tNormalize",
            "tDenormalize",
        ]

        for node in etl_components.get("nodes", []):
            node_type = node.get("type", "")

            # Check if it's a transformation component
            if any(trans_type in node_type for trans_type in transformation_types):
                transformations.append(
                    {
                        "name": node.get("name"),
                        "type": node_type,
                        "component": node_type,
                        "logic": {},  # TODO: Extract transformation logic
                        "input": [],  # TODO: Extract input columns
                        "output": [],  # TODO: Extract output columns
                    }
                )

        log.info(f"Extracted {len(transformations)} transformations")
        return transformations

    def _analyze_etl_flow(self, etl_components: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze ETL flow in Talend job.

        This traces the data flow from sources through transformations to targets
        using the connection information.

        Args:
            etl_components: Extracted ETL components

        Returns:
            Dict[str, Any]: ETL flow analysis
        """
        log.info("Analyzing ETL flow")

        # TODO: Implement flow analysis using graph traversal or LLM
        flow = {
            "flow_type": "unknown",  # linear, branching, parallel
            "steps": [],  # Ordered list of processing steps
            "data_lineage": {},  # Data lineage mapping
            "complexity": {
                "node_count": len(etl_components.get("nodes", [])),
                "connection_count": len(etl_components.get("connections", [])),
                "subjob_count": len(etl_components.get("subjobs", [])),
            },
        }

        # Build flow graph from connections
        # TODO: Implement graph traversal to determine flow type and steps
        # Will use etl_components.get("connections", []) for graph analysis

        log.info(f"Flow complexity: {flow['complexity']}")
        return flow

    def _extract_business_logic(self, etl_components: Dict[str, Any]) -> Dict[str, Any]:
        """Extract business logic from Talend components.

        Args:
            etl_components: Extracted ETL components

        Returns:
            Dict[str, Any]: Business logic details
        """
        log.info("Extracting business logic")

        # TODO: Implement using LLM to understand business rules
        business_logic = {
            "rules": [],  # Business rules
            "conditions": [],  # Conditional logic (from tFilterRow, tMap)
            "calculations": [],  # Calculations (from tMap expressions)
            "validations": [],  # Data validation rules
        }

        # Extract from tMap and tFilterRow components
        for node in etl_components.get("nodes", []):
            node_type = node.get("type", "")

            if "tMap" in node_type:
                # TODO: Extract tMap expressions and calculations
                pass
            elif "tFilterRow" in node_type:
                # TODO: Extract filter conditions
                pass

        return business_logic

    def _extract_dependencies(self, etl_components: Dict[str, Any]) -> List[str]:
        """Extract external dependencies from Talend job.

        Args:
            etl_components: Extracted ETL components

        Returns:
            List[str]: List of external dependencies
        """
        log.info("Extracting dependencies")

        # TODO: Implement dependency extraction
        dependencies = []

        # Context variables are dependencies
        context_vars = etl_components.get("context_variables", [])
        for var in context_vars:
            if isinstance(var, dict) and "name" in var:
                dependencies.append(f"context.{var['name']}")

        return dependencies

    def _generate_functional_summary(
        self,
        sources: List[Dict[str, Any]],
        targets: List[Dict[str, Any]],
        transformations: List[Dict[str, Any]],
        etl_flow: Dict[str, Any],
        business_logic: Dict[str, Any],
    ) -> str:
        """Generate functional summary for Talend job.

        Args:
            sources: Extracted sources
            targets: Extracted targets
            transformations: Extracted transformations
            etl_flow: Analyzed ETL flow
            business_logic: Extracted business logic

        Returns:
            str: Functional summary
        """
        log.info("Generating functional summary")

        if self.use_ai and self.llm_config:
            # TODO: Use LLM to generate comprehensive summary
            summary = self._generate_ai_summary(
                sources, targets, transformations, etl_flow, business_logic
            )
        else:
            # Generate rule-based summary
            summary = self._generate_rule_based_summary(
                sources, targets, transformations, etl_flow
            )

        return summary

    def _generate_ai_summary(
        self,
        sources: List[Dict[str, Any]],
        targets: List[Dict[str, Any]],
        transformations: List[Dict[str, Any]],
        etl_flow: Dict[str, Any],
        business_logic: Dict[str, Any],
    ) -> str:
        """Generate AI-powered functional summary.

        Args:
            sources: Extracted sources
            targets: Extracted targets
            transformations: Extracted transformations
            etl_flow: Analyzed ETL flow
            business_logic: Extracted business logic

        Returns:
            str: AI-generated functional summary
        """
        # TODO: Implement LLM-based summary generation
        log.info("Generating AI-powered summary")

        summary = (
            f"This Talend job processes data from {len(sources)} source(s) "
            f"through {len(transformations)} transformation(s) "
            f"to {len(targets)} target(s)."
        )

        return summary

    def _generate_rule_based_summary(
        self,
        sources: List[Dict[str, Any]],
        targets: List[Dict[str, Any]],
        transformations: List[Dict[str, Any]],
        etl_flow: Dict[str, Any],
    ) -> str:
        """Generate rule-based functional summary.

        Args:
            sources: Extracted sources
            targets: Extracted targets
            transformations: Extracted transformations
            etl_flow: Analyzed ETL flow

        Returns:
            str: Rule-based functional summary
        """
        log.info("Generating rule-based summary")

        source_names = [s.get("name", "unknown") for s in sources]
        target_names = [t.get("name", "unknown") for t in targets]
        trans_types = [t.get("type", "unknown") for t in transformations]

        summary = f"""
Talend Job: {self.source_file.stem}

Sources ({len(sources)}):
{', '.join(source_names) if source_names else 'None'}

Transformations ({len(transformations)}):
{', '.join(trans_types) if trans_types else 'None'}

Targets ({len(targets)}):
{', '.join(target_names) if target_names else 'None'}

Complexity:
- Nodes: {etl_flow['complexity']['node_count']}
- Connections: {etl_flow['complexity']['connection_count']}
- Subjobs: {etl_flow['complexity']['subjob_count']}

This job extracts data from {len(sources)} source(s), applies {len(transformations)}
transformation(s), and loads the results into {len(targets)} target(s).
        """.strip()

        return summary
