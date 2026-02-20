"""
Configuration for lineage sheet mappings by dialect.

This module provides a centralized, extensible configuration for determining
which Excel sheets should be used for lineage analysis for each dialect.
"""

from typing import Dict, List
from dataclasses import dataclass


@dataclass
class LineageSheetConfig:
    """Configuration for a dialect's lineage sheets."""
    
    primary_sheet: str
    """Primary sheet to use for lineage generation"""
    
    secondary_sheets: List[str]
    """Additional sheets that can be used for lineage (optional)"""
    
    format: str = "cross_reference"
    """Default format for the primary sheet (cross_reference or matrix)"""
    
    parser_type: str = "generic"
    """Parser type to use (generic, sql, informatica, etc.)"""


# Centralized configuration for all dialects
LINEAGE_SHEET_MAPPINGS: Dict[str, LineageSheetConfig] = {
    "sql": LineageSheetConfig(
        primary_sheet="RAW_PROGRAM_OBJECT_XREF",
        secondary_sheets=[],  # No fallback - Program-Object Xref has different schema (pivoted)
        format="cross_reference",
        parser_type="sql"
    ),
    "informatica": LineageSheetConfig(
        primary_sheet="RAW_PROGRAM_OBJECT_XREF",
        secondary_sheets=["Subjob Info", "Mappings Objects Xref"],
        format="cross_reference",
        parser_type="informatica"
    ),
    "talend": LineageSheetConfig(
        primary_sheet="Jobs Transformations Xref",
        secondary_sheets=["Subjob Details"],
        format="cross_reference",
        parser_type="generic"
    ),
    "datastage": LineageSheetConfig(
        primary_sheet="Jobs Transformations Xref",
        secondary_sheets=["Job Details"],
        format="cross_reference",
        parser_type="generic"
    ),
}


def get_lineage_sheets(dialect: str) -> List[str]:
    """
    Get all lineage sheet names for a dialect (primary + secondary).
    
    Args:
        dialect: Analyzer dialect (sql, informatica, talend, datastage)
        
    Returns:
        List of sheet names that contain lineage data
    """
    dialect_lower = dialect.lower()
    
    if dialect_lower not in LINEAGE_SHEET_MAPPINGS:
        # Return generic default for unknown dialects
        return ["Lineage", "Cross Reference", "Dependencies"]
    
    config = LINEAGE_SHEET_MAPPINGS[dialect_lower]
    return [config.primary_sheet] + config.secondary_sheets


def get_primary_lineage_sheet(dialect: str) -> str:
    """
    Get the primary lineage sheet name for a dialect.
    
    Args:
        dialect: Analyzer dialect
        
    Returns:
        Primary sheet name for lineage data
    """
    dialect_lower = dialect.lower()
    
    if dialect_lower not in LINEAGE_SHEET_MAPPINGS:
        return "Lineage"  # Generic default
    
    return LINEAGE_SHEET_MAPPINGS[dialect_lower].primary_sheet


def get_lineage_config(dialect: str) -> LineageSheetConfig:
    """
    Get the full lineage configuration for a dialect.
    
    Args:
        dialect: Analyzer dialect
        
    Returns:
        LineageSheetConfig for the dialect
    """
    dialect_lower = dialect.lower()
    
    if dialect_lower not in LINEAGE_SHEET_MAPPINGS:
        # Return generic default
        return LineageSheetConfig(
            primary_sheet="Lineage",
            secondary_sheets=[],
            format="cross_reference",
            parser_type="generic"
        )
    
    return LINEAGE_SHEET_MAPPINGS[dialect_lower]


def find_available_lineage_sheet(dialect: str, available_sheets: List[str]) -> str:
    """
    Find the best available lineage sheet from the analyzer file.
    
    Checks in order:
    1. Primary sheet
    2. Secondary sheets (in order)
    3. Generic fallback
    
    Args:
        dialect: Analyzer dialect
        available_sheets: List of sheet names available in the file
        
    Returns:
        Name of the sheet to use for lineage
        
    Raises:
        ValueError: If no suitable lineage sheet is found
    """
    config = get_lineage_config(dialect)
    available_sheets_lower = {s.lower(): s for s in available_sheets}
    
    # Check primary sheet (case-insensitive)
    if config.primary_sheet.lower() in available_sheets_lower:
        return available_sheets_lower[config.primary_sheet.lower()]
    
    # Check secondary sheets
    for sheet in config.secondary_sheets:
        if sheet.lower() in available_sheets_lower:
            return available_sheets_lower[sheet.lower()]
    
    # Check generic fallbacks
    fallbacks = ["lineage", "cross reference", "dependencies", "xref"]
    for fallback in fallbacks:
        if fallback in available_sheets_lower:
            return available_sheets_lower[fallback]
    
    raise ValueError(
        f"No suitable lineage sheet found for dialect '{dialect}'. "
        f"Expected: {config.primary_sheet} or {config.secondary_sheets}. "
        f"Available: {available_sheets}"
    )


def find_all_lineage_sheets(dialect: str, available_sheets: List[str]) -> List[str]:
    """
    Find ALL available lineage sheets for a dialect (additive approach).
    
    Returns all matching sheets (primary + secondary) without fallback logic.
    This allows processing multiple sheets together for comprehensive lineage.
    
    Args:
        dialect: Analyzer dialect
        available_sheets: List of sheet names available in the file
        
    Returns:
        List of all matching sheet names (primary + all available secondary sheets)
    """
    config = get_lineage_config(dialect)
    found_sheets = []
    available_sheets_lower = {s.lower(): s for s in available_sheets}
    
    # Check primary sheet (case-insensitive)
    if config.primary_sheet.lower() in available_sheets_lower:
        found_sheets.append(available_sheets_lower[config.primary_sheet.lower()])
    
    # Check ALL secondary sheets (additive, case-insensitive)
    for sheet in config.secondary_sheets:
        sheet_lower = sheet.lower()
        if sheet_lower in available_sheets_lower:
            # Avoid duplicates if primary and secondary reference the same sheet
            actual_sheet = available_sheets_lower[sheet_lower]
            if actual_sheet not in found_sheets:
                found_sheets.append(actual_sheet)
    
    return found_sheets

