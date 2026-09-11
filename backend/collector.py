"""Async collector loop — continuous real-time data pipeline.

Replaces the batch `collector/main.py` with a long-running async process that:
1. Long-polls technocore.chat rooms using wait=10 (connection-held)
2. Periodically fetches /rooms for metadata + scoring
3. Feeds messages through existing scoring/indexing modules
4. Snapshots to Redis + publishes events via pub/sub
5. Gracefully degrades when technocore is unreachable
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from collector.config import (
    ALWAYS_POLL_ROOMS,
    PROTOCOL_VERSIONS,
    ROOMS_LIMIT,
    ROOM_MESSAGE_LIMITS,
    TOP_N,
    USER_AGENT,
)
from collector.did_index import DidIndex
from collector.kibble import KibbleIndex
from collector.reputation import ReputationScorer
from collector.score import score_room
from collector.tclk import TclkIndex

from .store import Store

log = logging.getLogger("fri.collector")

REDIS_CHANNEL = "fri:events"

# Rooms to long-poll continuously: always-poll set + the events discovery feed
MONITORED_ROOMS: list[str] = list(dict.fromkeys([*ALWAYS_POLL_ROOMS, "events"]))

# Rolling window of messages per room (for live scoring)
ROOM_MSG_WINDOW = 200


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CollectorLoop:
    """Continuous async collector that feeds live data to Redis + pub/sub."""

    def __init__(self, store: Store, base_url: str = "https://technocore.chat") -> None:
        self.store = store
        self.base_url = base_url
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={"User-Agent": f"{USER_AGENT} (live)"},
            timeout=httpx.Timeout(25.0, connect=10.0),
        )

        # State
        self.room_metas: dict[str, dict[str, Any]] = {}
        self.room_messages: dict[str, list[dict[str, Any]]] = {}
        self.last_seq: dict[str, int] = {}
        self.did_index = DidIndex()
        self.kibble_index = KibbleIndex()
        self.tclk_index = TclkIndex()
        self.monitored: set[str] = set(MONITORED_ROOMS)

        # Health
        self.technocore_ok = True
        self.last_success = time.time()

        # Background tasks
        self._tasks: list[asyncio.Task] = []
        self._last_health_snapshot = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        log.info("Starting collector loop (base_url=%s)", self.base_url)

        # 1. Seed Redis from committed JSON so frontend has data immediately
        await self._seed_from_committed()

        # 2. Fetch room metadata
        await self._fetch_rooms()

        # 3. Keep monitored set focused on key protocol rooms only.
        #    Adding top rooms from /rooms causes too many concurrent
        #    long-polls and triggers technocore's rate limiter (429).

        # 4. Seed indices by fetching recent messages from all monitored rooms
        await self._seed_rooms()

        # 5. Initial snapshot + publish
        await self._snapshot_all()

        # 6. Start background tasks
        self._tasks = [
            asyncio.create_task(self._poll_all_rooms(), name="poll-rooms"),
            asyncio.create_task(self._rooms_loop(), name="rooms-loop"),
            asyncio.create_task(self._snapshot_loop(), name="snapshot-loop"),
            asyncio.create_task(self._counts_loop(), name="counts-loop"),
            asyncio.create_task(self._health_loop(), name="health-loop"),
            asyncio.create_task(self._health_snapshot_loop(), name="health-snapshot-loop"),
        ]
        log.info("Collector started — monitoring %d rooms", len(self.monitored))

    async def stop(self) -> None:
        log.info("Stopping collector loop")
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.client.aclose()

    # ------------------------------------------------------------------
    # Seeding
    # ------------------------------------------------------------------

    async def _seed_from_committed(self) -> None:
        """Load committed JSON from data/ into Redis for instant frontend display."""
        data_dir = Path(__file__).resolve().parent.parent / "data"
        for name, key in [
            ("latest.json", "fri:rooms"),
            ("dids.json", "fri:dids"),
            ("kibble.json", "fri:kibble"),
            ("tclk.json", "fri:tclk"),
            ("reputation.json", "fri:reputation"),
        ]:
            path = data_dir / name
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    await self.store.set(key, data)
                    log.info("Seeded %s from %s", key, name)
                except Exception as e:
                    log.warning("Could not seed %s: %s", name, e)

    async def _fetch_rooms(self) -> None:
        """GET /rooms?format=json — room metadata for scoring."""
        try:
            resp = await self.client.get(
                "/rooms",
                params={"format": "json", "limit": ROOMS_LIMIT},
                timeout=httpx.Timeout(60.0, connect=10.0),
            )
            resp.raise_for_status()
            data = resp.json()
            for r in data.get("rooms", []):
                name = r.get("room")
                if name:
                    self.room_metas[name] = r
            self.technocore_ok = True
            self.last_success = time.time()
            log.info("Fetched %d rooms", len(self.room_metas))
        except Exception as e:
            self.technocore_ok = False
            log.warning("fetch_rooms failed: %s", e)

    async def _seed_rooms(self) -> None:
        """Fetch initial messages from all monitored rooms to seed indices."""
        tasks = [self._seed_room(room) for room in self.monitored]
        await asyncio.gather(*tasks, return_exceptions=True)
        log.info(
            "Seeded indices: %d DIDs, %d jobs, %d contracts",
            self.did_index.total_dids,
            self.kibble_index.total_jobs,
            self.tclk_index.total_contracts,
        )

    async def _seed_room(self, room: str) -> None:
        try:
            limit = ROOM_MESSAGE_LIMITS.get(room, 50)
            resp = await self.client.get(
                f"/r/{room}",
                params={"format": "json", "limit": limit},
            )
            resp.raise_for_status()
            data = resp.json()
            messages = data.get("messages", [])
            for msg in messages:
                self._ingest(room, msg)
            if messages:
                self.last_seq[room] = max(m.get("seq", 0) for m in messages)
            self.technocore_ok = True
            self.last_success = time.time()
        except Exception as e:
            log.warning("Failed to seed room %s: %s", room, e)

    # ------------------------------------------------------------------
    # Long-polling
    # ------------------------------------------------------------------

    async def _poll_all_rooms(self) -> None:
        """Start a long-poll loop for each monitored room, staggered."""
        tasks = []
        for room in self.monitored:
            await asyncio.sleep(1.0)  # stagger starts to avoid request bursts
            tasks.append(asyncio.create_task(self._poll_room(room)))
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _poll_room(self, room: str) -> None:
        """Continuously long-poll a single room with wait=10."""
        backoff = 1.0
        while True:
            try:
                since = self.last_seq.get(room, 0)
                resp = await self.client.get(
                    f"/r/{room}",
                    params={"format": "json", "since": since, "wait": 10},
                    timeout=httpx.Timeout(20.0, connect=10.0),
                )
                resp.raise_for_status()
                data = resp.json()
                messages = data.get("messages", [])
                if messages:
                    for msg in messages:
                        self._ingest(room, msg)
                        await self.store.publish(
                            REDIS_CHANNEL,
                            {
                                "type": "feed",
                                "room": room,
                                "seq": msg.get("seq"),
                                "ts": msg.get("ts"),
                                "from": msg.get("from"),
                                "text": msg.get("text"),
                            },
                        )
                    self.last_seq[room] = max(m.get("seq", 0) for m in messages)
                self.technocore_ok = True
                self.last_success = time.time()
                backoff = 1.0
                # Brief pause before re-issue to spread load across rooms
                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.technocore_ok = False
                log.debug("Poll %s failed (retry in %.1fs): %s", room, backoff, e)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    def _ingest(self, room: str, msg: dict[str, Any]) -> None:
        """Feed a message to all indices + update rolling window."""
        self.did_index.ingest_message(room, msg)
        self.kibble_index.ingest_message(room, msg)
        self.tclk_index.ingest_message(room, msg)
        msgs = self.room_messages.get(room, [])
        msgs.append(msg)
        self.room_messages[room] = msgs[-ROOM_MSG_WINDOW:]

    # ------------------------------------------------------------------
    # Periodic loops
    # ------------------------------------------------------------------

    async def _rooms_loop(self) -> None:
        """Every 60s: re-fetch /rooms metadata + re-score rooms."""
        while True:
            await asyncio.sleep(60)
            await self._fetch_rooms()
            await self._snapshot_rooms()

    async def _snapshot_loop(self) -> None:
        """Every 30s: snapshot indices + reputation to Redis."""
        while True:
            await asyncio.sleep(30)
            await self._snapshot_dids()
            await self._snapshot_kibble()
            await self._snapshot_tclk()
            await self._snapshot_reputation()
            await self._snapshot_rooms()

    async def _counts_loop(self) -> None:
        """Every 5s: publish live counter updates."""
        while True:
            await asyncio.sleep(5)
            await self._publish_counts()

    async def _health_loop(self) -> None:
        """Every 10s: publish health status."""
        while True:
            await asyncio.sleep(10)
            await self._publish_health()

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    async def _snapshot_all(self) -> None:
        await self._snapshot_rooms()
        await self._snapshot_dids()
        await self._snapshot_kibble()
        await self._snapshot_tclk()
        await self._snapshot_reputation()
        await self._publish_counts()
        await self._publish_health()

    async def _snapshot_rooms(self) -> None:
        """Score monitored rooms with live data, merge with committed baseline."""
        existing = await self.store.get("fri:rooms") or {"rooms": []}
        rooms_by_name: dict[str, dict[str, Any]] = {
            r["room"]: r for r in existing.get("rooms", [])
        }

        # Update monitored rooms with live scores
        for name in self.monitored:
            meta = self.room_metas.get(name)
            if not meta:
                continue
            messages = self.room_messages.get(name, [])
            rooms_by_name[name] = score_room(meta, messages)

        scored = list(rooms_by_name.values())
        scored.sort(key=lambda x: x.get("score", 0), reverse=True)
        for i, r in enumerate(scored[: TOP_N], 1):
            r["rank"] = i

        snapshot = {
            "version": "1.1",
            "generated_at": _now(),
            "source": self.base_url,
            "protocol_versions": PROTOCOL_VERSIONS,
            "total_rooms_considered": len(scored),
            "rooms": scored[:TOP_N],
        }
        await self.store.set("fri:rooms", snapshot)
        await self.store.publish(REDIS_CHANNEL, {"type": "rooms", **snapshot})

    async def _snapshot_dids(self) -> None:
        snapshot = self.did_index.snapshot(top_limit=500)
        await self.store.set("fri:dids", snapshot)
        await self.store.publish(REDIS_CHANNEL, {"type": "dids", **snapshot})

    async def _snapshot_kibble(self) -> None:
        snapshot = self.kibble_index.snapshot(top_limit=500)
        await self.store.set("fri:kibble", snapshot)
        await self.store.publish(REDIS_CHANNEL, {"type": "kibble", **snapshot})

    async def _snapshot_tclk(self) -> None:
        snapshot = self.tclk_index.snapshot(top_limit=500)
        await self.store.set("fri:tclk", snapshot)
        await self.store.publish(REDIS_CHANNEL, {"type": "tclk", **snapshot})

    async def _snapshot_reputation(self) -> None:
        scorer = ReputationScorer(self.did_index, self.kibble_index, self.tclk_index)
        snapshot = scorer.snapshot(top_limit=500)
        await self.store.set("fri:reputation", snapshot)
        await self.store.publish(REDIS_CHANNEL, {"type": "reputation", **snapshot})

    async def _publish_counts(self) -> None:
        rep = await self.store.get("fri:reputation") or {}
        counts = {
            "total_dids": self.did_index.total_dids,
            "total_rooms": len(self.room_metas),
            "total_jobs": self.kibble_index.total_jobs,
            "total_contracts": self.tclk_index.total_contracts,
            "total_dids_scored": rep.get("total_dids_scored", 0),
        }
        await self.store.set("fri:counts", counts)
        await self.store.publish(REDIS_CHANNEL, {"type": "counts", **counts})

    async def _publish_health(self) -> None:
        stale = not self.technocore_ok or (time.time() - self.last_success > 60)
        health = {
            "status": "degraded" if stale else "ok",
            "stale": stale,
            "technocore_ok": self.technocore_ok,
            "last_success": self.last_success,
            "timestamp": _now(),
        }
        await self.store.set("fri:health", health)
        await self.store.publish(REDIS_CHANNEL, {"type": "health", **health})

    async def _health_snapshot_loop(self) -> None:
        """Every 5 min: write aggregate ecosystem metrics to Redis sorted set."""
        while True:
            await asyncio.sleep(300)
            try:
                await self._write_health_snapshot()
            except Exception as e:
                log.warning("Health snapshot failed: %s", e)

    async def _write_health_snapshot(self) -> None:
        """Compute and store aggregate ecosystem health metrics."""
        now = time.time()
        ts = int(now)

        # Daily active agents: DIDs active in last 24h
        cutoff_24h = now - 86400
        daily_active = 0
        for did_stats in self.did_index._dids.values():
            last = did_stats.get("last_active")
            if last:
                try:
                    from datetime import datetime, timezone
                    dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                    if dt.timestamp() > cutoff_24h:
                        daily_active += 1
                except Exception:
                    pass

        # New DIDs per day: DIDs first seen in last 24h
        new_dids = 0
        for did_stats in self.did_index._dids.values():
            first = did_stats.get("first_seen")
            if first:
                try:
                    from datetime import datetime, timezone
                    dt = datetime.fromisoformat(first.replace("Z", "+00:00"))
                    if dt.timestamp() > cutoff_24h:
                        new_dids += 1
                except Exception:
                    pass

        # TCLK deal volume: count active (non-terminal) contracts
        active_contracts = 0
        for c in self.tclk_index._contracts.values():
            state = c.get("state", "")
            if state not in ("claimed", "refunded", "cancelled"):
                active_contracts += 1

        # Kibble completion rate: accepted / total
        total_jobs = self.kibble_index.total_jobs
        accepted_jobs = 0
        for j in self.kibble_index._jobs.values():
            if j.get("state") in ("accepted", "attested"):
                accepted_jobs += 1
        completion_rate = (accepted_jobs / total_jobs) if total_jobs > 0 else 0

        snapshot = {
            "timestamp": _now(),
            "daily_active_agents": daily_active,
            "new_dids_per_day": new_dids,
            "tclk_deal_volume": active_contracts,
            "kibble_completion_rate": round(completion_rate, 4),
            "total_dids": self.did_index.total_dids,
            "total_rooms": len(self.room_metas),
            "total_jobs": total_jobs,
            "total_contracts": self.tclk_index.total_contracts,
        }

        member = json.dumps(snapshot)
        await self.store.zadd("fri:health:snapshots", float(ts), member)
        # Keep only last 7 days of snapshots (7 * 24 * 12 = 2016 entries at 5min intervals)
        await self.store.zremrangebyscore("fri:health:snapshots", 0, float(now - 604800))
        self._last_health_snapshot = now
        log.info("Health snapshot written: %s", snapshot)
