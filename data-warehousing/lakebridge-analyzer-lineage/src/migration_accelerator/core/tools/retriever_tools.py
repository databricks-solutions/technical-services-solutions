"""Tools for retrieving information from offline/online corpora."""

from migration_accelerator.core.corpus import TALEND_CONNECTIONS, TALEND_NODES
from migration_accelerator.core.tools.utils import trace_tool_call
from migration_accelerator.utils.logger import get_logger

log = get_logger()


@trace_tool_call
def retrieve_talend_knowledge(component_name: str | list[str]) -> str:
    """Retrieve comprehensive knowledge about one or more Talend ETL components.

    This tool provides detailed documentation for Talend nodes (components) and
    connections from a curated knowledge base. Use this to understand what a
    component does, its parameters, metadata structure, and common use cases.

    The component type (node vs connection) is automatically detected:
    - Components starting with lowercase 't' are treated as NODES (e.g., tMap, tJava)
    - All other components are treated as CONNECTIONS (e.g., FLOW, ITERATE, LOOKUP)

    Args:
        component_name: Either a single component name (str) or a
        list of component names (list[str]).
            Examples: "tMap", "FLOW", ["tMap", "tJava", "FLOW"]
            Component names are case-sensitive for nodes, auto-uppercased for
            connections.

    Returns:
        - If single component: Detailed knowledge text with header
        - If multiple components: JSON-formatted dictionary string where keys are
          component names and values are the retrieved knowledge text
        - Returns error information for components that are not found

    Examples:
        >>> retrieve_talend_knowledge("tMap")
        # Returns: "=== Talend NODE: tMap ===\\n\\n[documentation...]"

        >>> retrieve_talend_knowledge("FLOW")
        # Returns: "=== Talend CONNECTION: FLOW ===\\n\\n[documentation...]"

        >>> retrieve_talend_knowledge(["tMap", "tJava", "FLOW"])
        # Returns: {
        # ... "tMap": "[documentation...]",
        # ... "tJava": "[documentation...]",
        # ... "FLOW": "[documentation...]"
        # ... }

    When to use this tool:
    - When you encounter unknown Talend component names in JSON
    - To understand component parameters and their meanings
    - To learn about connection types and their behavior
    - When analyzing Talend .item files for migration or documentation
    """
    import json

    def _retrieve_single_component(comp_name: str) -> str:
        """Helper function to retrieve knowledge for a single component."""
        # Auto-detect component type based on naming convention
        if comp_name.startswith("t") and comp_name[0].islower():
            # It's a node (e.g., tMap, tJava, tFileInputDelimited)
            knowledge_base = TALEND_NODES
            component_category = "node"
            # Handle component names with underscores (e.g., tMap_1)
            if "_" in comp_name:
                comp_name = comp_name.split("_")[0]
        else:
            # It's a connection (e.g., FLOW, ITERATE, LOOKUP)
            knowledge_base = TALEND_CONNECTIONS
            component_category = "connection"
            comp_name = comp_name.upper()

        # Retrieve the knowledge
        if comp_name not in knowledge_base:
            # Provide helpful error message with suggestions
            available_components = list(knowledge_base.keys())

            # Try to find similar component names (case-insensitive partial match)
            suggestions = [
                name
                for name in available_components
                if comp_name.lower() in name.lower()
                or name.lower() in comp_name.lower()
            ]

            error_msg = f"Error: '{comp_name}' not found in {component_category} KB.\n"

            if suggestions:
                error_msg += "\nDid you mean one of these?\n"
                error_msg += "\n".join(f"  - {name}" for name in suggestions[:5])
            else:
                error_msg += f"\nAvailable {component_category}s include:\n"
                error_msg += "\n".join(
                    f"  - {name}" for name in available_components[:10]
                )
                if len(available_components) > 10:
                    error_msg += f"\n  ... and {len(available_components) - 10} more"

            return error_msg

        # Return the knowledge text
        knowledge_text = knowledge_base[comp_name]

        # Add a header for context
        header = f"=== Talend {component_category.upper()}: {comp_name} ===\n\n"

        return header + knowledge_text

    # Handle single component name
    if isinstance(component_name, str):
        return _retrieve_single_component(component_name)

    # Handle list of component names
    if isinstance(component_name, list):
        if len(component_name) == 0:
            return "Error: No component names provided. Please provide at least 1."

        results = {}

        for comp_name in component_name:
            if not isinstance(comp_name, str):
                results[str(comp_name)] = (
                    f"Error: Invalid component name type: {type(comp_name).__name__}"
                )
                continue

            knowledge = _retrieve_single_component(comp_name)
            results[comp_name] = knowledge

        # Return as formatted JSON string
        return json.dumps(results, indent=2, ensure_ascii=False)
