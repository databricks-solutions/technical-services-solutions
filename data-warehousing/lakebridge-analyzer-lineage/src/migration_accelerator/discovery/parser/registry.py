"""Parser registry module.

This module contains the parser registry and registration functionality,
separated from the main factory to avoid circular imports.
"""

from typing import Dict, Type

from migration_accelerator.discovery.parser.base import BaseSourceCodeParser
from migration_accelerator.utils.logger import get_logger

log = get_logger()

# Registry to store parser classes
PARSER_REGISTRY: Dict[str, Type[BaseSourceCodeParser]] = {}


def register_parser(dialect: str):
    """Decorator to register a parser for a specific dialect.

    Args:
        dialect: The dialect name (e.g., 'talend', 'informatica', 'synapse')

    Returns:
        Decorator function
    """

    def decorator(parser_class: Type[BaseSourceCodeParser]):
        PARSER_REGISTRY[dialect.lower()] = parser_class
        log.info(f"Registered parser for dialect: {dialect}")
        return parser_class

    return decorator


def get_registry() -> Dict[str, Type[BaseSourceCodeParser]]:
    """Get the current parser registry.

    Returns:
        Dict[str, Type[BaseSourceCodeParser]]: The parser registry
    """
    return PARSER_REGISTRY.copy()


def is_registered(dialect: str) -> bool:
    """Check if a dialect is registered.

    Args:
        dialect: Dialect to check

    Returns:
        bool: True if registered, False otherwise
    """
    return dialect.lower() in PARSER_REGISTRY


def get_supported_dialects() -> list[str]:
    """Get list of supported dialects.

    Returns:
        List[str]: List of supported dialect names
    """
    return list(PARSER_REGISTRY.keys())
