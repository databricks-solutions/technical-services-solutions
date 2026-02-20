"""
Analyzer Query Service for LLM-based querying of analyzer data.

Handles natural language queries against analyzer files using LLM agents.
"""

from typing import Any, Dict, List, Optional

from migration_accelerator.configs.modules import AnalyzerConfig
from migration_accelerator.core.llms import LLMManager
from migration_accelerator.discovery.analyzer import SourceAnalyzer
from migration_accelerator.utils.logger import get_logger

log = get_logger()


class AnalyzerQueryService:
    """
    Service for querying analyzer data using LLM.
    
    Supports:
    - Single file queries with context
    - Multi-file queries with merged dataframes
    - Dialect-specific sheet selection
    """
    
    def __init__(self, llm_endpoint: str = None):
        """
        Initialize analyzer query service.
        
        Args:
            llm_endpoint: LLM API endpoint URL (optional)
        """
        self.llm_config = {"endpoint": llm_endpoint} if llm_endpoint else None
    
    async def query_single(
        self, file_path: str, dialect: str, question: str
    ) -> Dict[str, Any]:
        """
        Query a single analyzer file using LLM.
        
        Args:
            file_path: Path to analyzer file
            dialect: Analyzer dialect (sql, talend, informatica)
            question: Natural language question
        
        Returns:
            Dictionary with question, answer, and sources
        
        Raises:
            ValueError: If LLM endpoint not configured
        """
        if not self.llm_config:
            raise ValueError("LLM endpoint not configured")
        
        import tempfile
        import os
        from pathlib import Path as PathLib
        from migration_accelerator.app.config import StorageBackend
        from migration_accelerator.app import config
        
        temp_file = None
        try:
            # If using Unity Catalog, download file to temp location first
            local_file_path = file_path
            
            if config.settings.storage_backend == StorageBackend.UNITY_CATALOG:
                from databricks.sdk import WorkspaceClient
                databricks_client = WorkspaceClient()
                
                # Download from UC to temp file
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=PathLib(file_path).suffix)
                temp_file.close()
                
                download_response = databricks_client.files.download(file_path)
                with open(temp_file.name, 'wb') as f:
                    f.write(download_response.contents.read())
                
                local_file_path = temp_file.name
            
            analyzer_config = AnalyzerConfig(analyzer_file=local_file_path, dialect=dialect)
            analyzer = SourceAnalyzer(analyzer_config, llm_config=self.llm_config)
            
            log.info(f"Querying analyzer with: {question}")
            result = analyzer.query(question)
            
            return {
                "question": question,
                "answer": str(result.get("output", result)),
                "sources": [],
            }
        
        except Exception as e:
            log.error(f"Failed to query with LLM: {e}")
            raise
        finally:
            if temp_file:
                try:
                    os.unlink(temp_file.name)
                except Exception:
                    pass
    
    async def query_multiple(
        self, file_data: List[Dict[str, Any]], question: str
    ) -> Dict[str, Any]:
        """
        Query multiple analyzer files using LLM with merged context.
        
        Groups files by dialect, loads relevant sheets, and creates
        a pandas agent with all dataframes for comprehensive querying.
        
        Args:
            file_data: List of dicts with file_path, dialect, filename
            question: Natural language question
        
        Returns:
            Dictionary with question, answer, and sources used
        
        Raises:
            ValueError: If LLM endpoint not configured or no data loaded
        """
        if not self.llm_config:
            raise ValueError("LLM endpoint not configured")
        
        import tempfile
        import os
        from pathlib import Path as PathLib
        from migration_accelerator.app.config import StorageBackend
        from migration_accelerator.app import config
        
        temp_files = []
        try:
            from migration_accelerator.core.agent_toolkits.pandas import (
                create_pandas_dataframe_agent,
            )
            
            # Initialize UC client if needed
            databricks_client = None
            if config.settings.storage_backend == StorageBackend.UNITY_CATALOG:
                from databricks.sdk import WorkspaceClient
                databricks_client = WorkspaceClient()
            
            # Group files by dialect
            dialect_groups = {}
            for file_info in file_data:
                dialect = file_info["dialect"]
                if dialect not in dialect_groups:
                    dialect_groups[dialect] = []
                dialect_groups[dialect].append(file_info)
            
            # Merge dataframes by dialect
            all_dataframes = []
            sources_used = []
            
            for dialect, files in dialect_groups.items():
                for file_info in files:
                    # Download from UC if needed
                    local_file_path = file_info["file_path"]
                    temp_file = None
                    
                    if config.settings.storage_backend == StorageBackend.UNITY_CATALOG:
                        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=PathLib(file_info["file_path"]).suffix)
                        temp_file.close()
                        temp_files.append(temp_file.name)
                        
                        download_response = databricks_client.files.download(file_info["file_path"])
                        with open(temp_file.name, 'wb') as f:
                            f.write(download_response.contents.read())
                        
                        local_file_path = temp_file.name
                    
                    analyzer_config = AnalyzerConfig(
                        analyzer_file=local_file_path, dialect=dialect
                    )
                    analyzer = SourceAnalyzer(
                        analyzer_config, llm_config=self.llm_config
                    )
                    
                    # Get relevant sheets based on dialect
                    sheet_names = self._get_dialect_sheets(dialect)
                    
                    data = analyzer.parse(sheet_names=sheet_names)
                    for sheet_name, df in data.items():
                        all_dataframes.append(df)
                        sources_used.append(f"{file_info['filename']}:{sheet_name}")
            
            if not all_dataframes:
                raise ValueError("No dataframes could be loaded from the files")
            
            # Create agent with all dataframes
            llm_manager = LLMManager(self.llm_config)
            model = llm_manager.get_llm()
            
            agent = create_pandas_dataframe_agent(
                model,
                all_dataframes,
                verbose=True,
                allow_dangerous_code=True,
            )
            
            log.info(
                f"Querying {len(all_dataframes)} dataframes from "
                f"{len(file_data)} files: {question}"
            )
            result = agent.invoke(question)
            
            return {
                "question": question,
                "answer": str(result.get("output", result)),
                "sources": sources_used[:5],  # Limit to top 5 sources
            }
        
        except Exception as e:
            log.error(f"Failed to query multiple analyzers: {e}")
            raise
        finally:
            # Clean up all temp files
            for temp_file_path in temp_files:
                try:
                    os.unlink(temp_file_path)
                except Exception:
                    pass
    
    def _get_dialect_sheets(self, dialect: str) -> List[str]:
        """
        Get relevant sheet names for a dialect.
        
        Args:
            dialect: Analyzer dialect
        
        Returns:
            List of sheet names to load
        """
        if dialect == "sql":
            return [
                "SQL Programs",
                "Referenced Objects",
                "Program-Object Xref",
            ]
        elif dialect == "talend":
            return [
                "Job Details",
                "Jobs Transformations Xref",
            ]
        elif dialect == "informatica":
            return [
                "Mapping Details",
                "Mappings Objects Xref",
            ]
        else:
            return []



