"""Converter module for ETL migration.

This module provides the Executor framework for orchestrating the entire
migration pipeline from source to target format, as well as dialect-specific
converters like TalendConverter.
"""

from migration_accelerator.experimental.converter.executor import (
    Executor,
    ExecutorConfig,
)
from migration_accelerator.experimental.converter.talend import (
    TalendConverter,
    TalendReAct,
    convert_talend_to_pyspark,
)

__all__ = [
    "Executor",
    "ExecutorConfig",
    "TalendConverter",
    "TalendReAct",
    "convert_talend_to_pyspark",
]
