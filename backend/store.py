"""Redis store — caching + pub/sub for live data fan-out.

Hardened for serverless Redis providers (e.g. Upstash free tier):
- rediss:// (TLS) URLs work as-is; a redis:// URL pointing at an Upstash
  host logs an explicit hint because Upstash drops plain-TEXT connections
- socket keepalive + periodic health checks detect provider-side idle closes
- transient connection/timeout errors are retried with exponential backoff
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlparse

import redis.asyncio as aioredis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

log = logging.getLogger("fri.store")


def _safe_target(url: str) -> str:
    """Return scheme://host:port for logging — never include the password."""
    try:
        p = urlparse(url)
        port = f":{p.port}" if p.port else ""
        return f"{p.scheme}://{p.hostname or '?'}{port}"
    except Exception:
        return "<unparseable-redis-url>"


class Store:
    """Thin wrapper around redis.asyncio for JSON caching + pub/sub."""

    def __init__(self, url: str = "redis://redis:6379") -> None:
        self.url = url

        kwargs: dict[str, Any] = dict(
            decode_responses=True,
            socket_keepalive=True,
            socket_connect_timeout=10,
            health_check_interval=30,
        )
        # Retry transient connection errors (Upstash closes idle connections)
        try:
            kwargs["retry"] = Retry(ExponentialBackoff(cap=1.0, base=0.05), retries=3)
            kwargs["retry_on_error"] = [RedisConnectionError, RedisTimeoutError]
        except Exception:  # pragma: no cover — very old redis-py without Retry
            log.warning("redis-py Retry unavailable — running without retries")

        parsed = urlparse(url)
        host = parsed.hostname or ""
        if parsed.scheme == "redis" and "upstash" in host:
            log.warning(
                "REDIS_URL uses redis:// but the host looks like Upstash (%s). "
                "Upstash only accepts TLS connections — use rediss:// (the Redis "
                "URL from the Upstash console, not the REST URL).",
                host,
            )
        if parsed.scheme not in ("redis", "rediss", "unix"):
            log.warning(
                "REDIS_URL has unexpected scheme %r in %s",
                parsed.scheme,
                _safe_target(url),
            )

        log.info("Connecting to Redis at %s", _safe_target(url))
        self._redis = aioredis.from_url(url, **kwargs)

    async def ping(self) -> bool:
        """True if Redis answers PING — used by /api/health to report degraded state."""
        try:
            return bool(await self._redis.ping())
        except Exception as e:
            log.warning("Redis ping failed (%s): %s", _safe_target(self.url), e)
            return False

    async def set(self, key: str, value: dict[str, Any]) -> None:
        await self._redis.set(key, json.dumps(value))

    async def get(self, key: str) -> dict[str, Any] | None:
        data = await self._redis.get(key)
        return json.loads(data) if data else None

    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        await self._redis.publish(channel, json.dumps(message))

    def pubsub(self):
        return self._redis.pubsub()

    async def zadd(self, key: str, score: float, member: str) -> None:
        await self._redis.zadd(key, {member: score})

    async def zrange(self, key: str, start: int, end: int) -> list[str]:
        return await self._redis.zrange(key, start, end)

    async def zremrangebyscore(self, key: str, min_score: float, max_score: float) -> None:
        await self._redis.zremrangebyscore(key, min_score, max_score)

    async def close(self) -> None:
        await self._redis.close()
