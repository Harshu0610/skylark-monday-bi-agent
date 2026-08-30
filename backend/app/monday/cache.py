"""Tiny TTL cache for board fetches.

A demo asks ten questions in three minutes; without this that is twenty board
fetches and a rate limit. It also gives us something to serve when Monday is
down, which is the difference between a degraded answer and no answer.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass
class CacheEntry(Generic[T]):
    value: T
    stored_at: float

    @property
    def age_seconds(self) -> int:
        return int(time.time() - self.stored_at)


class TTLCache(Generic[T]):
    def __init__(self, ttl_seconds: int) -> None:
        self.ttl = ttl_seconds
        self._store: dict[str, CacheEntry[T]] = {}

    def get(self, key: str) -> T | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.age_seconds > self.ttl:
            return None
        return entry.value

    def get_stale(self, key: str) -> CacheEntry[T] | None:
        """Return an entry regardless of age -- used when the API is unavailable
        and a clearly-labelled stale answer beats no answer at all."""
        return self._store.get(key)

    def set(self, key: str, value: T) -> None:
        self._store[key] = CacheEntry(value=value, stored_at=time.time())

    def entry(self, key: str) -> CacheEntry[T] | None:
        return self._store.get(key)

    def clear(self) -> None:
        self._store.clear()


def cache_meta(entry: CacheEntry[Any] | None) -> dict[str, Any]:
    if entry is None:
        return {"fetched_at": None, "age_seconds": None}
    return {
        "fetched_at": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(entry.stored_at)
        ),
        "age_seconds": entry.age_seconds,
    }
