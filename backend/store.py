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
import os
import time
from typing import Any
from urllib.parse import urlparse

import redis.asyncio as aioredis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

log = logging.getLogger("fri.store")

# An OOM store fails EVERY write — logging each failure turned the failure
# itself into a CPU/IO burden on the F1 worker (2026-09-22 boot throttle).
# Log at most one line per op per window; the errors counter in stats()
# stays the honest, always-current signal.
ERR_LOG_EVERY_S = max(1.0, float(os.environ.get("FRI_ERR_LOG_EVERY_S", 60)))


def _safe_target(url: str) -> str:
    """Return scheme://host:port for logging — never include the password."""
    try:
        p = urlparse(url)
        port = f":{p.port}" if p.port else ""
        return f"{p.scheme}://{p.hostname or '?'}{port}"
    except Exception:
        return "<unparseable-redis-url>"


class Store:
    """Thin wrapper around redis.asyncio for JSON caching + pub/sub.

    Two error tiers (2026-09-22 free-tier hardening):

    - HIGH-LEVEL reads/writes (set/get/publish) NEVER raise: a store at its
      plan ceiling (Aiven free-1 = 30 MB) rejects writes with OOM replies,
      and a raising snapshot used to kill collector.start(), whose retry
      loop then burned the F1 CPU quota into a full worker wedge. Here the
      failure is logged + counted (see stats()) and the loop degrades.

    - LOW-LEVEL primitives (mset_raw, scan_keys, z*/s* helpers) still
      RAISE: callers that implement their own retry/compensation logic
      (did-persist re-queue, prune loop) need the real exception.
    """

    def __init__(self, url: str = "redis://redis:6379") -> None:
        self.url = url
        self.errors = 0  # failed high-level ops since boot (health signal)
        self._err_last: dict[str, float] = {}  # op -> last logged (monotonic)

        kwargs: dict[str, Any] = dict(
            decode_responses=True,
            socket_keepalive=True,
            socket_connect_timeout=10,
            # Hard cap per-command read wait: without it a black-holed pooled
            # connection (SNAT/LB silent drop) blocks the await forever.
            socket_timeout=15,
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

    def stats(self) -> dict[str, Any]:
        """Error counters for /api/health — write failures are the free-tier
        OOM signal the dashboard needs to surface."""
        return {"store_errors": self.errors}

    def _err_note(self, op: str, detail: str, e: Exception) -> None:
        """Count the failure always; log it at most once per window per op."""
        now = time.monotonic()
        if now - self._err_last.get(op, 0.0) >= ERR_LOG_EVERY_S:
            self._err_last[op] = now
            log.warning("store.%s(%s) failed: %s", op, detail, e)

    async def set(self, key: str, value: dict[str, Any]) -> bool:
        try:
            await self._redis.set(key, json.dumps(value))
            return True
        except Exception as e:
            self.errors += 1
            self._err_note("set", key, e)
            return False

    async def get(self, key: str) -> dict[str, Any] | None:
        try:
            data = await self._redis.get(key)
            return json.loads(data) if data else None
        except Exception as e:
            self.errors += 1
            self._err_note("get", key, e)
            return None

    async def publish(self, channel: str, message: dict[str, Any]) -> bool:
        try:
            await self._redis.publish(channel, json.dumps(message))
            return True
        except Exception as e:
            self.errors += 1
            self._err_note("publish", channel, e)
            return False

    # ------------------------------------------------------------------
    # Durable per-DID persistence (2026-09 "no DID is forgotten")
    # ------------------------------------------------------------------

    async def scan_keys(self, match: str, chunk: int = 500) -> list[str]:
        """All keys matching a glob pattern (SCAN, never KEYS)."""
        out: list[str] = []
        async for key in self._redis.scan_iter(match=match, count=chunk):
            out.append(key)
        return out

    async def mget_raw(self, keys: list[str]) -> list[str | None]:
        """Bulk raw-string GET in chunks (values are compact JSON)."""
        out: list[str | None] = []
        for i in range(0, len(keys), 500):
            chunk = keys[i : i + 500]
            out.extend(await self._redis.mget(chunk))
        return out

    async def mset_raw(self, mapping: dict[str, str]) -> None:
        """Bulk raw-string SET via non-transactional pipeline."""
        if not mapping:
            return
        items = list(mapping.items())
        for i in range(0, len(items), 500):
            chunk = items[i : i + 500]
            pipe = self._redis.pipeline(transaction=False)
            for key, value in chunk:
                pipe.set(key, value)
            await pipe.execute()

    async def sadd(self, key: str, members: list[str]) -> None:
        """Add members to a set (registry known-fingerprint tracking)."""
        if not members:
            return
        for i in range(0, len(members), 500):
            await self._redis.sadd(key, *members[i : i + 500])

    async def smembers(self, key: str) -> set[str]:
        """All members of a set; empty set when the key is absent."""
        try:
            return set(await self._redis.smembers(key))
        except Exception:
            return set()

    def pubsub(self):
        return self._redis.pubsub()

    async def zadd(self, key: str, score: float, member: str) -> None:
        await self._redis.zadd(key, {member: score})

    async def zadd_multi(self, key: str, pairs: list[tuple[float, str]]) -> None:
        """Batch ZADD via non-transactional pipeline (prune-index upkeep)."""
        if not pairs:
            return
        for i in range(0, len(pairs), 500):
            chunk = pairs[i : i + 500]
            pipe = self._redis.pipeline(transaction=False)
            pipe.zadd(key, {member: score for score, member in chunk})
            await pipe.execute()

    async def zrange(self, key: str, start: int, end: int) -> list[str]:
        return await self._redis.zrange(key, start, end)

    async def zrangebyscore(
        self, key: str, min_score: float, max_score: float | str
    ) -> list[str]:
        """Score-bounded zset read (inclusive bounds, like Redis).

        `max_score` accepts the Redis "+inf" sentinel for unbounded ranges —
        used by /api/health/snapshots so a request never pulls the whole
        sorted set just to discard most of it client-side.
        """
        return await self._redis.zrangebyscore(key, min_score, max_score)

    async def zremrangebyscore(self, key: str, min_score: float, max_score: float) -> None:
        await self._redis.zremrangebyscore(key, min_score, max_score)

    # ------------------------------------------------------------------
    # Prune primitives (raise — the prune loop owns error handling)
    # ------------------------------------------------------------------

    async def dbsize(self) -> int:
        return int(await self._redis.dbsize())

    async def zcard(self, key: str) -> int:
        return int(await self._redis.zcard(key))

    async def zrem(self, key: str, members: list[str]) -> int:
        if not members:
            return 0
        return int(await self._redis.zrem(key, *members))

    async def scard(self, key: str) -> int:
        return int(await self._redis.scard(key))

    async def spop(self, key: str, count: int) -> list[str]:
        """Remove and return up to `count` random members (known-set trim)."""
        if count <= 0:
            return []
        out = await self._redis.spop(key, count)
        return list(out) if out else []

    async def srem(self, key: str, members: list[str]) -> int:
        if not members:
            return 0
        return int(await self._redis.srem(key, *members))

    async def delete(self, keys: list[str]) -> int:
        """Batch DELETE via non-transactional pipeline (returns deleted count)."""
        if not keys:
            return 0
        deleted = 0
        for i in range(0, len(keys), 500):
            pipe = self._redis.pipeline(transaction=False)
            for key in keys[i : i + 500]:
                pipe.delete(key)
            results = await pipe.execute()
            deleted += sum(1 for r in results if r)
        return deleted

    async def close(self) -> None:
        await self._redis.close()
