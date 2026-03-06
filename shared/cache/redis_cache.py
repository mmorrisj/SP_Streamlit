"""
Redis caching layer for FastAPI endpoints.

Graceful degradation: if Redis is unavailable, all operations are no-ops
and requests fall through to the database. No errors are raised.

Usage in FastAPI:
    from shared.cache.redis_cache import cache, init_cache

    # Call once at startup
    init_cache()

    @app.get("/api/metrics/overall")
    @cache(ttl=300)
    async def get_overall_metrics():
        ...

    # Or manual usage:
    from shared.cache.redis_cache import get_cache
    rc = get_cache()
    rc.set("key", data, ttl=600)
    data = rc.get("key")
"""

import os
import json
import hashlib
import logging
import functools
from typing import Optional, Any

logger = logging.getLogger(__name__)

_redis_client = None
_redis_available = False


def init_cache(redis_url: Optional[str] = None) -> bool:
    """Initialize the Redis connection. Returns True if Redis is available."""
    global _redis_client, _redis_available

    url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    try:
        import redis
        _redis_client = redis.from_url(url, decode_responses=True, socket_timeout=2, socket_connect_timeout=2)
        _redis_client.ping()
        _redis_available = True
        logger.info("Redis cache connected: %s", url.split("@")[-1])  # Log without password
        return True
    except Exception as e:
        _redis_client = None
        _redis_available = False
        logger.warning("Redis unavailable (%s) — caching disabled, all requests hit database", e)
        return False


class CacheClient:
    """Thin wrapper around Redis with graceful fallback."""

    def get(self, key: str) -> Optional[Any]:
        if not _redis_available:
            return None
        try:
            raw = _redis_client.get(key)
            if raw is not None:
                return json.loads(raw)
        except Exception:
            return None
        return None

    def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        if not _redis_available:
            return False
        try:
            _redis_client.setex(key, ttl, json.dumps(value, default=str))
            return True
        except Exception:
            return False

    def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching a glob pattern (e.g. 'api:metrics:*')."""
        if not _redis_available:
            return 0
        try:
            keys = list(_redis_client.scan_iter(match=pattern, count=500))
            if keys:
                return _redis_client.delete(*keys)
        except Exception:
            pass
        return 0

    def flush_all(self) -> bool:
        """Clear the entire cache. Use sparingly (e.g. after pipeline runs)."""
        if not _redis_available:
            return False
        try:
            _redis_client.flushdb()
            return True
        except Exception:
            return False

    @property
    def available(self) -> bool:
        return _redis_available


_cache_client = CacheClient()


def get_cache() -> CacheClient:
    return _cache_client


def _build_cache_key(prefix: str, args, kwargs) -> str:
    """Build a deterministic cache key from endpoint prefix and query params."""
    # Include all args/kwargs that affect the response
    parts = [prefix]
    if args:
        parts.extend(str(a) for a in args)
    if kwargs:
        for k in sorted(kwargs.keys()):
            v = kwargs[k]
            if v is not None:
                parts.append(f"{k}={v}")
    raw = "|".join(parts)
    h = hashlib.md5(raw.encode()).hexdigest()[:12]
    return f"api:{prefix}:{h}"


def cache(ttl: int = 300, prefix: Optional[str] = None):
    """
    Decorator for FastAPI endpoint functions. Caches JSON-serializable responses.

    Args:
        ttl: Cache time-to-live in seconds (default 5 minutes)
        prefix: Cache key prefix (default: function name)
    """
    def decorator(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not _redis_available:
                return await func(*args, **kwargs)

            key_prefix = prefix or func.__name__
            cache_key = _build_cache_key(key_prefix, args, kwargs)

            cached = _cache_client.get(cache_key)
            if cached is not None:
                return cached

            result = await func(*args, **kwargs)
            _cache_client.set(cache_key, result, ttl=ttl)
            return result

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            if not _redis_available:
                return func(*args, **kwargs)

            key_prefix = prefix or func.__name__
            cache_key = _build_cache_key(key_prefix, args, kwargs)

            cached = _cache_client.get(cache_key)
            if cached is not None:
                return cached

            result = func(*args, **kwargs)
            _cache_client.set(cache_key, result, ttl=ttl)
            return result

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
