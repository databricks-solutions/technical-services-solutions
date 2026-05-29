"""
Configuration classes for the application.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class AnalyzerConfig:
    analyzer_file: str
    dialect: str
    format: Optional[str] = "xlsx"
