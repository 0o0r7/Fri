"""Async collector loop — continuous real-time data pipeline.

Replaces the batch `collector/main.py` with a long-running async process that:
1. Long-polls technocore.chat rooms using wait=10 (connection-held)
2. Periodically fetches /rooms for metadata + scoring
3. Feeds messages through existing scoring/indexing modules
4. Snapshots to Redis + fans events out to SSE subscribers
5. Gracefully degrades when technocore is unreachable

Event fan-out defaults to the in-process EventBus (zero Redis commands for
pub/sub); FRI_EVENT_BUS=redis restores the legacy Redis pub/sub mode.
"""

from __future__ import annotations

import asyncio
import json
import os
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from collector.config import (
    ALWAYS_POLL_ROOMS,
    DID_PERSIST_INTERVAL_S,
    DID_PERSIST_PREFIX,
    PROTOCOL_VERSIONS,
    ROOMS_LIMIT,
    ROOM_MESSAGE_LIMITS,
    SEQ_WATERMARK_KEY,
    TOP_N,
    USER_AGENT,
)
from collector.did_index import DidIndex, DidStats, did_note_fingerprint
from collector.kibble import KibbleIndex
from collector.reputation import ReputationScorer
from collector.score import score_room
from collector.tclk import TclkIndex

from .backfill import backfill_loop, parse_watermarks, persist_watermarks
from .eventbus import EventBus
from .registry import registry_loop
from .store import Store

log = logging.getLogger("fri.collector")

REDIS_CHANNEL = "fri:events"


def _env_interval(name: str, default: float) -> float:
    """Read a loop interval (seconds) from the environment.

    Lets hosted deployments tune Redis command volume — e.g. on Upstash's
    free tier (500K commands/month) raise the intervals via env vars
    instead of editing code.
    """
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


# Loop intervals (seconds) — docker defaults; override via env for hosted Redis
COUNTS_INTERVAL_S = _env_interval("FRI_COUNTS_INTERVAL", 5)
HEALTH_INTERVAL_S = _env_interval("FRI_HEALTH_INTERVAL", 10)
SNAPSHOT_INTERVAL_S = _env_interval("FRI_SNAPSHOT_INTERVAL", 30)
ROOMS_INTERVAL_S = _env_interval("FRI_ROOMS_INTERVAL", 60)

# Rooms to long-poll continuously: always-poll set + the events discovery feed
MONITORED_ROOMS: list[str] = list(dict.fromkeys([*ALWAYS_POLL_ROOMS, "events"]))

