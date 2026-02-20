"""
FastAPI dependencies for dependency injection.

Uses singleton pattern for services to avoid creating multiple instances.
"""

from functools import lru_cache
from typing import Optional

from fastapi import Header, HTTPException, Request

from migration_accelerator.app.config import settings
from migration_accelerator.app.services import (
    AnalyzerService,
    LineageService,
    LLMService,
    StorageService,
)
from migration_accelerator.app.services.analyzer_query_service import AnalyzerQueryService
from migration_accelerator.app.services.cache_service import CacheService, get_cache_service
from migration_accelerator.app.services.lineage_analyzer import LineageAnalyzer
from migration_accelerator.app.services.lineage_auto_generator import LineageAutoGenerator
from migration_accelerator.app.services.lineage_exporter import LineageExporter
from migration_accelerator.app.services.lineage_merger import LineageMerger
from migration_accelerator.app.services.migration_planner import MigrationPlanner
from migration_accelerator.utils.logger import get_logger

log = get_logger()

# Global service instances (singletons)
_storage_service: Optional[StorageService] = None
_analyzer_service: Optional[AnalyzerService] = None
_lineage_service: Optional[LineageService] = None
_llm_service: Optional[LLMService] = None
_lineage_merger: Optional[LineageMerger] = None
_lineage_analyzer: Optional[LineageAnalyzer] = None
_migration_planner: Optional[MigrationPlanner] = None
_lineage_exporter: Optional[LineageExporter] = None
_analyzer_query_service: Optional[AnalyzerQueryService] = None
_lineage_auto_generator: Optional[LineageAutoGenerator] = None


@lru_cache(maxsize=1)
def get_storage_service() -> StorageService:
    """Get singleton storage service instance."""
    global _storage_service
    if _storage_service is None:
        _storage_service = StorageService()
    return _storage_service


@lru_cache(maxsize=1)
def get_analyzer_service() -> AnalyzerService:
    """Get singleton analyzer service instance."""
    global _analyzer_service
    if _analyzer_service is None:
        _analyzer_service = AnalyzerService(llm_endpoint=settings.llm_endpoint)
    return _analyzer_service


@lru_cache(maxsize=1)
def get_lineage_service() -> LineageService:
    """Get singleton lineage service instance."""
    global _lineage_service
    if _lineage_service is None:
        from migration_accelerator.app.config import get_storage_path
        storage_path = get_storage_path()
        _lineage_service = LineageService(
            llm_endpoint=settings.llm_endpoint,
            storage_path=storage_path
        )
    return _lineage_service


@lru_cache(maxsize=1)
def get_llm_service() -> LLMService:
    """Get singleton LLM service instance."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService(llm_endpoint=settings.llm_endpoint)
    return _llm_service


@lru_cache(maxsize=1)
def get_lineage_merger() -> LineageMerger:
    """Get singleton lineage merger instance."""
    global _lineage_merger
    if _lineage_merger is None:
        storage = get_storage_service()
        lineage = get_lineage_service()
        cache = get_cache_service()
        _lineage_merger = LineageMerger(
            storage_service=storage,
            lineage_service=lineage,
            cache_service=cache
        )
    return _lineage_merger


@lru_cache(maxsize=1)
def get_lineage_analyzer() -> LineageAnalyzer:
    """Get singleton lineage analyzer instance."""
    global _lineage_analyzer
    if _lineage_analyzer is None:
        cache = get_cache_service()
        _lineage_analyzer = LineageAnalyzer(cache_service=cache)
    return _lineage_analyzer


@lru_cache(maxsize=1)
def get_migration_planner() -> MigrationPlanner:
    """Get singleton migration planner instance."""
    global _migration_planner
    if _migration_planner is None:
        _migration_planner = MigrationPlanner()
    return _migration_planner


@lru_cache(maxsize=1)
def get_lineage_exporter() -> LineageExporter:
    """Get singleton lineage exporter instance."""
    global _lineage_exporter
    if _lineage_exporter is None:
        _lineage_exporter = LineageExporter()
    return _lineage_exporter


@lru_cache(maxsize=1)
def get_analyzer_query_service() -> AnalyzerQueryService:
    """Get singleton analyzer query service instance."""
    global _analyzer_query_service
    if _analyzer_query_service is None:
        _analyzer_query_service = AnalyzerQueryService(llm_endpoint=settings.llm_endpoint)
    return _analyzer_query_service


@lru_cache(maxsize=1)
def get_lineage_auto_generator() -> LineageAutoGenerator:
    """Get singleton lineage auto generator instance."""
    global _lineage_auto_generator
    if _lineage_auto_generator is None:
        _lineage_auto_generator = LineageAutoGenerator()
    return _lineage_auto_generator


async def get_current_user(request: Request) -> str:
    """
    Get current user email from request.
    
    Extracts user email from x-forwarded-access-token header (JWT) provided by Databricks Apps,
    or X-User-ID header for testing purposes.
    Note: This only extracts the email for per-user folder organization.
    All UC operations use the service principal configured in the environment.
    
    Args:
        request: FastAPI request
    
    Returns:
        User email address
    """
    # Check for test header first (X-User-ID) - used in tests for user isolation
    test_user_id = request.headers.get("x-user-id") or request.headers.get("X-User-ID")
    if test_user_id:
        log.debug(f"Using test user ID from header: {test_user_id}")
        return test_user_id
    
    # In debug mode, use test user
    if settings.debug:
        return "test_user"
    
    # Get user token from Databricks Apps header
    user_token = request.headers.get("x-forwarded-access-token")
    
    if not user_token:
        log.warning("No x-forwarded-access-token header found, using default user")
        return "default_user"
    
    # Decode JWT to extract user email (without making API calls)
    try:
        import jwt
        
        # Decode without verification (we trust Databricks Apps infrastructure)
        # The token is already validated by Databricks before reaching our app
        decoded = jwt.decode(user_token, options={"verify_signature": False})
        
        # Extract email from standard JWT claims
        user_email = decoded.get("email") or decoded.get("sub") or decoded.get("upn")
        
        if user_email:
            log.info(f"Extracted user email from token: {user_email}")
            return user_email
        else:
            log.warning("Could not find email in token claims")
            return "unknown_user"
            
    except Exception as e:
        log.error(f"Failed to decode user token: {e}")
        return "unknown_user"


async def verify_file_access(
    file_id: str, user_id: str, storage: StorageService
) -> bool:
    """
    Verify user has access to file.
    
    For Unity Catalog: If get_file_path succeeds, file exists (SDK verified it)
    For Local: Check filesystem with .exists()

    Args:
        file_id: File identifier
        user_id: User identifier
        storage: Storage service

    Returns:
        True if user has access

    Raises:
        HTTPException: If access denied
    """
    # Simply check if we can get the file path
    # For UC: get_file_path already verified existence via SDK
    # For Local: get_file_path checks existence
    file_path = storage.get_file_path(file_id, user_id)
    
    if not file_path:
        raise HTTPException(status_code=404, detail="File not found")
    
    # For local storage, double-check filesystem
    from migration_accelerator.app.config import StorageBackend
    if storage.storage_backend == StorageBackend.IN_MEMORY:
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="File not found")
    
    return True


