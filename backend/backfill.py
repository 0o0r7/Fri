"""Full-history backfill — GET /r/<room>/export ring ingestion.

FRI used to be a rolling-window oracle: only the last N messages of a
handful of monitored rooms were ever observed, so any DID whose activity
fell outside that tail was invisible — and under flood traffic the
technocore ring buffer (~10 MiB per room) churns in HOURS, which made
even the recent past evaporate. This module turns FRI into a cumulative
oracle:

    one export request per room returns the WHOLE retained ring as raw
    JSONL (seq-ordered, byte-exact); every record is fed through the
    same ingest pipeline as live polling, guarded by per-room seq
    watermarks so a message is counted exactly once across seeds, polls
    and sweeps, boots and restarts.

Watermark contract (shared with CollectorLoop — see collector.py):

    _seq_lo[room]  min seq ingested by ANY path (live or backfill)
    _seq_hi[room]  max seq ingested by ANY path

    live paths (seed + poll) own the TOP of the ring: they ingest
    seq > hi and raise hi;
    backfill owns the BOTTOM: for monitored rooms it ingests only
    seq < lo (strictly below everything live ever ingested) and lowers
    lo. For UNMONITORED rooms there is no poll loop, so backfill also
    owns the top (seq > hi, raising hi) to pick up new messages between
    sweeps.

Both checks run between awaits in single-threaded asyncio, so the
check-then-ingest step is race-free against the poll loops.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx

from collector.config import (
    ALWAYS_POLL_ROOMS,
    BACKFILL_INTERVAL_S,
    BACKFILL_ROOMS_LIMIT,
    BACKFILL_ROOM_DELAY_S,
    BACKFILL_TIMEOUT_S,
    ROOM_DENYLIST,
    SEQ_WATERMARK_KEY,
)

log = logging.getLogger("fri.backfill")


def parse_watermarks(payload: dict[str, Any] | None) -> dict[str, dict[str, int]]:
    """Validate a persisted watermark payload ({room: {lo, hi}})."""
    out: dict[str, dict[str, int]] = {}
    if not isinstance(payload, dict):
        return out
    for room, wm in payload.items():
        if not isinstance(room, str) or not isinstance(wm, dict):
            continue
        try:
            lo = int(wm.get("lo"))
            hi = int(wm.get("hi"))
        except (TypeError, ValueError):
            continue
        if lo > hi:
            continue
        out[room] = {"lo": lo, "hi": hi}
    return out


def select_rooms(room_metas: dict[str, dict[str, Any]]) -> list[str]:
    """Always-poll rooms + the most active non-machine boards.

    mb-* boards are per-machine template-spam factories — exporting all
    of them would burn hours of sweep time for zero reputation signal.
    Everything else is ranked by the server's window size (recent
    message volume) and capped at BACKFILL_ROOMS_LIMIT.
    """
    rooms = list(ALWAYS_POLL_ROOMS)
    seen = set(rooms)
    candidates: list[tuple[int, str]] = []
    for name, meta in room_metas.items():
        if name in seen or name in ROOM_DENYLIST or name.startswith("mb-"):
            continue
        try:
            window = int(meta.get("window") or meta.get("messages") or 0)
        except (TypeError, ValueError):
            window = 0
        candidates.append((-window, name))
    candidates.sort()
    for _, name in candidates:
        if len(rooms) >= BACKFILL_ROOMS_LIMIT + len(ALWAYS_POLL_ROOMS):
            break
        rooms.append(name)
        seen.add(name)
    return rooms


def ingest_ring(
    collector,
    room: str,
    lines: list[str],
) -> tuple[int, int, int]:
    """Ingest export JSONL lines into the collector indices.

    Returns (ingested, skipped_seen, malformed). The room's watermarks
    are FROZEN at sweep start: exports arrive oldest-first, and each
    ingest lowers the floor — comparing against a moving floor would
    re-skip everything above the first ingested record. Freezing is
    race-free too: this function is fully synchronous, so the poll loop
    cannot interleave mid-sweep, and the live paths re-check their own
    high-water mark on every _ingest anyway.
    """
    monitored = room in collector.monitored
    lo_start = collector._seq_lo.get(room)
    hi_start = collector._seq_hi.get(room)
    ingested = skipped = malformed = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(record, dict):
            malformed += 1
            continue
        try:
            seq = int(record.get("seq"))
        except (TypeError, ValueError):
            malformed += 1
            continue

        below = lo_start is None or seq < lo_start
        above = hi_start is None or seq > hi_start
        if monitored:
            # Poll owns the top — backfill takes only the untouched bottom.
            allowed = below
        else:
            allowed = below or above
        if not allowed:
            skipped += 1
            continue

        collector._ingest(room, record, source="backfill", window=False)
        lo_now = collector._seq_lo.get(room)
        if lo_now is None or seq < lo_now:
            collector._seq_lo[room] = seq
        hi_now = collector._seq_hi.get(room)
        if hi_now is None or seq > hi_now:
            collector._seq_hi[room] = seq
        ingested += 1
    return ingested, skipped, malformed


async def sweep_once(collector, rooms: list[str]) -> dict[str, int]:
    """One export sweep over the given rooms. Never raises."""
    totals = {"rooms_ok": 0, "rooms_failed": 0, "ingested": 0, "skipped": 0}
    for room in rooms:
        try:
            resp = await collector.client.get(
                f"/r/{room}/export",
                timeout=httpx.Timeout(BACKFILL_TIMEOUT_S, connect=10.0),
            )
            if resp.status_code == 429:
                # Rate limited — sit one out, then retry once before
                # deferring the room to the next sweep.
                await asyncio.sleep(10.0)
                resp = await collector.client.get(
                    f"/r/{room}/export",
                    timeout=httpx.Timeout(BACKFILL_TIMEOUT_S, connect=10.0),
                )
            resp.raise_for_status()
            lines = resp.text.splitlines()
            ingested, skipped, malformed = ingest_ring(collector, room, lines)
            totals["rooms_ok"] += 1
            totals["ingested"] += ingested
            totals["skipped"] += skipped
            if ingested or malformed:
                log.info(
                    "backfill %s: +%d msgs (%d already indexed, %d malformed)",
                    room,
                    ingested,
                    skipped,
                    malformed,
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            totals["rooms_failed"] += 1
            log.warning("backfill %s failed: %s", room, e)
        collector.technocore_ok = True
        collector.last_success = time.time()
        await asyncio.sleep(BACKFILL_ROOM_DELAY_S)
    return totals


async def persist_watermarks(collector) -> None:
    """Write {room: {lo, hi}} to the store (cross-boot dedup contract)."""
    watermarks: dict[str, dict[str, int]] = {}
    for room, lo in collector._seq_lo.items():
        if lo is None:
            continue
        hi = collector._seq_hi.get(room)
        watermarks[room] = {"lo": lo, "hi": hi if hi is not None else lo}
    try:
        await collector.store.set(SEQ_WATERMARK_KEY, watermarks)
    except Exception as e:
        log.warning("watermark persist failed: %s", e)


async def backfill_loop(collector) -> None:
    """Boot sweep + periodic re-sweep (picks up unmonitored-room traffic)."""
    first = True
    while True:
        if not first:
            await asyncio.sleep(BACKFILL_INTERVAL_S)
        first = False
        rooms = select_rooms(collector.room_metas)
        if not rooms:
            log.warning("backfill: no rooms selected yet (no /rooms data)")
            continue
        log.info("Backfill sweep starting: %d rooms", len(rooms))
        try:
            totals = await sweep_once(collector, rooms)
            log.info(
                "Backfill sweep done: %d rooms ok, %d failed, "
                "+%d messages ingested (%d already indexed)",
                totals["rooms_ok"],
                totals["rooms_failed"],
                totals["ingested"],
                totals["skipped"],
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("backfill sweep crashed (retries next cycle): %s", e)
        await persist_watermarks(collector)
