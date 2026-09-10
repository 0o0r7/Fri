"""Redis store — caching + pub/sub for live data fan-out."""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis

log = logging.getLogger("fri.store")


class Store:
    """Thin wrapper around redis.asyncio for JSON caching + pub/sub."""

    def __init__(self, url: str = "redis://redis:6379") -> None:
        self._redis = aioredis.from_url(url, decode_responses=True)

    async def set(self, key: str, value: dict[str, Any]) -> None:
        await self._redis.set(key, json.dumps(value))

    async def get(self, key: str) -> dict[str, Any] | None:
        data = await self._redis.get(key)
        return json.loads(data) if data else None

    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        await self._redis.publish(channel, json.dumps(message))

    def pubsub(self):
        return self._redis.pubsub()

    async def close(self) -> None:
        await self._redis.close()
