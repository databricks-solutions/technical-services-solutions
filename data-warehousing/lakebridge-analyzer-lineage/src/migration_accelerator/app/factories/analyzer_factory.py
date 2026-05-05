"""
Factory for creating analyzer instances.

Centralizes analyzer creation logic to eliminate duplication across the codebase.
"""

from contextlib import contextmanager
from typing import Optional

from migration_accelerator.app.constants import Dialect
from migration_accelerator.configs.modules import AnalyzerConfig, LLMConfig
from migration_accelerator.discovery.analyzer.base import SourceAnalyzer


class AnalyzerFactory:
    """
    Factory for creating and managing analyzer instances.
    
    Eliminates duplicate analyzer creation code by providing a single
    point of instantiation with consistent configuration.
    """
    
    def __init__(self, llm_config: Optional[LLMConfig] = None):
        """
        Initialize analyzer factory.
        
        Args:
            llm_config: Optional LLM configuration for analyzer operations
        """
        self.llm_config = llm_config
    
    def create(self, file_path: str, dialect: Dialect) -> SourceAnalyzer:
        """
        Create analyzer instance for a file.
        
        Args:
            file_path: Path to analyzer file
            dialect: Analyzer dialect enum
            
        Returns:
            Configured SourceAnalyzer instance
            
        Example:
            factory = AnalyzerFactory(llm_config)
            analyzer = factory.create("/path/to/file.xlsx", Dialect.SQL)
        """
        config = AnalyzerConfig(analyzer_file=file_path, dialect=dialect.value)
        return SourceAnalyzer(config, llm_config=self.llm_config)
    
    @contextmanager
    def analyzer_context(self, file_path: str, dialect: Dialect):
        """
        Context manager for analyzer with automatic cleanup.
        
        Args:
            file_path: Path to analyzer file
            dialect: Analyzer dialect enum
            
        Yields:
            Configured SourceAnalyzer instance
            
        Example:
            factory = AnalyzerFactory()
            with factory.analyzer_context("/path/to/file.xlsx", Dialect.TALEND) as analyzer:
                data = analyzer.parse()
        """
        analyzer = self.create(file_path, dialect)
        try:
            yield analyzer
        finally:
            # Add cleanup logic if needed in the future
            pass




