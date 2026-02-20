"""Registry for intent builders.

This module provides a registry pattern for registering and discovering
dialect-specific intent builders.
"""

from typing import Any, Dict, Type

from migration_accelerator.utils.logger import get_logger

log = get_logger()

# Global registry for intent builders
INTENT_BUILDER_REGISTRY: Dict[str, Type[Any]] = {}


def register_intent_builder(dialect: str):
    """Decorator to register an intent builder for a specific dialect.

    Args:
        dialect: The dialect name (e.g., 'talend', 'informatica')

    Returns:
        Decorator function

    Example:
        @register_intent_builder('talend')
        class TalendIntentBuilder(BaseIntentBuilder):
            pass
    """

    def decorator(cls: Type[Any]) -> Type[Any]:
        dialect_lower = dialect.lower()
        log.debug(f"Registering intent builder for dialect: {dialect_lower}")
        INTENT_BUILDER_REGISTRY[dialect_lower] = cls
        return cls

    return decorator


def get_intent_builder_class(dialect: str) -> Type[Any]:
    """Get the intent builder class for a specific dialect.

    Args:
        dialect: The dialect name

    Returns:
        Type[Any]: The intent builder class

    Raises:
        ValueError: If dialect is not registered
    """
    dialect_lower = dialect.lower()

    if dialect_lower not in INTENT_BUILDER_REGISTRY:
        available = list(INTENT_BUILDER_REGISTRY.keys())
        raise ValueError(
            f"No intent builder registered for dialect: {dialect}. "
            f"Available dialects: {available}"
        )

    return INTENT_BUILDER_REGISTRY[dialect_lower]


def get_supported_dialects() -> list[str]:
    """Get list of supported dialects.

    Returns:
        List[str]: List of registered dialect names
    """
    return sorted(list(INTENT_BUILDER_REGISTRY.keys()))


def is_registered(dialect: str) -> bool:
    """Check if a dialect has a registered intent builder.

    Args:
        dialect: The dialect name

    Returns:
        bool: True if registered, False otherwise
    """
    return dialect.lower() in INTENT_BUILDER_REGISTRY
