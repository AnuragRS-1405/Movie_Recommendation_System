"""
cache_service.py — Lightweight in-memory TTL cache for TMDB responses and
computed feature vectors. Avoids redundant API calls and re-vectorizing the
same movie on every request.

Design:
  - Async-safe via asyncio.Lock per cache bucket
  - TTL-based expiry (entries silently expire on next read)
  - Six separate buckets: tmdb_details, tmdb_search, feature_vectors,
    home_feed, credits, and videos
  - No external dependencies (no Redis, no cachetools)

v5.0 additions:
  - credits_cache  — cast/crew data, expires after 30 minutes
  - videos_cache   — trailer video keys, expires after 30 minutes
  - discovery_cache — genre/language/regional discovery results, 5 minutes
"""
import asyncio
import time
from typing import Any, Dict, Optional, Tuple

# ── Internal storage type ─────────────────────────────────────────────────────
# Each bucket stores {key: (value, expires_at_monotonic)}
_Bucket = Dict[str, Tuple[Any, float]]


class _TTLCache:
    """Single bucket async TTL cache."""

    def __init__(self, default_ttl: float = 300.0):
        self._store: _Bucket = {}
        self._lock = asyncio.Lock()
        self.default_ttl = default_ttl

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            return value

    async def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        expires_at = time.monotonic() + (ttl if ttl is not None else self.default_ttl)
        async with self._lock:
            self._store[key] = (value, expires_at)

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()

    def sync_get(self, key: str) -> Optional[Any]:
        """Synchronous get for use in non-async contexts."""
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    def sync_set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Synchronous set for use in non-async contexts."""
        expires_at = time.monotonic() + (ttl if ttl is not None else self.default_ttl)
        self._store[key] = (value, expires_at)

    def size(self) -> int:
        """Returns approximate number of cached (possibly expired) entries."""
        return len(self._store)


# ── Module-level cache instances ──────────────────────────────────────────────

# TMDB movie details: 10 minutes (mostly static data)
tmdb_details_cache = _TTLCache(default_ttl=600.0)

# TMDB search results: 5 minutes
tmdb_search_cache = _TTLCache(default_ttl=300.0)

# Computed feature vectors for external movies: 30 minutes
feature_vector_cache = _TTLCache(default_ttl=1800.0)

# Home feed / discover results: 3 minutes (frequently changing)
home_feed_cache = _TTLCache(default_ttl=180.0)

# v5.0 — Cast and crew data: 30 minutes (static, rarely changes)
credits_cache = _TTLCache(default_ttl=1800.0)

# v5.0 — Trailer video keys: 30 minutes (static)
videos_cache = _TTLCache(default_ttl=1800.0)

# v5.0 — Regional & language discovery results: 5 minutes
discovery_cache = _TTLCache(default_ttl=300.0)
