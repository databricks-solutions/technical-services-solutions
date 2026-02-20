"""
Dialect detection utility for analyzer files.
"""

import io
from pathlib import Path
from typing import Optional

import pandas as pd

from migration_accelerator.utils.logger import get_logger

log = get_logger()


def detect_dialect_from_excel(file_path: str) -> Optional[str]:
    """
    Detect analyzer dialect by checking Summary sheet column F.
    
    Handles both local files and Unity Catalog files.
    
    Args:
        file_path: Path to Excel analyzer file (local or UC path)
        
    Returns:
        Detected dialect ('sql', 'talend', 'informatica', 'datastage') or None
    """
    try:
        log.info(f"Attempting to detect dialect from: {file_path}")
        
        # Check if this is a Unity Catalog path
        if file_path.startswith("/Volumes/"):
            # Unity Catalog path - read directly using Databricks SDK
            from databricks.sdk import WorkspaceClient
            
            log.info(f"Reading UC file for dialect detection: {file_path}")
            databricks_client = WorkspaceClient()
            
            # Download file content to memory
            download_response = databricks_client.files.download(file_path)
            file_content = download_response.contents.read()
            
            # Read Excel from memory buffer
            with pd.ExcelFile(io.BytesIO(file_content)) as xls:
                if "Summary" not in xls.sheet_names:
                    log.warning("No Summary sheet found in file")
                    return None
                df = pd.read_excel(xls, sheet_name="Summary")
            
            log.info(f"Successfully read UC file from memory")
        else:
            # Local file - use standard file reading
            from migration_accelerator.utils.files import read_excel
            data = read_excel(file_path, sheet_names=["Summary"])
            
            if "Summary" not in data:
                log.warning("No Summary sheet found in file")
                return None
            df = data["Summary"]
        
        # Now we have the Summary sheet DataFrame - continue with detection
        
        # Check if column F exists (6th column, index 5)
        if len(df.columns) < 6:
            log.warning(f"Summary sheet has fewer than 6 columns: {len(df.columns)}")
            return None
        
        # Get column F (index 5)
        column_f = df.iloc[:, 5]
        
        # Convert to string and check for keywords
        column_f_str = column_f.astype(str).str.upper()
        
        # Check for dialect keywords (case-insensitive)
        dialect_keywords = {
            "sql": ["SQL", "SQLSERVER", "SQL_SERVER", "T-SQL", "TSQL"],
            "talend": ["TALEND", "TOS", "TALEND_OPEN_STUDIO"],
            "informatica": ["INFA", "INFORMATICA", "POWERCENTER"],
            "datastage": ["DATASTAGE", "DATA_STAGE", "IBM_DATASTAGE"],
        }
        
        for dialect, keywords in dialect_keywords.items():
            for keyword in keywords:
                if column_f_str.str.contains(keyword, case=False, na=False).any():
                    log.info(f"Detected dialect: {dialect} (keyword: {keyword})")
                    return dialect
        
        log.warning("No dialect keyword found in column F of Summary sheet")
        return None
        
    except KeyError as e:
        log.error(f"Sheet not found while detecting dialect: {e}")
        return None
    except Exception as e:
        log.error(f"Error detecting dialect: {e}", exc_info=True)
        return None


async def detect_dialect_from_excel_async(file_path: str) -> Optional[str]:
    """
    Async wrapper for dialect detection.
    
    Args:
        file_path: Path to Excel analyzer file
        
    Returns:
        Detected dialect or None
    """
    return detect_dialect_from_excel(file_path)

