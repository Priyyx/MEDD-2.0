"""Small thread-safe TTL cache keyed by (data_version, key). Invalidated on every successful ingestion."""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

from app.config import get_settings


class TTLCache:
    def __init__(self, ttl: int, max_items: int = 512) -> None:
        self.ttl, self.max_items = ttl, max_items
        self._d: dict[Any, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._inflight: dict[Any, threading.Lock] = {}
        self.hits = self.misses = 0

    def get_or_set(self, key: Any, fn: Callable[[], Any]) -> Any:
        now = time.monotonic()
        with self._lock:
            hit = self._d.get(key)
            if hit and hit[0] > now:
                self.hits += 1
                return hit[1]
        # single-flight: concurrent requests for the same key wait for ONE computation (no cache stampede)
        with self._lock:
            kl = self._inflight.setdefault(key, threading.Lock())
        with kl:
            with self._lock:
                hit = self._d.get(key)
                if hit and hit[0] > time.monotonic():
                    self.hits += 1
                    return hit[1]
            self.misses += 1
            val = fn()
            self._store(key, val, now)
        with self._lock:
            self._inflight.pop(key, None)
        return val

    def _store(self, key, val, now):
        with self._lock:
            if len(self._d) >= self.max_items:
                for k in sorted(self._d, key=lambda k: self._d[k][0])[: self.max_items // 4]:
                    self._d.pop(k, None)
            self._d[key] = (now + self.ttl, val)

    def clear(self) -> None:
        with self._lock:
            self._d.clear()

    def stats(self) -> dict:
        return {"items": len(self._d), "hits": self.hits, "misses": self.misses, "ttl_seconds": self.ttl}


cache = TTLCache(get_settings().cache_ttl_seconds)