# Rolling window of messages per room (for live scoring)
ROOM_MSG_WINDOW = 200


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CollectorLoop:
    """Continuous async collector: live data to Redis + SSE event fan-out."""

    def __init__(
        self,
        store: Store,
        base_url: str = "https://technocore.chat",
        event_bus: EventBus | None = None,
    ) -> None:
        self.store = store
        self.base_url = base_url
        # None → legacy Redis pub/sub fan-out (FRI_EVENT_BUS=redis)
        self.event_bus = event_bus
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={"User-Agent": f"{USER_AGENT} (live)"},
            timeout=httpx.Timeout(25.0, connect=10.0),
        )

        # State
        self.room_metas: dict[str, dict[str, Any]] = {}
        self.room_messages: dict[str, list[dict[str, Any]]] = {}
        self.last_seq: dict[str, int] = {}
        # Per-room seq watermarks — the exact-once contract across seed,
        # poll, backfill and boots. Live paths (seed/poll) own the top of
        # each ring (ingest seq > hi); the backfill owns the bottom
        # (ingest seq < lo; for unmonitored rooms also the top). See
        # backend/backfill.py.
        self._seq_lo: dict[str, int | None] = {}
        self._seq_hi: dict[str, int | None] = {}
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

        # 1b. Durable layer: merge the persisted full DID index + per-room
        # seq watermarks BEFORE any live seeding, so the exact-once
        # contract holds across boots (see backend/backfill.py).
        await self._rehydrate_durable()

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
            asyncio.create_task(
                self._health_snapshot_loop(), name="health-snapshot-loop"
            ),
            # Durability layer: full-ring export sweeps, the persistent
            # did-note registry, and write-through index persistence.
            asyncio.create_task(self._persist_loop(), name="did-persist"),
            asyncio.create_task(backfill_loop(self), name="backfill"),
            asyncio.create_task(registry_loop(self), name="did-registry"),
        ]
        log.info(
            "Collector started — monitoring %d rooms "
            "(backfill + registry sweeps running in background)",
            len(self.monitored),
        )

    async def stop(self) -> None:
        log.info("Stopping collector loop")
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.client.aclose()

    # ------------------------------------------------------------------
    # Durable persistence — "no DID is forgotten"
    # ------------------------------------------------------------------

    async def _rehydrate_durable(self) -> None:
        """Merge the persisted full DID index + seq watermarks from the store.

        Restarts and free-tier spin-downs used to reset the live index to
        the top-500 committed baseline, forgetting every other DID the
        process had ever observed. The write-through store keys
        (fri:d:<fingerprint>) are the durable truth: re-merged at boot
        with max-merge semantics (see DidIndex.hydrate_entry), then live
        ingest continues on top.

        Self-healing: if the store holds watermarks but ZERO did entries
        (provider data loss / manual flush), the watermarks are dropped —
        re-ingesting retained messages is the correct recovery there;
        honoring them would strand the counters at zero forever.
        """
        # Watermarks first — seeding and polling must respect them.
        try:
            wm = parse_watermarks(await self.store.get(SEQ_WATERMARK_KEY))
        except Exception:
            wm = {}
        for room, marks in wm.items():
            self._seq_lo[room] = marks["lo"]
            self._seq_hi[room] = marks["hi"]

        loaded = 0
        try:
            keys = await self.store.scan_keys(f"{DID_PERSIST_PREFIX}*")
            if keys:
                values = await self.store.mget_raw(keys)
                for raw in values:
                    if not raw:
                        continue
                    try:
                        entry = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(entry, dict):
                        if self.did_index.hydrate_entry(entry):
                            loaded += 1
        except Exception as e:
            log.warning("durable did rehydrate failed: %s", e)

        if loaded == 0 and wm:
            log.warning(
                "durable did store empty but %d watermarks present — "
                "assuming provider data loss, resetting watermarks",
                len(wm),
            )
            self._seq_lo.clear()
            self._seq_hi.clear()

        log.info(
            "Durable rehydration: %d did entries merged, "
            "%d room watermarks restored",
            loaded,
            len(wm) if loaded else 0,
        )

    @staticmethod
    def _durable_entry(stats: DidStats) -> dict[str, Any]:
        """Compact store shape for one DID (published view minus derived).

        Identity-only DIDs (zero observed messages) persist a slim entry:
        the zero counters and empty rooms map carry no information, and
        with tens of thousands of registry entries every saved byte is
        store headroom (eviction is the failure mode being defended
        against). hydrate_entry treats missing fields as defaults, so the
        slim shape round-trips losslessly.
        """
        if stats.messages_signed == 0 and not stats.rooms and stats.identity_note:
            return {
                "did": stats.did,
                "first_seen": stats.first_seen,
                "profile_bio": stats.profile_bio,
                "identity_note": True,
            }
        return {
            "did": stats.did,
            "messages_signed": stats.messages_signed,
            "first_seen": stats.first_seen,
            "last_active": stats.last_active,
            "rooms_breakdown": dict(stats.rooms),
            "total_text_chars": stats.total_text_chars,
            "phrase_msgs": stats.phrase_msgs,
            "template_msgs": stats.template_msgs,
            "campaign_msgs": stats.campaign_msgs,
            "profile_bio": stats.profile_bio,
            "identity_note": stats.identity_note,
        }

    async def _persist_loop(self) -> None:
        """Write dirty DIDs + seq watermarks to the store every cycle.

        The store (Aiven Valkey) does not spin down — it is the durability
        anchor that lets the Render service restart without forgetting.
        """
        while True:
            await asyncio.sleep(DID_PERSIST_INTERVAL_S)
            try:
                await self._flush_did_persistence()
            except Exception as e:
                log.warning("did persist cycle failed: %s", e)

    async def _flush_did_persistence(self) -> None:
        dirty = self.did_index.pop_dirty()
        if dirty:
            mapping: dict[str, str] = {}
            for did in dirty:
                stats = self.did_index.get(did)
                if stats is None:
                    continue
                fp = did_note_fingerprint(did)
                mapping[f"{DID_PERSIST_PREFIX}{fp}"] = json.dumps(
                    self._durable_entry(stats), separators=(",", ":")
                )
            try:
                if mapping:
                    await self.store.mset_raw(mapping)
            except Exception:
                # pop_dirty() already cleared the set — re-queue so the
                # next cycle retries instead of silently losing writes.
                self.did_index.mark_dirty_many(dirty)
                raise
        await persist_watermarks(self)

    # ------------------------------------------------------------------
    # Seeding
    # ------------------------------------------------------------------

    async def _seed_from_committed(self, data_dir: str | Path | None = None) -> None:
        """Load committed JSON from data/ into Redis for instant frontend display.

        Also hydrates the in-memory indices (dids/kibble/tclk) from the same
        files — one read per file, two uses. Without hydration the live index
        boots empty: counts collapse to whatever the 11 seeded rooms saw
        recently, daily_active/new_dids health metrics read ~total_dids
        (everything looks brand-new), and reputation loses all deal history
        until the firehose refills it. Hydrating from the committed batch
        baseline costs zero extra technocore requests.

        Overlap note: messages present in BOTH the committed baseline and the
        live seed window are counted twice (the batch JSON publishes no
        per-message seq to dedup against). Boots are rare and the inflation
        is bounded by one seed window — accepted in exchange for continuity.
        Replay guards in ingest_message (first offer/poster wins, accept
        skipped when one exists) keep re-ingested frames from duplicating
        hydrated contracts/jobs.
        """
        data_dir = Path(data_dir) if data_dir else (
            Path(__file__).resolve().parent.parent / "data"
        )
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
                    if key == "fri:dids":
                        log.info(
                            "Hydrated did index: %d DIDs from %s",
                            self.did_index.hydrate(data), name,
                        )
                    elif key == "fri:kibble":
                        log.info(
                            "Hydrated kibble index: %d jobs from %s",
                            self.kibble_index.hydrate(data), name,
                        )
                    elif key == "fri:tclk":
                        log.info(
                            "Hydrated tclk index: %d contracts from %s",
                            self.tclk_index.hydrate(data), name,
                        )
                    log.info("Seeded %s from %s", key, name)
                except Exception as e:
                    log.warning("Could not seed %s: %s", name, e)
        log.info(
            "Committed-baseline hydration complete: %d DIDs, %d kibble jobs, "
            "%d TCLK contracts restored from %s",
            self.did_index.total_dids,
            self.kibble_index.total_jobs,
            self.tclk_index.total_contracts,
            data_dir,
        )

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
                seqs = [m.get("seq", 0) for m in messages]
                self.last_seq[room] = max(seqs)
                # Fresh discovery (no watermark yet): the whole returned
                # tail was ingested — record its bottom so the backfill
                # sweep stops strictly below it.
                if self._seq_lo.get(room) is None:
                    self._seq_lo[room] = min(seqs)
                    self._seq_hi[room] = max(seqs)
            self.technocore_ok = True
            self.last_success = time.time()
        except Exception as e:
            log.warning("Failed to seed room %s: %s", room, e)

    # ------------------------------------------------------------------
    # Event fan-out
    # ------------------------------------------------------------------

    async def _emit(self, event: dict[str, Any]) -> None:
        """Fan an event out to SSE subscribers.

        Default (event_bus present, FRI_EVENT_BUS=memory): in-process bus —
        zero Redis commands, and delivery cannot fail on a Redis error (a
        failed publish here used to abort the poll loop before last_seq was
        updated, re-fetching and re-ingesting the same messages).
        event_bus=None (FRI_EVENT_BUS=redis): legacy Redis pub/sub, kept for
        multi-process deployments.
        """
        if self.event_bus is not None:
            await self.event_bus.publish(event)
        else:
            await self.store.publish(REDIS_CHANNEL, event)

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
                        try:
                            await self._emit(
                                {
                                    "type": "feed",
                                    "room": room,
                                    "seq": msg.get("seq"),
                                    "ts": msg.get("ts"),
                                    "from": msg.get("from"),
                                    "text": msg.get("text"),
                                },
                            )
                        except Exception as e:
                            # Fan-out must never gate ingest sequencing: a
                            # failed PUBLISH (redis mode, provider outage)
                            # used to abort the loop before last_seq advanced,
                            # so the same window was re-fetched and
                            # re-ingested (counter inflation) until Redis
                            # recovered. Memory mode cannot fail; degrade
                            # the SSE feed instead, keep counters exact.
                            log.debug("Emit failed (ingest continues): %s", e)
                    seqs = [m.get("seq", 0) for m in messages]
                    self.last_seq[room] = max(seqs)
                    # Maintain the live-path watermark (fresh discovery
                    # records the bottom of the first window; incremental
                    # polls only raise the top).
                    if self._seq_lo.get(room) is None:
                        self._seq_lo[room] = min(seqs)
                        self._seq_hi[room] = max(seqs)
                    else:
                        hi_old = self._seq_hi.get(room)
                        self._seq_hi[room] = max(
                            hi_old if hi_old is not None else 0, max(seqs)
                        )
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

    def _ingest(
        self,
        room: str,
        msg: dict[str, Any],
        source: str = "live",
        window: bool = True,
    ) -> None:
        """Feed a message to all indices (+ optional live rolling window).

        Exact-once contract: live paths (seed/poll) ingest only seq above
        the room's high-water mark; the backfill (source="backfill") does
        its own below-the-floor check in ingest_ring. Messages without a
        seq (anonymous posts) cannot be deduped and pass through — they
        carry no per-DID counters.
        """
        seq = msg.get("seq")
        if seq is not None:
            try:
                seq = int(seq)
            except (TypeError, ValueError):
                seq = None
        if source == "live" and seq is not None:
            hi = self._seq_hi.get(room)
            if hi is not None and seq <= hi:
                return  # already counted (seed overlap / redelivery)
        self.did_index.ingest_message(room, msg)
        self.kibble_index.ingest_message(room, msg)
        self.tclk_index.ingest_message(room, msg)
        if window:
            msgs = self.room_messages.get(room, [])
            msgs.append(msg)
            self.room_messages[room] = msgs[-ROOM_MSG_WINDOW:]

    # ------------------------------------------------------------------
    # Periodic loops
    # ------------------------------------------------------------------

    async def _rooms_loop(self) -> None:
        """Every ROOMS_INTERVAL_S: re-fetch /rooms metadata + re-score rooms."""
        while True:
            await asyncio.sleep(ROOMS_INTERVAL_S)
            await self._fetch_rooms()
            await self._snapshot_rooms()

    async def _snapshot_loop(self) -> None:
        """Every SNAPSHOT_INTERVAL_S: snapshot indices + reputation to Redis."""
        while True:
            await asyncio.sleep(SNAPSHOT_INTERVAL_S)
            await self._snapshot_dids()
            await self._snapshot_kibble()
            await self._snapshot_tclk()
            await self._snapshot_reputation()
            await self._snapshot_rooms()

    async def _counts_loop(self) -> None:
        """Every COUNTS_INTERVAL_S: publish live counter updates."""
        while True:
            await asyncio.sleep(COUNTS_INTERVAL_S)
            await self._publish_counts()

    async def _health_loop(self) -> None:
        """Every HEALTH_INTERVAL_S: publish health status."""
        while True:
            await asyncio.sleep(HEALTH_INTERVAL_S)
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
        await self._emit({"type": "rooms", **snapshot})

    async def _snapshot_dids(self) -> None:
        snapshot = self.did_index.snapshot(top_limit=500)
        await self.store.set("fri:dids", snapshot)
        await self._emit({"type": "dids", **snapshot})

    async def _snapshot_kibble(self) -> None:
        snapshot = self.kibble_index.snapshot(top_limit=500)
        await self.store.set("fri:kibble", snapshot)
        await self._emit({"type": "kibble", **snapshot})

    async def _snapshot_tclk(self) -> None:
        snapshot = self.tclk_index.snapshot(top_limit=500)
        await self.store.set("fri:tclk", snapshot)
        await self._emit({"type": "tclk", **snapshot})

    async def _snapshot_reputation(self) -> None:
        scorer = ReputationScorer(self.did_index, self.kibble_index, self.tclk_index)
        snapshot = scorer.snapshot(top_limit=500)
        await self.store.set("fri:reputation", snapshot)
        await self._emit({"type": "reputation", **snapshot})

    async def _publish_counts(self) -> None:
        rep = await self.store.get("fri:reputation") or {}
        spam = rep.get("spam") or {}
        counts = {
            "total_dids": self.did_index.total_dids,
            "total_rooms": len(self.room_metas),
            "total_jobs": self.kibble_index.total_jobs,
            "total_contracts": self.tclk_index.total_contracts,
            "total_dids_scored": rep.get("total_dids_scored", 0),
            # Audit P0 (window metadata): raw counters travel with the
            # window they observe, so a flood-inflated live number is
            # distinguishable from the committed batch baseline. The
            # flagged count makes spam visibility symmetric — raw counts
            # include flagged DIDs, /api/reputation scoring excludes them.
            "flagged_dids": spam.get("flagged_dids", 0),
            "window": {
                **self.did_index.observation_window(),
                "monitored_rooms": sorted(self.monitored),
                "scored_count": rep.get("total_dids_scored", 0),
            },
        }
        await self.store.set("fri:counts", counts)
        await self._emit({"type": "counts", **counts})

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
        await self._emit({"type": "health", **health})

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

        # Daily active agents: DIDs active in last 24h.
        # NOTE: did_index._dids holds DidStats dataclass instances — attribute
        # access only. (A .get() call here raised AttributeError, which the
        # loop's try/except swallowed: this snapshot never wrote in prod.)
        cutoff_24h = now - 86400
        daily_active = 0
        for did_stats in self.did_index._dids.values():
            last = did_stats.last_active
            if last:
                try:
                    dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                    if dt.timestamp() > cutoff_24h:
                        daily_active += 1
                except Exception:
                    pass

        # New DIDs per day: DIDs first seen in last 24h
        new_dids = 0
        for did_stats in self.did_index._dids.values():
            first = did_stats.first_seen
            if first:
                try:
                    dt = datetime.fromisoformat(first.replace("Z", "+00:00"))
                    if dt.timestamp() > cutoff_24h:
                        new_dids += 1
                except Exception:
                    pass

        # TCLK deal volume: count active (non-terminal) contracts
        active_contracts = 0
        for c in self.tclk_index._contracts.values():
            # c is a TclkContract dataclass; .state is a derived property.
            # Terminal set == TCLK SPEC §3.5 receipt outcomes (KNOWN_OUTCOMES).
            state = c.state
            if state not in ("claimed", "refunded", "cancelled"):
                active_contracts += 1

        # Kibble completion rate: accepted / total
        total_jobs = self.kibble_index.total_jobs
        accepted_jobs = 0
        for j in self.kibble_index._jobs.values():
            # j is a KibbleJob dataclass; .state is a derived property.
            if j.state in ("accepted", "attested"):
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
