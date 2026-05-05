"""
Analyzer service for processing uploaded analyzer files.
"""

import asyncio
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
        
        def _analyze_sync():
            """Run all blocking I/O + CPU work in a thread."""
            nonlocal file_path
            _temp_file = None
            try:
                local_file_path = file_path

                is_uc_path = (
                    config.settings.storage_backend == StorageBackend.UNITY_CATALOG
                    and file_path.startswith("/Volumes/")
                )
                if is_uc_path:
                    from databricks.sdk import WorkspaceClient
                    databricks_client = WorkspaceClient()

                    _temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=Path(file_path).suffix)
                    _temp_file.close()

                    download_response = databricks_client.files.download(file_path)
                    with open(_temp_file.name, 'wb') as f:
                        f.write(download_response.contents.read())

                    local_file_path = _temp_file.name
                    log.info(f"Downloaded UC file to temp location for analysis: {local_file_path}")

                try:
                    dialect_enum = Dialect(dialect.lower())
                except ValueError:
                    dialect_enum = Dialect.TALEND

                analyzer = self.analyzer_factory.create(local_file_path, dialect_enum)

                log.info(f"Parsing analyzer file: {file_path}")
                data = analyzer.parse()

                sheets = list(data.keys())
                log.info(f"Found {len(sheets)} sheets: {sheets}")

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
                    "lineages": [],
                }

            except Exception as e:
                log.error(f"Failed to analyze file {file_path}: {e}")
                raise
            finally:
                if _temp_file and os.path.exists(_temp_file.name):
                    os.unlink(_temp_file.name)

        return await asyncio.to_thread(_analyze_sync)

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
        
        def _get_metrics_sync():
            _temp_file = None
            try:
                local_file_path = file_path

                if config.settings.storage_backend == StorageBackend.UNITY_CATALOG:
                    from databricks.sdk import WorkspaceClient
                    databricks_client = WorkspaceClient()

                    _temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=Path(file_path).suffix)
                    _temp_file.close()

                    download_response = databricks_client.files.download(file_path)
                    with open(_temp_file.name, 'wb') as f:
                        f.write(download_response.contents.read())

                    local_file_path = _temp_file.name

                try:
                    dialect_enum = Dialect(dialect.lower())
                except ValueError:
                    dialect_enum = Dialect.TALEND

                analyzer = self.analyzer_factory.create(local_file_path, dialect_enum)
                return analyzer.get_key_metrics(sheet_name)

            except Exception as e:
                log.error(f"Failed to get metrics: {e}")
                raise
            finally:
                if _temp_file:
                    try:
                        os.unlink(_temp_file.name)
                    except Exception:
                        pass

        return await asyncio.to_thread(_get_metrics_sync)

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
        
        def _get_complexity_sync():
            _temp_file = None
            try:
                local_file_path = file_path

                if config.settings.storage_backend == StorageBackend.UNITY_CATALOG:
                    from databricks.sdk import WorkspaceClient
                    databricks_client = WorkspaceClient()

                    _temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=Path(file_path).suffix)
                    _temp_file.close()

                    download_response = databricks_client.files.download(file_path)
                    with open(_temp_file.name, 'wb') as f:
                        f.write(download_response.contents.read())

                    local_file_path = _temp_file.name

                try:
                    dialect_enum = Dialect(dialect.lower())
                except ValueError:
                    dialect_enum = Dialect.TALEND

                analyzer = self.analyzer_factory.create(local_file_path, dialect_enum)

                if dialect == "sql":
                    return analyzer.get_sql_complexity_breakdown(sheet_name)
                else:
                    return analyzer.get_job_complexity_breakdown(sheet_name)

            except Exception as e:
                log.error(f"Failed to get complexity: {e}")
                raise
            finally:
                if _temp_file:
                    try:
                        os.unlink(_temp_file.name)
                    except Exception:
                        pass

        return await asyncio.to_thread(_get_complexity_sync)

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


