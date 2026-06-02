"""TTL cache — Redis (production) or in-memory dict (local dev fallback)."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import TYPE_CHECKING, Generic, TypeVar

from pydantic import BaseModel

from app.config import settings

if TYPE_CHECKING:
    from redis import Redis

logger = logging.getLogger(__name__)

T = TypeVar("T")

_CACHE_PREFIX = "da:cache:"


@dataclass
class _MemoryEntry:
    payload: str
    expires_at: datetime


class CacheBackend(ABC):
    @abstractmethod
    def get(self, key: str) -> object | None: ...

    @abstractmethod
    def set(self, key: str, value: object, *, ttl_seconds: int) -> None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def clear(self) -> None: ...

    @property
    @abstractmethod
    def backend_name(self) -> str: ...


def _serialize_value(value: object) -> str:
    if isinstance(value, BaseModel):
        return json.dumps(
            {
                "__pydantic__": f"{value.__class__.__module__}.{value.__class__.__name__}",
                "payload": value.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
    return json.dumps({"__raw__": value}, ensure_ascii=False, default=str)


def _deserialize_value(raw: str) -> object | None:
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not isinstance(envelope, dict):
        return envelope

    if "__pydantic__" in envelope:
        type_key = envelope["__pydantic__"]
        payload = envelope.get("payload")
        if type_key == "app.schemas.scorecard.AnalyzeResponse":
            from app.schemas.scorecard import AnalyzeResponse

            return AnalyzeResponse.model_validate(payload)
        logger.warning("Unknown cached pydantic type: %s", type_key)
        return None

    if "__raw__" in envelope:
        return envelope["__raw__"]

    return envelope


class MemoryCacheBackend(CacheBackend):
    def __init__(self) -> None:
        self._store: dict[str, _MemoryEntry] = {}
        self._lock = Lock()

    @property
    def backend_name(self) -> str:
        return "memory"

    def get(self, key: str) -> object | None:
        now = datetime.now(timezone.utc)
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.expires_at <= now:
                del self._store[key]
                return None
            return _deserialize_value(entry.payload)

    def set(self, key: str, value: object, *, ttl_seconds: int) -> None:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(1, ttl_seconds))
        payload = _serialize_value(value)
        with self._lock:
            self._store[key] = _MemoryEntry(payload=payload, expires_at=expires_at)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


class RedisCacheBackend(CacheBackend):
    def __init__(self, redis_url: str) -> None:
        import redis

        self._client: Redis = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        self._client.ping()

    @property
    def backend_name(self) -> str:
        return "redis"

    def _redis_key(self, key: str) -> str:
        return f"{_CACHE_PREFIX}{key}"

    def get(self, key: str) -> object | None:
        raw = self._client.get(self._redis_key(key))
        if raw is None:
            return None
        return _deserialize_value(raw)

    def set(self, key: str, value: object, *, ttl_seconds: int) -> None:
        payload = _serialize_value(value)
        self._client.setex(self._redis_key(key), max(1, ttl_seconds), payload)

    def delete(self, key: str) -> None:
        self._client.delete(self._redis_key(key))

    def clear(self) -> None:
        pattern = f"{_CACHE_PREFIX}*"
        cursor = 0
        while True:
            cursor, keys = self._client.scan(cursor=cursor, match=pattern, count=200)
            if keys:
                self._client.delete(*keys)
            if cursor == 0:
                break


_backend: CacheBackend | None = None
_backend_lock = Lock()


def _create_backend() -> CacheBackend:
    redis_url = settings.redis_url.strip()
    if redis_url:
        try:
            backend = RedisCacheBackend(redis_url)
            logger.info("Cache backend: Redis")
            return backend
        except Exception as exc:
            logger.warning(
                "Redis unavailable (%s); falling back to in-memory cache.",
                exc,
            )
    logger.info("Cache backend: in-memory")
    return MemoryCacheBackend()


def get_cache_backend() -> CacheBackend:
    """Lazy singleton cache backend."""
    global _backend
    if _backend is None:
        with _backend_lock:
            if _backend is None:
                _backend = _create_backend()
    return _backend


def reset_cache_backend_for_tests() -> None:
    """Reset backend singleton (tests only)."""
    global _backend
    with _backend_lock:
        _backend = None


def cache_get(key: str) -> object | None:
    return get_cache_backend().get(key)


def cache_set(key: str, value: object, *, ttl_seconds: int) -> None:
    get_cache_backend().set(key, value, ttl_seconds=ttl_seconds)


def cache_delete(key: str) -> None:
    get_cache_backend().delete(key)


def cache_clear() -> None:
    get_cache_backend().clear()


def get_cache_backend_name() -> str:
    return get_cache_backend().backend_name
