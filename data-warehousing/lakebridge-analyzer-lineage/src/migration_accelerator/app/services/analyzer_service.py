"""
Analyzer service for processing uploaded analyzer files.
"""

from typing import Any, Dict, List, Optional

from migration_accelerator.app.constants import Dialect
from migration_accelerator.app.factories.analyzer_factory import AnalyzerFactory
from migration_accelerator.configs.modules import AnalyzerConfig, LLMConfig
from migration_accelerator.utils.logger import get_logger

log = get_logger()


class AnalyzerService:
    """Service for analyzer operations."""

    def __init__(self, llm_endpoint: Optional[str] = None):
        """
        Initialize analyzer service.

        Args:
            llm_endpoint: LLM endpoint name (optional)
        """
        self.llm_endpoint = llm_endpoint
        self.llm_config = None
        if llm_endpoint:
            from migration_accelerator.configs.modules import LLMConfig
            from migration_accelerator.app.config import settings
            self.llm_config = LLMConfig(
                endpoint_name=llm_endpoint,
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_max_tokens
            )
        self.analyzer_factory = AnalyzerFactory(llm_config=self.llm_config)

        if llm_endpoint:
            self.llm_config = LLMConfig(
                endpoint_name=llm_endpoint, temperature=0.1, max_tokens=2000
            )

    async def analyze_file(
        self, file_path: str, dialect: str, user_id: str
    ) -> Dict[str, Any]:
        """
        Analyze uploaded analyzer file.

        Args:
            file_path: Path to analyzer file
            dialect: Analyzer dialect (talend, informatica, sql)
            user_id: User identifier

        Returns:
            Analysis results dictionary
        """
        import tempfile
        import os
        from pathlib import Path
        from migration_accelerator.app.config import StorageBackend
        from migration_accelerator.app import config
        
        temp_file = None
        try:
            # If using Unity Catalog, download file to temp location first
            local_file_path = file_path
            
            if config.settings.storage_backend == StorageBackend.UNITY_CATALOG:
                # Initialize Databricks client with service principal
                from databricks.sdk import WorkspaceClient
                
                databricks_client = WorkspaceClient()
                log.info("Using service principal for UC file download")
                
                # Download from UC to temp file
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=Path(file_path).suffix)
                temp_file.close()
                
                download_response = databricks_client.files.download(file_path)
                with open(temp_file.name, 'wb') as f:
                    f.write(download_response.contents.read())
                
                local_file_path = temp_file.name
                log.info(f"Downloaded UC file to temp location for analysis: {local_file_path}")
            
            # Convert string dialect to Dialect enum
            try:
                dialect_enum = Dialect(dialect.lower())
            except ValueError:
                dialect_enum = Dialect.TALEND  # Default fallback
            
            # Use factory to create analyzer with local file path
            analyzer = self.analyzer_factory.create(local_file_path, dialect_enum)

            # Parse file
            log.info(f"Parsing analyzer file: {file_path}")
            data = analyzer.parse()

            # Extract available sheets
            sheets = list(data.keys())
            log.info(f"Found {len(sheets)} sheets: {sheets}")

            # Get metrics if Summary sheet exists
            metrics = None
            complexity = None

            if "Summary" in sheets:
                try:
                    metrics = analyzer.get_key_metrics("Summary")
                    complexity = analyzer.get_job_complexity_breakdown("Summary")
                except Exception as e:
                    log.warning(f"Could not extract metrics from Summary: {e}")

            return {
                "sheets": sheets,
                "metrics": metrics,
                "complexity": complexity,
                "dialect": dialect,
                "user_id": user_id,
                "lineages": [],  # Lineages will be generated separately
            }

        except Exception as e:
            log.error(f"Failed to analyze file {file_path}: {e}")
            raise
        finally:
            # Clean up temp file if created
            if temp_file and os.path.exists(temp_file.name):
                os.unlink(temp_file.name)
                log.debug(f"Cleaned up temp file: {temp_file.name}")

    async def get_metrics(
        self, file_path: str, dialect: str, sheet_name: str = "Summary"
    ) -> Dict[str, Any]:
        """
        Get metrics from analyzer file.

        Args:
            file_path: Path to analyzer file
            dialect: Analyzer dialect
            sheet_name: Sheet name to extract metrics from

        Returns:
            Metrics dictionary
        """
        import tempfile
        import os
        from pathlib import Path
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
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=Path(file_path).suffix)
                temp_file.close()
                
                download_response = databricks_client.files.download(file_path)
                with open(temp_file.name, 'wb') as f:
                    f.write(download_response.contents.read())
                
                local_file_path = temp_file.name
            
            # Convert string dialect to Dialect enum
            try:
                dialect_enum = Dialect(dialect.lower())
            except ValueError:
                dialect_enum = Dialect.TALEND
            
            analyzer = self.analyzer_factory.create(local_file_path, dialect_enum)
            metrics = analyzer.get_key_metrics(sheet_name)
            return metrics

        except Exception as e:
            log.error(f"Failed to get metrics: {e}")
            raise
        finally:
            # Clean up temp file
            if temp_file:
                try:
                    os.unlink(temp_file.name)
                except Exception:
                    pass

    async def get_complexity(
        self, file_path: str, dialect: str, sheet_name: str = "Summary"
    ) -> Dict[str, int]:
        """
        Get complexity breakdown from analyzer file.

        Args:
            file_path: Path to analyzer file
            dialect: Analyzer dialect
            sheet_name: Sheet name to extract complexity from

        Returns:
            Complexity dictionary
        """
        import tempfile
        import os
        from pathlib import Path
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
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=Path(file_path).suffix)
                temp_file.close()
                
                download_response = databricks_client.files.download(file_path)
                with open(temp_file.name, 'wb') as f:
                    f.write(download_response.contents.read())
                
                local_file_path = temp_file.name
            
            # Convert string dialect to Dialect enum
            try:
                dialect_enum = Dialect(dialect.lower())
            except ValueError:
                dialect_enum = Dialect.TALEND
            
            analyzer = self.analyzer_factory.create(local_file_path, dialect_enum)

            if dialect == "sql":
                complexity = analyzer.get_sql_complexity_breakdown(sheet_name)
            else:
                complexity = analyzer.get_job_complexity_breakdown(sheet_name)

            return complexity

        except Exception as e:
            log.error(f"Failed to get complexity: {e}")
            raise
        finally:
            # Clean up temp file
            if temp_file:
                try:
                    os.unlink(temp_file.name)
                except Exception:
                    pass

    async def get_sheet_data(
        self, file_path: str, dialect: str, sheet_name: str
    ) -> Dict[str, Any]:
        """
        Get data from a specific sheet.

        Args:
            file_path: Path to analyzer file
            dialect: Analyzer dialect
            sheet_name: Sheet name

        Returns:
            Sheet data as dictionary
        """
        try:
            # Convert string dialect to Dialect enum
            try:
                dialect_enum = Dialect(dialect.lower())
            except ValueError:
                dialect_enum = Dialect.TALEND
            
            analyzer = self.analyzer_factory.create(file_path, dialect_enum)
            df = analyzer.get_sheet(sheet_name)
            return df.to_dict(orient="records")

        except Exception as e:
            log.error(f"Failed to get sheet data: {e}")
            raise

    def get_lineage_sheet_name(self, dialect: str, available_sheets: List[str] = None) -> str:
        """
        Get the default lineage sheet name for a dialect.

        Args:
            dialect: Analyzer dialect
            available_sheets: List of available sheets in the file (optional)

        Returns:
            Sheet name containing lineage data
        """
        from migration_accelerator.app.services.lineage_config import (
            get_primary_lineage_sheet,
            find_available_lineage_sheet
        )
        
        # If we have available sheets, find the best match
        if available_sheets:
            try:
                return find_available_lineage_sheet(dialect, available_sheets)
            except ValueError:
                # Fallback to primary if no match found
                pass
        
        # Return primary sheet for the dialect
        return get_primary_lineage_sheet(dialect)


