"""
Application configuration management.
"""

import os
from enum import Enum
from typing import Optional

from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class StorageBackend(str, Enum):
    """Supported storage backends.
    
    - unity_catalog: Unity Catalog Volumes (recommended for production)
    - in_memory: In-memory storage (for development/testing)
    """

    UNITY_CATALOG = "unity_catalog"
    IN_MEMORY = "in_memory"


class Settings(BaseSettings):
    """Application settings."""

    # App settings
    app_name: str = "Migration Accelerator"
    app_version: str = "0.2.0"
    debug: bool = False
    
    # LLM settings
    llm_endpoint: str = os.getenv(
        "LLM_ENDPOINT", 
        "databricks-meta-llama-3-1-70b-instruct"
    )
    llm_temperature: float = 0.1
    llm_max_tokens: int = 2000
    
    # Storage settings - NO HARDCODED PRODUCTION PATHS
    storage_backend: StorageBackend = StorageBackend.IN_MEMORY  # Safe default
    uc_volume_path: Optional[str] = None  # Unity Catalog volume path (e.g., /Volumes/catalog/schema/volume)
    
    # API settings
    api_prefix: str = "/api/v1"
    cors_origins: list = []
    max_upload_size: int = 100 * 1024 * 1024  # 100MB
    
    # Session settings
    session_timeout_hours: int = 24
    
    model_config = ConfigDict(
        env_file=".env",
        case_sensitive=False
    )


# Global settings instance
settings = Settings()


def get_storage_path() -> str:
    """Get storage path based on backend.
    
    Returns:
        Path for Unity Catalog Volumes or /tmp for in-memory storage
    
    Raises:
        ValueError: If UC backend selected but path not configured
    """
    if settings.storage_backend == StorageBackend.UNITY_CATALOG:
        if not settings.uc_volume_path:
            raise ValueError(
                "Unity Catalog backend requires UC_VOLUME_PATH "
                "to be set in environment or .env file"
            )
        return settings.uc_volume_path
    else:
        # IN_MEMORY backend uses local tmp directory
        return "/tmp/migration-accelerator"


def reload_settings_from_env() -> Settings:
    """
    Reload settings from environment variables.
    
    Used by integration tests to force reload after .env.integration is loaded.
    
    Returns:
        Reloaded settings instance
    """
    global settings
    settings = Settings()
    return settings


def clear_service_cache():
    """
    Clear all cached service instances.
    
    Forces services to reinitialize with new settings.
    Called by integration tests after reloading settings.
    """
    from migration_accelerator.app.api import dependencies
    from migration_accelerator.app.services import cache_service
    
    # Clear lru_cache for all service getters
    dependencies.get_storage_service.cache_clear()
    dependencies.get_analyzer_service.cache_clear()
    dependencies.get_lineage_service.cache_clear()
    dependencies.get_llm_service.cache_clear()
    dependencies.get_lineage_merger.cache_clear()
    dependencies.get_lineage_analyzer.cache_clear()
    dependencies.get_migration_planner.cache_clear()
    dependencies.get_lineage_exporter.cache_clear()
    dependencies.get_analyzer_query_service.cache_clear()
    dependencies.get_lineage_auto_generator.cache_clear()
    
    # Clear global service instances
    dependencies._storage_service = None
    dependencies._analyzer_service = None
    dependencies._lineage_service = None
    dependencies._llm_service = None
    dependencies._lineage_merger = None
    dependencies._lineage_analyzer = None
    dependencies._migration_planner = None
    dependencies._lineage_exporter = None
    dependencies._analyzer_query_service = None
    dependencies._lineage_auto_generator = None
    
    # Clear cache service (uses global variable, not lru_cache)
    cache_service._cache_instance = None
