"""
Constants and enums for the application.

Centralizes magic strings into type-safe enums.
"""

from enum import Enum


class Dialect(str, Enum):
    """Analyzer dialect types."""
    SQL = "sql"
    TALEND = "talend"
    INFORMATICA = "informatica"
    DATASTAGE = "datastage"


class LineageFormat(str, Enum):
    """Lineage data format types."""
    CROSS_REFERENCE = "cross_reference"
    MATRIX = "matrix"


class ExportFormat(str, Enum):
    """Export format types."""
    JSON = "json"
    CSV = "csv"
    GRAPHML = "graphml"
    GEXF = "gexf"


class NodeType(str, Enum):
    """Node types in lineage graphs."""
    FILE = "FILE"
    TABLE_OR_VIEW = "TABLE_OR_VIEW"


class Relationship(str, Enum):
    """Edge relationship types in lineage graphs."""
    READS_FROM = "READS_FROM"
    WRITES_TO = "WRITES_TO"
    CREATES = "CREATES"
    CREATES_INDEX = "CREATES_INDEX"
    DELETES_FROM = "DELETES_FROM"
    DROPS = "DROPS"
    DEPENDS_ON = "DEPENDS_ON"
    DEPENDS_ON_FILE = "DEPENDS_ON_FILE"




