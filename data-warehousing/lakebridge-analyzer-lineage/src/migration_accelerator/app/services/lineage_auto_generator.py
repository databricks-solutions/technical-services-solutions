"""
Lineage Auto Generator Service for automatic lineage creation.

Generates lineages from analyzer files without AI enhancement.
"""

from typing import Any, Dict, List

from migration_accelerator.app.config import get_storage_path
from migration_accelerator.app.services.lineage_service import LineageService
from migration_accelerator.utils.logger import get_logger

log = get_logger()


class LineageAutoGenerator:
    """
    Service for automatically generating lineages from analyzer files.
    
    Processes all applicable lineage sheets for a dialect and generates
    cross-reference lineages without AI enhancement.
    """
    
    async def auto_generate_lineages(
        self,
        file_path: str,
        dialect: str,
        sheets: List[str],
        user_id: str,
        analyzer_id: str
    ) -> List[Dict[str, Any]]:
        """
        Auto-generate lineages for all applicable formats (without AI).
        
        Discovers lineage sheets based on dialect and generates
        cross-reference lineages for each applicable sheet combination.
        
        Args:
            file_path: Path to analyzer file
            dialect: Analyzer dialect (sql, talend, informatica)
            sheets: Available sheets in the analyzer file
            user_id: User identifier
            analyzer_id: Analyzer/file identifier
        
        Returns:
            List of generated lineage metadata dictionaries with:
            - lineage_id: Generated lineage identifier
            - format: Lineage format (cross_reference)
            - sheet_name: Combined sheet names
            - sheet_names: List of all sheets used
            - nodes_count: Number of nodes
            - edges_count: Number of edges
            - created_at: Creation timestamp
            - auto_generated: True flag
        """
        lineages = []
        
        try:
            # Get ALL lineage sheets for this dialect (additive, no fallback)
            from migration_accelerator.app.services.lineage_config import (
                find_all_lineage_sheets
            )
            
            lineage_sheets = find_all_lineage_sheets(dialect, sheets)
            
            if not lineage_sheets:
                log.info(f"No lineage sheets found for {dialect}")
                return lineages
            
            log.info(
                f"Found {len(lineage_sheets)} lineage sheet(s) for "
                f"{dialect}: {lineage_sheets}"
            )
            
            # Initialize lineage service
            lineage_service = LineageService(
                llm_endpoint=None,  # No AI for auto-generation
                storage_path=get_storage_path()
            )
            
            # Determine applicable formats based on dialect
            formats_to_generate = self._get_formats_for_dialect(dialect)
            
            # Generate each format (processing all sheets together)
            for format_type in formats_to_generate:
                try:
                    log.info(
                        f"Auto-generating {format_type} lineage for {dialect} "
                        f"from {len(lineage_sheets)} sheet(s)"
                    )
                    
                    result = await lineage_service.create_lineage_from_analyzer(
                        file_path=file_path,
                        dialect=dialect,
                        sheet_name=lineage_sheets,  # Pass all sheets
                        user_id=user_id,
                        format=format_type,
                        enhance_with_llm=False,
                    )
                    
                    lineages.append({
                        "lineage_id": result["lineage_id"],
                        "format": format_type,
                        "sheet_name": (
                            ", ".join(lineage_sheets)
                            if len(lineage_sheets) > 1
                            else lineage_sheets[0]
                        ),
                        "sheet_names": lineage_sheets,  # Track all sheets
                        "nodes_count": result["nodes_count"],
                        "edges_count": result["edges_count"],
                        "created_at": result["created_at"],
                        "auto_generated": True,
                    })
                    
                    log.info(
                        f"Generated {format_type} lineage: {result['lineage_id']} "
                        f"({result['nodes_count']} nodes, {result['edges_count']} edges)"
                    )
                
                except Exception as e:
                    log.warning(f"Failed to auto-generate {format_type} lineage: {e}")
                    continue
            
            log.info(f"Auto-generated {len(lineages)} lineage(s) for {dialect}")
        
        except Exception as e:
            log.error(f"Error in auto-lineage generation: {e}")
        
        return lineages
    
    def _get_formats_for_dialect(self, dialect: str) -> List[str]:
        """
        Get applicable lineage formats for a dialect.
        
        Args:
            dialect: Analyzer dialect
        
        Returns:
            List of format types to generate
        """
        if dialect == "sql":
            return ["cross_reference"]
        elif dialect == "talend":
            return ["cross_reference"]
        elif dialect == "informatica":
            return ["cross_reference"]
        else:
            return []




