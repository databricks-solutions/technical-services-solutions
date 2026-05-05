from dataclasses import dataclass
from typing import Any, Dict, Optional

from dataclasses_json import dataclass_json

from migration_accelerator.settings import SUPPORTED_DIALECTS, SUPPORTED_TARGET_SYSTEMS

"""
Registry for all configuration classes.
"""
CONFIG_REGISTRY: Dict[str, Any] = {}


def register_config(cls: Any) -> Any:
    """
    Register a configuration class in the CONFIG_REGISTRY.
    """
    CONFIG_REGISTRY[cls.__name__] = cls
    return cls


@register_config
@dataclass_json
@dataclass
class LLMConfig:
    endpoint_name: str
    temperature: float
    max_tokens: int


@register_config
@dataclass_json
@dataclass
class AnalyzerConfig:
    analyzer_file: str
    dialect: str
    format: Optional[str] = "xlsx"


@register_config
@dataclass_json
@dataclass
class SourceCodeConfig:
    source_file_path: str
    source_dialect: str
    source_dir: Optional[str] = None

    def __post_init__(self):
        """Validate that source_dialect is one of the allowed values."""
        allowed_dialects = list(SUPPORTED_DIALECTS.keys())
        if self.source_dialect not in allowed_dialects:
            raise ValueError(
                f"Invalid source_dialect '{self.source_dialect}'. "
                f"Must be one of: {', '.join(sorted(allowed_dialects))}"
            )


@register_config
@dataclass_json
@dataclass
class TargetCodeConfig:
    target_file_path: str
    target_dialect: str
    target_dir: Optional[str] = None

    def __post_init__(self):
        """Validate that target_dialect is one of the allowed values."""
        allowed_dialects = SUPPORTED_TARGET_SYSTEMS
        if self.target_dialect not in allowed_dialects:
            raise ValueError(
                f"Invalid target_dialect '{self.target_dialect}'. "
                f"Must be one of: {', '.join(sorted(allowed_dialects))}"
            )


@register_config
@dataclass_json
@dataclass
class ParserPromptConfig:
    prompt: str


@register_config
@dataclass_json
@dataclass
class ConverterPromptConfig:
    prompt: str
    skip_node_types: Optional[list[str]] = None
    custom_mappings: Optional[Dict[str, str]] = None
