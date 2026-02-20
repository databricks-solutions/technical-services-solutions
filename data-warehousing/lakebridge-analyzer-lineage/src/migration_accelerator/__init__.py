"""
Migration Accelerator - Non-functional migration utilities.

This package provides utilities for:
- Discovery: Database and application discovery
- Profiling: Performance and resource profiling
- Lineage: Data and process lineage tracking
- Impact Assessment: Migration impact analysis
- Quality Assurance: Data quality validation
- CodeOps: Code migration operations
"""

from migration_accelerator import cli
from migration_accelerator.settings import PERSIST_LOGS
from migration_accelerator.utils.logger import setup_logger
from migration_accelerator.version import _get_version

setup_logger(persist=PERSIST_LOGS)


__version__ = _get_version()
__author__ = "Migration Accelerator Team"
__email__ = "ps-labs-tooling-gdc@databricks.com"
__description__ = "Non-functional migration accelerator utilities"


__all__ = [
    "cli",
    "__version__",
]
