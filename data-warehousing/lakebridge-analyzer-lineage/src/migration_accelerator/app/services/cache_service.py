"""
In-memory caching service with TTL support for aggregate lineage optimization.
"""

import hashlib
import json
import time
from typing import Any, Dict, Optional
from collections import OrderedDict
from threading import Lock

from migration_accelerator.utils.logger import get_logger

log = get_logger()


class CacheService:
    """
    Simple in-memory cache with TTL and LRU eviction.
    
    For production, this could be replaced with Redis, but in-memory
    is sufficient for single-instance deployments and avoids external dependencies.
    """

    def __init__(self, max_size: int = 100, default_ttl: int = 3600):
        """
        Initialize cache service.

        Args:
            max_size: Maximum number of cache entries (LRU eviction when exceeded)
            default_ttl: Default time-to-live in seconds (1 hour default)
        """
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._lock = Lock()
        
        log.info(f"Cache initialized with max_size={max_size}, default_ttl={default_ttl}s")

    def _is_expired(self, entry: Dict[str, Any]) -> bool:
        """Check if cache entry is expired."""
        expiry = entry.get("expiry", 0)
        return time.time() > expiry

    def _evict_if_needed(self) -> None:
        """Evict oldest entry if cache is full."""
        if len(self._cache) >= self.max_size:
            oldest_key = next(iter(self._cache))
            self._cache.pop(oldest_key)
            log.debug(f"Evicted cache entry: {oldest_key}")

    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        with self._lock:
            entry = self._cache.get(key)
            
            if entry is None:
                log.debug(f"Cache miss: {key}")
                return None
            
            if self._is_expired(entry):
                log.debug(f"Cache expired: {key}")
                self._cache.pop(key)
                return None
            
            # Move to end (LRU)
            self._cache.move_to_end(key)
            
            log.debug(f"Cache hit: {key}")
            return entry["value"]

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        Set value in cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds (uses default if not specified)
        """
        with self._lock:
            ttl = ttl if ttl is not None else self.default_ttl
            expiry = time.time() + ttl
            
            self._cache[key] = {
                "value": value,
                "expiry": expiry,
                "created_at": time.time(),
            }
            
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            
            # Evict if needed
            self._evict_if_needed()
            
            log.debug(f"Cache set: {key} (ttl={ttl}s)")

    def delete(self, key: str) -> None:
        """
        Delete entry from cache.

        Args:
            key: Cache key
        """
        with self._lock:
            if key in self._cache:
                self._cache.pop(key)
                log.debug(f"Cache deleted: {key}")

    def invalidate_pattern(self, pattern: str) -> int:
        """
        Invalidate all cache keys matching a pattern.

        Args:
            pattern: Pattern to match (e.g., "lineage:aggregate:user123:*")

        Returns:
            Number of keys invalidated
        """
        with self._lock:
            # Simple prefix matching for now
            keys_to_delete = [k for k in self._cache.keys() if k.startswith(pattern.rstrip("*"))]
            
            for key in keys_to_delete:
                self._cache.pop(key)
            
            count = len(keys_to_delete)
            if count > 0:
                log.info(f"Invalidated {count} cache entries matching: {pattern}")
            
            return count

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            log.info(f"Cache cleared: {count} entries removed")

    def stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        with self._lock:
            total_entries = len(self._cache)
            expired_count = sum(1 for entry in self._cache.values() if self._is_expired(entry))
            
            return {
                "total_entries": total_entries,
                "expired_entries": expired_count,
                "active_entries": total_entries - expired_count,
                "max_size": self.max_size,
                "utilization": f"{(total_entries / self.max_size * 100):.1f}%",
            }


def generate_cache_key(user_id: str, file_ids: list, include_deps: bool = False) -> str:
    """
    Generate a deterministic cache key for aggregate lineage.

    Args:
        user_id: User identifier
        file_ids: List of file IDs (sorted for determinism)
        include_deps: Whether file dependencies are included

    Returns:
        Cache key string
    """
    # Sort file IDs for deterministic key generation
    sorted_file_ids = sorted(file_ids)
    
    # Create hash of file IDs to keep key length reasonable
    file_hash = hashlib.md5(json.dumps(sorted_file_ids).encode()).hexdigest()[:12]
    
    deps_suffix = "_deps" if include_deps else ""
    
    return f"lineage:aggregate:{user_id}:{file_hash}{deps_suffix}"


# Global cache instance (singleton)
_cache_instance: Optional[CacheService] = None


def get_cache_service() -> CacheService:
    """Get or create the global cache service instance."""
    global _cache_instance
    
    if _cache_instance is None:
        _cache_instance = CacheService(max_size=100, default_ttl=3600)
    
    return _cache_instance


