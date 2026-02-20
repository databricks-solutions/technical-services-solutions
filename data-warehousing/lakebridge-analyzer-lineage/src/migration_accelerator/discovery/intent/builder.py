"""Intent builder factory and utilities.

This module provides factory methods for creating dialect-specific
intent builders and managing the intent generation process.
"""

from pathlib import Path
from typing import Optional

from migration_accelerator.configs.modules import LLMConfig, SourceCodeConfig
from migration_accelerator.discovery.intent.base import BaseIntentBuilder, IntentOutput
from migration_accelerator.discovery.intent.registry import (
    get_intent_builder_class,
    get_supported_dialects,
    is_registered,
)
from migration_accelerator.utils.logger import get_logger

log = get_logger()


def generate_mermaid_diagram(
    intent: IntentOutput,
    orientation: str = "TD",
    use_ai: bool = False,
    llm_config: Optional[LLMConfig] = None,
) -> str:
    """Generate a Mermaid diagram from IntentOutput.

    Args:
        intent: IntentOutput to visualize
        orientation: Flow direction (TD, LR, RL, BT)
        use_ai: Whether to use AI for enhanced diagram generation
        llm_config: LLM configuration for AI-powered generation

    Returns:
        str: Mermaid diagram syntax

    Example:
        >>> from migration_accelerator.discovery.intent import IntentBuilder,
            generate_mermaid_diagram
        >>> builder = IntentBuilder.create_builder(source_config)
        >>> intent = builder.generate_intent()
        >>> mermaid = generate_mermaid_diagram(intent,
            use_ai=True, llm_config=llm_config)
        >>> print(mermaid)
    """
    from migration_accelerator.discovery.intent.visualizer import (
        create_mermaid_diagram,
    )

    return create_mermaid_diagram(intent, orientation, use_ai, llm_config)


def discover_and_register_intent_builders():
    """Discover and register all available intent builders.

    This function imports all intent builder modules to trigger their
    registration via the @register_intent_builder decorator.
    """
    # Import dialect-specific builders here as they are implemented
    # For now, this is a placeholder

    try:
        from migration_accelerator.discovery.intent.talend import (  # noqa: F401
            TalendIntentBuilder,
        )

        log.info("Imported TalendIntentBuilder")
    except ImportError as e:
        log.warning(f"Could not import TalendIntentBuilder: {e}")

    # Add more builders as they are implemented:
    # try:
    #     from migration_accelerator.discovery.intent.informatica import (  # noqa: F401
    #         InformaticaIntentBuilder,
    #     )
    #     log.info("Imported InformaticaIntentBuilder")
    # except ImportError as e:
    #     log.warning(f"Could not import InformaticaIntentBuilder: {e}")

    dialects = get_supported_dialects()
    log.info(f"Discovered and registered {len(dialects)} intent builders: {dialects}")

    return len(dialects)


class IntentBuilder:
    """Factory class for creating dialect-specific intent builders."""

    @staticmethod
    def create_builder(
        source_config: SourceCodeConfig,
        parsed_content_path: Optional[Path] = None,
        use_ai: bool = False,
        llm_config: Optional[LLMConfig] = None,
        user_prompt: Optional[str] = None,
    ) -> BaseIntentBuilder:
        """Create an intent builder for the specified dialect.

        Args:
            source_config: Source code configuration
            parsed_content_path: Path to parsed content from previous step
            use_ai: Whether to use AI for intent generation
            llm_config: LLM configuration for AI-powered generation
            user_prompt: Optional user prompt for customization

        Returns:
            BaseIntentBuilder: Dialect-specific intent builder instance

        Raises:
            ValueError: If dialect is not supported
        """
        dialect = source_config.source_dialect.lower()

        # Discover and register all builders
        discover_and_register_intent_builders()

        log.debug(f"Creating intent builder for dialect: {dialect}")

        if not is_registered(dialect):
            supported = get_supported_dialects()
            raise ValueError(
                f"Unsupported dialect: {dialect}. " f"Supported dialects: {supported}"
            )

        builder_class = get_intent_builder_class(dialect)
        log.info(
            f"Creating {dialect} intent builder for: {source_config.source_file_path}"
        )

        return builder_class(
            source_config=source_config,
            parsed_content_path=parsed_content_path,
            use_ai=use_ai,
            llm_config=llm_config,
            user_prompt=user_prompt,
        )

    @staticmethod
    def get_supported_dialects() -> list[str]:
        """Get list of supported dialects.

        Returns:
            List[str]: List of supported dialect names
        """
        discover_and_register_intent_builders()
        return get_supported_dialects()

    @staticmethod
    def is_dialect_supported(dialect: str) -> bool:
        """Check if a dialect is supported.

        Args:
            dialect: Dialect name to check

        Returns:
            bool: True if dialect is supported, False otherwise
        """
        discover_and_register_intent_builders()
        return is_registered(dialect)


