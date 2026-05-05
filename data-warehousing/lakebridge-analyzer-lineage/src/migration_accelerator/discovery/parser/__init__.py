"""Source code parser factory and registry.

This module implements a factory pattern for creating dialect-specific
source code parsers.
"""

from typing import Optional

from migration_accelerator.configs.modules import (
    LLMConfig,
    ParserPromptConfig,
    SourceCodeConfig,
)
from migration_accelerator.discovery.parser.base import BaseSourceCodeParser
from migration_accelerator.discovery.parser.registry import (
    PARSER_REGISTRY,
    get_supported_dialects,
    is_registered,
)
from migration_accelerator.utils.logger import get_logger

log = get_logger()


# Parsers are automatically registered when their modules are imported
# Use discover_and_register_parsers() to explicitly register all parsers
def discover_and_register_parsers():
    """Discover and register all available parsers.

    This function safely imports all parser modules to trigger their registration.
    Call this if you want to ensure all parsers are available.
    """
    try:
        from migration_accelerator.discovery.parser.talend import (  # noqa: F401
            TalendParser,
        )

        log.info("Imported TalendParser")
    except ImportError as e:
        log.warning(f"Could not import TalendParser: {e}")

    # Add more parsers here as you create them:
    # try:
    #     from migration_accelerator.discovery.parser.informatica import (  # noqa: F401
    #         InformaticaParser,
    #     )
    #     log.info("Imported InformaticaParser")
    # except ImportError as e:
    #     log.warning(f"Could not import InformaticaParser: {e}")

    # try:
    #     from migration_accelerator.discovery.parser.sql import SQLParser  # noqa: F401
    #     log.info("Imported SQLParser")
    # except ImportError as e:
    #     log.warning(f"Could not import SQLParser: {e}")

    dialects = get_supported_dialects()
    log.info(f"Discovered and registered {len(dialects)} parsers: {dialects}")

    return len(dialects)


class SourceCodeParser:
    """Factory class for creating source code parsers."""

    @staticmethod
    def create_parser(
        config: SourceCodeConfig,
        user_prompt: Optional[ParserPromptConfig] = None,
        use_ai: Optional[bool] = False,
        llm_config: Optional[LLMConfig] = None,
    ) -> BaseSourceCodeParser:
        """Create a parser instance for the specified dialect.

        Args:
            config: SourceCodeConfig containing dialect and file information
            user_prompt: Optional[ParserPromptConfig] containing user prompt
            use_ai: Optional[bool] containing use_ai flag
            llm_config: Optional[LLMConfig] containing LLM configuration
        Returns:
            BaseSourceCodeParser: Instance of the appropriate parser

        Raises:
            ValueError: If the dialect is not supported
        """
        dialect = config.source_dialect.lower()

        discover_and_register_parsers()

        log.debug(f"PARSER_REGISTRY: {PARSER_REGISTRY}")

        if dialect not in PARSER_REGISTRY:
            supported_dialects = list(PARSER_REGISTRY.keys())
            raise ValueError(
                f"Unsupported dialect: {dialect}. "
                f"Supported dialects: {supported_dialects}"
            )

        parser_class = PARSER_REGISTRY[dialect]
        log.info(f"Creating {dialect} parser for file: {config.source_file_path}")

        return parser_class(config, user_prompt, use_ai, llm_config)

    @staticmethod
    def get_supported_dialects() -> list[str]:
        """Get list of supported dialects.

        Returns:
            List[str]: List of supported dialect names
        """
        discover_and_register_parsers()
        return get_supported_dialects()

    @staticmethod
    def is_dialect_supported(dialect: str) -> bool:
        """Check if a dialect is supported.

        Args:
            dialect: Dialect name to check

        Returns:
            bool: True if dialect is supported, False otherwise
        """
        discover_and_register_parsers()
        return is_registered(dialect)


__all__ = ["BaseSourceCodeParser", "SourceCodeParser", "discover_and_register_parsers"]
