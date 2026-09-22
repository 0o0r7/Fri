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
    KEEP_ACTIVE,
    KEEP_JUNK,
    KEEP_KNOWN,
    KEEP_REGISTRY,
    PRUNE_INTERVAL_S,
    PROTOCOL_VERSIONS,
    REHYDRATE_DELAY_S,
    REHYDRATE_PACE_S,
    ROOMS_LIMIT,
    ROOM_MESSAGE_LIMITS,
    ROOMS_TIMEOUT_S,
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
from .registry import (
    REGISTRY_JUNK_KEY,
    REGISTRY_KNOWN_KEY,
    REGISTRY_PRIORITY_KEY,
    registry_loop,
)
from .store import Store

log = logging.getLogger("fri.collector")

REDIS_CHANNEL = "fri:events"

# Zset eviction indexes for the durable per-DID store (free-tier caps).
# member = fingerprint, score = recency epoch — the prune loop evicts the
# lowest-scored tail without ever scanning the values themselves.
IDX_ACTIVE_KEY = "fri:idx:active"
IDX_REG_KEY = "fri:idx:reg"


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
        self._boot_ts = time.time()

        # Background tasks
        self._tasks: list[asyncio.Task] = []
        self._last_health_snapshot = 0.0
        # Free-tier hardening (2026-09-22): loop-crash counters (health
        # liveness), prune statistics, and fingerprints that must never
        # be evicted from the durable store (operator-pinned DIDs).
        self._loop_failures: dict[str, int] = {}
        self.prune_stats: dict[str, Any] = {}
        self._protected_fps: set[str] = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._tasks and any(not t.done() for t in self._tasks):
            log.warning("collector.start() called on a live collector — ignoring")
            return
        log.info("Starting collector loop (base_url=%s)", self.base_url)

        # Boot steps 1-5 are individually guarded: a failure (Redis at its
        # plan ceiling, technocore hanging, anything) must NEVER raise out
        # of start() — the old raise-into-_retry_collector_start pattern
        # turned every boot into a CPU-burning retry storm that wedged the
        # F1 worker. Degraded beats dead: the HTTP service stays up and
        # the background loops below ALWAYS spawn.
        await self._guard("seed-from-committed", self._seed_from_committed)

        # 1b. Durable layer: room watermarks FIRST — a single fast GET that
        # polling must respect before any live seeding. The heavy per-DID
        # SCAN+MGET (250k+ fri:d: keys on Aiven, minutes of round-trips)
        # runs as a background task: awaiting it on the boot path blows
        # App Service's ~230s startup probe and crash-loops the container.
        try:
            wm = parse_watermarks(await self.store.get(SEQ_WATERMARK_KEY))
        except Exception:
            wm = {}
        for room, marks in wm.items():
            self._seq_lo[room] = marks["lo"]
            self._seq_hi[room] = marks["hi"]
        self._rehydrate_task = asyncio.create_task(
            self._rehydrate_did_entries(wm, delay_s=REHYDRATE_DELAY_S),
            name="durable-rehydrate",
        )

        # 2. Fetch room metadata
        await self._guard("fetch-rooms", self._fetch_rooms)

        # 3. Keep monitored set focused on key protocol rooms only.
        #    Adding top rooms from /rooms causes too many concurrent
        #    long-polls and triggers technocore's rate limiter (429).

        # 4. Seed indices by fetching recent messages from all monitored rooms
        await self._guard("seed-rooms", self._seed_rooms)

        # 5. Initial snapshot + publish
        await self._guard("snapshot-all", self._snapshot_all)

        # 6. Start background tasks — supervised: a crashed loop restarts
        # with backoff instead of silently dying (a dead health loop was
        # half of the frozen-payload lie).
        self._tasks = [
            self._spawn("poll-rooms", self._poll_all_rooms),
            self._spawn("rooms-loop", self._rooms_loop),
            self._spawn("snapshot-loop", self._snapshot_loop),
            self._spawn("counts-loop", self._counts_loop),
            self._spawn("health-loop", self._health_loop),
            self._spawn("health-snapshot-loop", self._health_snapshot_loop),
            # Durability layer: full-ring export sweeps, the persistent
            # did-note registry, write-through index persistence, and the
            # free-tier prune cycle.
            self._spawn("did-persist", self._persist_loop),
            self._spawn("prune", self._prune_loop),
            self._spawn("backfill", lambda: backfill_loop(self)),
            self._spawn("did-registry", lambda: registry_loop(self)),
        ]
        log.info(
            "Collector started — monitoring %d rooms "
            "(backfill + registry + prune sweeps running in background)",
            len(self.monitored),
        )

    async def _guard(self, step: str, coro_fn) -> None:
        """Run one boot step; a failure degrades instead of killing start()."""
        try:
            await coro_fn()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.technocore_ok = False
            log.error(
                "boot step %s failed (%s: %s) — continuing degraded",
                step,
                type(e).__name__,
                e,
            )

    def _spawn(self, name: str, factory) -> asyncio.Task:
        """Supervise a background loop: restart on unexpected death.

        CancelledError propagates (shutdown path). Restart backoff keeps a
        crash-looping task from becoming a CPU storm.
        """

        async def supervised() -> None:
            backoff = 5.0
            while True:
                try:
                    await factory()
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self._loop_failures[name] = self._loop_failures.get(name, 0) + 1
                    log.error(
                        "loop %s crashed (%s: %s) — restarting in %.0fs",
                        name,
                        type(e).__name__,
                        e,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 300.0)

        return asyncio.create_task(supervised(), name=name)

    async def stop(self) -> None:
        log.info("Stopping collector loop")
        rt = getattr(self, "_rehydrate_task", None)
        if rt and not rt.done():
            rt.cancel()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.client.aclose()

    # ------------------------------------------------------------------
    # Durable persistence — "no DID is forgotten"
    # ------------------------------------------------------------------

    async def _rehydrate_did_entries(
        self, wm: dict[str, Any], delay_s: float = 0.0
    ) -> None:
        """Merge the persisted full DID index from per-DID store keys — capped.

        Restarts and free-tier spin-downs used to reset the live index to
        the top-500 committed baseline; the write-through store keys
        (fri:d:<fingerprint>) are the durable truth re-merged at boot.

        Free-tier hardening (2026-09-22): the store once held 600k+
        fri:d:* entries (~10x the Aiven free-1 ceiling), which is exactly
        what pushed writes into OOM failure. This pass therefore keeps
        only the survivors — top KEEP_ACTIVE by message volume, the
        newest KEEP_REGISTRY identities, plus operator-pinned fps —
        DELETES the rest, and zset-indexes the kept entries
        (fri:idx:active / fri:idx:reg) so the prune loop can maintain the
        caps afterwards. On a right-sized store this is a plain hydrate
        (everything is kept). Runs as a background task: at scale the
        sweep takes minutes and must not block uvicorn's lifespan.

        Self-healing: if the store holds watermarks but ZERO did entries
        (provider data loss / manual flush), the watermarks are dropped —
        re-ingesting retained messages is the correct recovery there.
        """
        loaded = 0
        # Boot grace (F1 throttle protection): let /api/health and the cheap
        # loops answer before the heavy sweep touches the store.
        if delay_s > 0:
            await asyncio.sleep(delay_s)
        try:
            await self._load_protected_fps()
            keys = await self.store.scan_keys(f"{DID_PERSIST_PREFIX}*", chunk=2000)
            if keys:
                loaded = await self._rehydrate_indexed(keys)
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

    async def _load_protected_fps(self) -> None:
        """Operator-pinned fingerprints must survive every prune pass."""
        self._protected_fps = set()
        try:
            self._protected_fps = set(
                await self.store.smembers(REGISTRY_PRIORITY_KEY)
            )
        except Exception as e:
            log.warning("priority fps unavailable (%s) — prune skips pin protection", e)

    @staticmethod
    def _ts_epoch(ts: str | None) -> float:
        """Epoch seconds of an ISO-Z timestamp; 0.0 when unparseable."""
        if ts:
            try:
                return datetime.fromisoformat(
                    str(ts).replace("Z", "+00:00")
                ).timestamp()
            except (ValueError, TypeError, OSError):
                pass
        return 0.0

    def _recency_score(self, stats: DidStats) -> float:
        """Zset score for eviction order: active by last_active, else now."""
        return (
            self._ts_epoch(stats.last_active)
            or self._ts_epoch(stats.first_seen)
            or time.time()
        )

    async def _rehydrate_indexed(self, keys: list[str]) -> int:
        """Classify + select + hydrate + index the durable entries.

        Pass 1 streams every value once (classify only): active DIDs
        compete for KEEP_ACTIVE slots by message volume (min-heap), the
        first KEEP_REGISTRY identities encountered are kept, everything
        else is queued for deletion. Pass 2 re-fetches and hydrates the
        surviving active entries, indexes all survivors, and deletes the
        losers — the one-time recovery that pulls an oversized store back
        under its ceiling.
        """
        import heapq

        loaded = 0
        kept_reg = 0
        reg_pairs: list[tuple[float, str]] = []
        active_heap: list[tuple[int, str, str]] = []  # (messages, fp, key)
        delete_keys: list[str] = []

        for i in range(0, len(keys), 500):
            chunk = keys[i : i + 500]
            values = await self.store.mget_raw(chunk)
            for key, raw in zip(chunk, values):
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                fp = key[len(DID_PERSIST_PREFIX) :]
                if fp in self._protected_fps:
                    if self.did_index.hydrate_entry(entry):
                        loaded += 1
                    reg_pairs.append(
                        (self._ts_epoch(entry.get("first_seen")) or time.time(), fp)
                    )
                    continue
                try:
                    signed = int(entry.get("messages_signed") or 0)
                except (TypeError, ValueError):
                    signed = 0
                if signed > 0:
                    heapq.heappush(active_heap, (signed, fp, key))
                    if len(active_heap) > KEEP_ACTIVE:
                        _, _, dropped_key = heapq.heappop(active_heap)
                        delete_keys.append(dropped_key)
                else:
                    if kept_reg < KEEP_REGISTRY:
                        kept_reg += 1
                        if self.did_index.hydrate_entry(entry):
                            loaded += 1
                        reg_pairs.append(
                            (
                                self._ts_epoch(entry.get("first_seen"))
                                or time.time(),
                                fp,
                            )
                        )
                    else:
                        delete_keys.append(key)
            # F1 shared-CPU pacing: the old full-speed sweep tripped the
            # App Service resource governor mid-boot and the generation
            # died before the one-time recovery could converge.
            if REHYDRATE_PACE_S > 0:
                await asyncio.sleep(REHYDRATE_PACE_S)

        # Pass 2 — hydrate the surviving ACTIVE entries (heap finalized).
        active_pairs: list[tuple[float, str]] = []
        kept_active_keys = [t[2] for t in active_heap]
        for i in range(0, len(kept_active_keys), 500):
            chunk = kept_active_keys[i : i + 500]
            values = await self.store.mget_raw(chunk)
            for key, raw in zip(chunk, values):
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                if self.did_index.hydrate_entry(entry):
                    loaded += 1
                fp = key[len(DID_PERSIST_PREFIX) :]
                active_pairs.append(
                    (
                        self._ts_epoch(entry.get("last_active"))
                        or self._ts_epoch(entry.get("first_seen"))
                        or time.time(),
                        fp,
                    )
                )
            if REHYDRATE_PACE_S > 0:
                await asyncio.sleep(REHYDRATE_PACE_S)

        # Index the survivors, delete the losers (frees ceiling pressure).
        try:
            if active_pairs:
                await self.store.zadd_multi(IDX_ACTIVE_KEY, active_pairs)
            if reg_pairs:
                await self.store.zadd_multi(IDX_REG_KEY, reg_pairs)
        except Exception as e:
            log.warning("durable idx build failed (prune loop will retry): %s", e)
        if delete_keys:
            # Sliced + paced deletes: one huge pipeline batch against an
            # oversized store stalls both the Valkey server thread and the
            # event loop; slices keep the blast radius small.
            deleted = 0
            for i in range(0, len(delete_keys), 5000):
                try:
                    deleted += await self.store.delete(
                        delete_keys[i : i + 5000]
                    )
                except Exception as e:
                    log.warning("recovery prune delete slice failed: %s", e)
                if REHYDRATE_PACE_S > 0:
                    await asyncio.sleep(REHYDRATE_PACE_S)
            log.warning(
                "recovery prune: %d/%d oversized durable entries deleted "
                "(caps: active=%d reg=%d)",
                deleted,
                len(delete_keys),
                KEEP_ACTIVE,
                KEEP_REGISTRY,
            )
        return loaded

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
            active_pairs: list[tuple[float, str]] = []
            reg_pairs: list[tuple[float, str]] = []
            for did in dirty:
                stats = self.did_index.get(did)
                if stats is None:
                    continue
                fp = did_note_fingerprint(did)
                mapping[f"{DID_PERSIST_PREFIX}{fp}"] = json.dumps(
                    self._durable_entry(stats), separators=(",", ":")
                )
                # Eviction-index upkeep: one pipeline ZADD per flush cycle,
                # so the prune loop never has to scan values to enforce the
                # free-tier caps.
                if stats.messages_signed > 0:
                    active_pairs.append((self._recency_score(stats), fp))
                else:
                    reg_pairs.append(
                        (self._ts_epoch(stats.first_seen) or time.time(), fp)
                    )
            try:
                if mapping:
                    await self.store.mset_raw(mapping)
                    if active_pairs:
                        await self.store.zadd_multi(IDX_ACTIVE_KEY, active_pairs)
                    if reg_pairs:
                        await self.store.zadd_multi(IDX_REG_KEY, reg_pairs)
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
        """GET /rooms?format=json — room metadata for scoring.

        Upstream hang regression (2026-09-21): /rooms?limit=N HANGS for
        most N (limit=1 ok, no-limit ok in ~0.04s, limit=20 slow-200,
        limit=150/50/100/2/3/5/10 hang). The limited fetch gets a bounded
        timeout, then falls back to the no-limit form; on total failure
        the previously cached metas are kept (blanking them would zero
        room scoring until the next successful fetch).
        """
        for attempt, params in enumerate(
            ({"format": "json", "limit": ROOMS_LIMIT}, {"format": "json"})
        ):
            try:
                resp = await self.client.get(
                    "/rooms",
                    params=params,
                    timeout=httpx.Timeout(ROOMS_TIMEOUT_S, connect=10.0),
                )
                resp.raise_for_status()
                data = resp.json()
                rooms = data.get("rooms", [])
                if not rooms and attempt == 0:
                    log.warning(
                        "fetch_rooms(limit=%s) returned 0 rooms — trying "
                        "no-limit fallback",
                        ROOMS_LIMIT,
                    )
                    continue
                for r in rooms:
                    name = r.get("room")
                    if name:
                        self.room_metas[name] = r
                self.technocore_ok = True
                self.last_success = time.time()
                log.info("Fetched %d rooms (limit=%s)", len(rooms), params.get("limit"))
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if attempt == 0:
                    log.warning(
                        "fetch_rooms(limit=%s) failed (%s) — trying no-limit "
                        "fallback",
                        ROOMS_LIMIT,
                        e,
                    )
                else:
                    self.technocore_ok = False
                    log.warning(
                        "fetch_rooms fallback failed too: %s — keeping %d "
                        "cached metas",
                        e,
                        len(self.room_metas),
                    )

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
    # Free-tier prune — keep the store under its plan ceiling
    # ------------------------------------------------------------------

    async def _prune_loop(self) -> None:
        """Every PRUNE_INTERVAL_S: enforce the durable-store caps.

        The Aiven free-1 ceiling (~30 MB) is what the Sep 21-22 wedge was
        made of: writes failed OOM, snapshots raised, the retry storm
        burned F1. This loop keeps the store right-sized BY POLICY.
        """
        while True:
            await asyncio.sleep(PRUNE_INTERVAL_S)
            try:
                await self._prune_once()
            except Exception as e:
                log.warning("prune cycle failed: %s", e)

    async def _prune_once(self) -> dict[str, Any]:
        """One cap-enforcement pass. Never raises (loop-safe).

        - fri:d:<fp> entries: evict the lowest-recency tail via the
          fri:idx:* zsets (no value scans), protecting operator pins.
        - fri:reg:known / fri:reg:junk: SPOP-trim; the only cost of
          trimming is polite re-fetch churn on a later sweep.
        """
        stats: dict[str, Any] = {
            "active_evicted": 0,
            "reg_evicted": 0,
            "known_trimmed": 0,
            "junk_trimmed": 0,
            "dbsize": None,
        }
        try:
            stats["dbsize"] = await self.store.dbsize()
        except Exception:
            pass

        for idx_key, cap, kind in (
            (IDX_ACTIVE_KEY, KEEP_ACTIVE, "active"),
            (IDX_REG_KEY, KEEP_REGISTRY, "reg"),
        ):
            try:
                size = await self.store.zcard(idx_key)
                excess = size - cap
                if excess > 0:
                    # Candidate window = excess + pinned fps: protected
                    # members must not consume cap slots, so the window
                    # reaches past them and `excess` NON-protected members
                    # are evicted (exact convergence, pins never touched).
                    window = min(excess + len(self._protected_fps), 50_000)
                    members = await self.store.zrange(idx_key, 0, window - 1)
                    candidates = [
                        m for m in members if m not in self._protected_fps
                    ][:excess]
                    if candidates:
                        await self.store.delete(
                            [f"{DID_PERSIST_PREFIX}{m}" for m in candidates]
                        )
                        await self.store.zrem(idx_key, candidates)
                        stats[f"{kind}_evicted"] = len(candidates)
            except Exception as e:
                log.warning("prune %s failed: %s", kind, e)

        for set_key, cap, stat_name in (
            (REGISTRY_KNOWN_KEY, KEEP_KNOWN, "known_trimmed"),
            (REGISTRY_JUNK_KEY, KEEP_JUNK, "junk_trimmed"),
        ):
            try:
                size = await self.store.scard(set_key)
                excess = size - cap
                if excess > 0:
                    popped = await self.store.spop(set_key, min(excess, 50_000))
                    stats[stat_name] = len(popped)
            except Exception as e:
                log.warning("prune %s failed: %s", set_key, e)

        stats["at"] = _now()
        self.prune_stats = stats
        if any(
            stats[k]
            for k in (
                "active_evicted",
                "reg_evicted",
                "known_trimmed",
                "junk_trimmed",
            )
        ):
            log.info("prune cycle: %s", stats)
        return stats

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
            # Process-local liveness (2026-09-22): a frozen Redis payload
            # answering "ok" while every loop is dead is exactly how the
            # Sep 21 wedge stayed invisible. These fields are verifiable.
            "uptime_s": int(time.time() - self._boot_ts),
            "loops": {t.get_name(): (not t.done()) for t in self._tasks},
            "loop_failures": dict(self._loop_failures),
            "dids_tracked": self.did_index.total_dids,
            "registry_only_tracked": self.did_index.registry_only_count(),
            "prune": self.prune_stats or None,
        }
        stats_fn = getattr(self.store, "stats", None)
        if callable(stats_fn):
            health.update(stats_fn())  # store_errors — the OOM signal
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
