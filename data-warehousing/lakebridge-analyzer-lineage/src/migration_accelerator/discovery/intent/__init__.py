"""Intent generation module for ETL migration.

This module provides functionality for generating intent from parsed source code.
Intent includes ETL flow, sources, targets, transformations, and functional summaries.
"""

from migration_accelerator.discovery.intent.base import (
    BaseIntentBuilder,
    IntentOutput,
)
from migration_accelerator.discovery.intent.builder import (
    IntentBuilder,
    IntentGenerationConfig,
    IntentGenerator,
    discover_and_register_intent_builders,
)
from migration_accelerator.discovery.intent.registry import (
    get_supported_dialects,
    is_registered,
    register_intent_builder,
)
from migration_accelerator.discovery.intent.visualizer import (
    MermaidDiagramGenerator,
    create_mermaid_diagram,
    display_mermaid_in_databricks,
)

__all__ = [
    "BaseIntentBuilder",
    "IntentOutput",
    "IntentBuilder",
    "IntentGenerationConfig",
    "IntentGenerator",
    "register_intent_builder",
    "get_supported_dialects",
    "is_registered",
    "discover_and_register_intent_builders",
    "MermaidDiagramGenerator",
    "create_mermaid_diagram",
    "display_mermaid_in_databricks",
]