class IntentGenerationConfig:
    """Configuration for intent generation process."""

    def __init__(
        self,
        source_config: SourceCodeConfig,
        parsed_content_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
        use_ai: bool = False,
        llm_config: Optional[LLMConfig] = None,
        user_prompt: Optional[str] = None,
        include_lineage: bool = True,
        include_metadata: bool = True,
    ):
        """Initialize intent generation configuration.

        Args:
            source_config: Source code configuration
            parsed_content_dir: Directory containing parsed content
            output_dir: Directory for intent output
            use_ai: Whether to use AI for generation
            llm_config: LLM configuration
            user_prompt: Custom user prompt
            include_lineage: Include data lineage in intent
            include_metadata: Include metadata in intent
        """
        self.source_config = source_config
        self.parsed_content_dir = parsed_content_dir
        self.output_dir = output_dir
        self.use_ai = use_ai
        self.llm_config = llm_config
        self.user_prompt = user_prompt
        self.include_lineage = include_lineage
        self.include_metadata = include_metadata


class IntentGenerator:
    """High-level intent generator that orchestrates the process."""

    def __init__(self, config: IntentGenerationConfig):
        """Initialize intent generator.

        Args:
            config: Intent generation configuration
        """
        self.config = config
        self.builder: Optional[BaseIntentBuilder] = None
        log.info("Initialized IntentGenerator")

    def generate(self) -> IntentOutput:
        """Generate intent for the configured source.

        Returns:
            IntentOutput: Generated intent

        Raises:
            ValueError: If configuration is invalid
        """
        log.info("Starting intent generation process")

        # Determine parsed content path
        parsed_content_path = self._find_parsed_content()

        # Create builder
        self.builder = IntentBuilder.create_builder(
            source_config=self.config.source_config,
            parsed_content_path=parsed_content_path,
            use_ai=self.config.use_ai,
            llm_config=self.config.llm_config,
            user_prompt=self.config.user_prompt,
        )

        # Generate intent
        intent = self.builder.generate_intent()

        log.info("Intent generation completed successfully")
        return intent

    def _find_parsed_content(self) -> Optional[Path]:
        """Find the parsed content file for the source.

        Returns:
            Optional[Path]: Path to parsed content, or None if not found
        """
        if not self.config.parsed_content_dir:
            log.warning("No parsed content directory specified")
            return None

        source_file = Path(self.config.source_config.source_file_path)

        # Look for parsed content file
        # Convention: <source_filename>_parsed.json
        parsed_filename = f"{source_file.stem}_parsed.json"
        parsed_path = self.config.parsed_content_dir / parsed_filename

        if parsed_path.exists():
            log.info(f"Found parsed content at: {parsed_path}")
            return parsed_path
        else:
            log.warning(f"Parsed content not found at: {parsed_path}")
            return None

    def save_intent(
        self, intent: IntentOutput, output_path: Optional[Path] = None
    ) -> Path:
        """Save generated intent to file.

        Args:
            intent: Generated intent
            output_path: Optional custom output path

        Returns:
            Path: Path where intent was saved
        """
        from migration_accelerator.utils.files import write_json

        if output_path:
            save_path = output_path
        elif self.config.output_dir:
            source_file = Path(self.config.source_config.source_file_path)
            filename = f"{source_file.stem}_intent.json"
            save_path = self.config.output_dir / filename
        else:
            raise ValueError("No output path specified")

        save_path.parent.mkdir(parents=True, exist_ok=True)

        write_json(intent.to_dict(), save_path)
        log.info(f"Saved intent to: {save_path}")

        return save_path


__all__ = [
    "IntentBuilder",
    "IntentGenerationConfig",
    "IntentGenerator",
    "discover_and_register_intent_builders",
    "generate_mermaid_diagram",
]
