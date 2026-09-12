"""FastAPI app — REST endpoints + SSE live stream.

Serves cached snapshots from Redis (instant, no technocore round-trip) and
a single multiplexed SSE endpoint that fans out Redis pub/sub events.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from collector.reputation import ReputationScorer

from .collector import REDIS_CHANNEL, CollectorLoop
from .store import Store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fri.api")

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
BASE_URL = os.environ.get("TECHNOCORE_BASE_URL", "https://technocore.chat")

COLLECTOR_RETRY_S = float(os.environ.get("FRI_COLLECTOR_RETRY_S", "30"))

# The collector prunes fri:health:snapshots to 7 days, so asking for more
# than 168h can never return more data — it only widened the scan range.
MAX_SNAPSHOT_HOURS = 168


async def _retry_collector_start(
    collector: CollectorLoop, store: Store, app: FastAPI
) -> None:
    """Keep retrying collector.start() until Redis/provider recovers.

    Keeps the HTTP service alive (degraded) so /api/health keeps answering
    and the frontend's static-fallback keeps working while Redis is down.
    """
    while not app.state.collector_ready:
        await asyncio.sleep(COLLECTOR_RETRY_S)
        # Fast pre-check: skip the technocore HTTP warm-up while Redis is down
        if not await store.ping():
            log.warning("Redis still unreachable — retrying in %.0fs", COLLECTOR_RETRY_S)
            continue
        try:
            await collector.start()
            app.state.collector_ready = True
            log.info("Collector started after retry — live data restored")
        except Exception as e:
            log.warning(
                "Collector start retry failed: %s — retrying in %.0fs",
                e,
                COLLECTOR_RETRY_S,
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = Store(REDIS_URL)
    collector = CollectorLoop(store, BASE_URL)
    app.state.store = store
    app.state.collector = collector
    app.state.collector_ready = False

    try:
        # Fast pre-check so a dead Redis fails in <1s instead of after the
        # whole technocore HTTP warm-up inside collector.start().
        if not await store.ping():
            raise RedisConnectionError("Redis PING failed at boot")
        await collector.start()
        app.state.collector_ready = True
    except Exception as e:
        # Redis unreachable at boot must NOT kill the service (Render would
        # crash-loop). Serve degraded; the frontend falls back to static data.
        log.critical(
            "Collector failed to start (%s: %s) — serving degraded with no "
            "live data; retrying every %.0fs",
            type(e).__name__,
            e,
            COLLECTOR_RETRY_S,
        )
        if isinstance(e, RedisConnectionError) and "closed by server" in str(e).lower():
            log.critical(
                "HINT: 'Connection closed by server' usually means REDIS_URL is "
                "wrong. Upstash needs rediss://default:<PASSWORD>@<host>:6379 "
                "(the Redis URL from the Upstash console — not redis:// and not "
                "the REST https:// URL)."
            )
        app.state._collector_retry_task = asyncio.create_task(
            _retry_collector_start(collector, store, app)
        )

    log.info("FRI backend ready (collector_ready=%s)", app.state.collector_ready)
    yield

    retry_task = getattr(app.state, "_collector_retry_task", None)
    if retry_task and not retry_task.done():
        retry_task.cancel()
    await collector.stop()
    await store.close()
    log.info("FRI backend stopped")


app = FastAPI(title="FRI Live API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RedisConnectionError)
@app.exception_handler(RedisTimeoutError)
async def _redis_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    """Redis down mid-run → 503 (not 500) so the frontend falls back to static."""
    return JSONResponse(
        status_code=503,
        content={"error": "redis_unavailable", "detail": str(exc)[:200]},
    )


# ---------------------------------------------------------------------------
# REST endpoints — instant reads from Redis cache
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health():
    # Probe Redis directly: if it is down we must report 503 (not 200 with a
    # stale body), otherwise the frontend would enter LIVE mode and show blanks
    # instead of falling back to the committed static snapshots.
    if not await app.state.store.ping():
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "redis": False},
        )
    return await app.state.store.get("fri:health") or {"status": "starting"}


@app.get("/api/health/snapshots")
async def health_snapshots(hours: int = 24):
    """Historical ecosystem health snapshots from Redis sorted set.

    `hours` is clamped to 1..168 (the store only retains 7 days) and the
    range is applied server-side via ZRANGEBYSCORE, so a request can no
    longer pull the whole zset just to discard most of it in Python.
    """
    hours = max(1, min(hours, MAX_SNAPSHOT_HOURS))
    min_score = time.time() - (hours * 3600)
    members = await app.state.store.zrangebyscore(
        "fri:health:snapshots", min_score, "+inf"
    )
    snapshots = []
    for m in members:
        try:
            snapshots.append(json.loads(m))
        except Exception:
            pass
    return {"snapshots": snapshots, "count": len(snapshots)}


@app.get("/api/counts")
async def counts():
    return await app.state.store.get("fri:counts") or {}


@app.get("/api/rooms")
async def rooms():
    return await app.state.store.get("fri:rooms") or {"rooms": []}


@app.get("/api/dids")
async def dids():
    return await app.state.store.get("fri:dids") or {"dids": []}


@app.get("/api/kibble")
async def kibble():
    return await app.state.store.get("fri:kibble") or {"jobs": []}


@app.get("/api/tclk")
async def tclk():
    return await app.state.store.get("fri:tclk") or {"contracts": []}


@app.get("/api/reputation")
async def reputation():
    return await app.state.store.get("fri:reputation") or {"dids": []}


# ---------------------------------------------------------------------------
# Per-DID endpoints — Phase 4 drill-down (snapshot-first, live fallback)
# ---------------------------------------------------------------------------


def _find_did_entry(payload: dict | None, did: str) -> dict | None:
    """Find a DID's entry in a snapshot payload (fri:dids / fri:reputation)."""
    for entry in (payload or {}).get("dids", []):
        if isinstance(entry, dict) and entry.get("did") == did:
            return entry
    return None


async def _live_score(did: str) -> dict | None:
    """Score a DID against the live in-memory indices.

    Covers DIDs that became active after the last snapshot cycle (e.g.
    brand-new agents) — the 30s snapshot will include them momentarily,
    but a per-DID query should not have to wait. Returns None when the
    collector is not ready or the DID is unknown to the live index.
    """
    collector = getattr(app.state, "collector", None)
    if collector is None or not getattr(app.state, "collector_ready", False):
        return None
    if collector.did_index.get(did) is None:
        return None
    scorer = ReputationScorer(
        collector.did_index, collector.kibble_index, collector.tclk_index
    )
    breakdown = scorer.score_did(did)
    return breakdown.to_dict() if breakdown else None


@app.get("/api/did/{did}/score")
async def did_score(did: str):
    """Per-DID reputation score with the full transparent breakdown.

    Served from the cached fri:reputation snapshot; falls back to scoring
    against the live indices for DIDs newer than the last snapshot.
    404 when the DID is unknown to both.
    """
    rep = await app.state.store.get("fri:reputation")
    entry = _find_did_entry(rep, did)
    if entry is not None:
        return entry
    live = await _live_score(did)
    if live is not None:
        return live
    raise HTTPException(status_code=404, detail="did_not_found")


@app.get("/api/did/{did}/profile")
async def did_profile(did: str):
    """Per-DID profile: activity stats + reputation breakdown in one read.

    Aggregated from the cached snapshots with the same live fallback as
    /api/did/{did}/score. 404 only when the DID is unknown to both.
    """
    dids_payload = await app.state.store.get("fri:dids")
    did_stats = _find_did_entry(dids_payload, did)
    rep = await app.state.store.get("fri:reputation")
    rep_entry = _find_did_entry(rep, did)

    live_rep = None
    if rep_entry is None:
        live_rep = await _live_score(did)
        if did_stats is None and live_rep is not None:
            # The live index knows this DID even though the last snapshot
            # didn't include it — expose its fresh activity stats too.
            stats = app.state.collector.did_index.get(did)
            if stats is not None:
                did_stats = stats.to_dict()

    if did_stats is None and rep_entry is None and live_rep is None:
        raise HTTPException(status_code=404, detail="did_not_found")

    return {
        "did": did,
        "did_stats": did_stats,
        "reputation": rep_entry if rep_entry is not None else live_rep,
    }


# ---------------------------------------------------------------------------
# SSE — single multiplexed event stream
# ---------------------------------------------------------------------------


@app.get("/api/live")
async def live(request: Request):
    """Server-Sent Events stream — fans out Redis pub/sub events.

    Event types: counts, feed, rooms, dids, kibble, tclk, reputation, health
    """

    async def stream():
        pubsub = app.state.store.pubsub()
        await pubsub.subscribe(REDIS_CHANNEL)
        last_heartbeat = time.time()
        try:
            while True:
                if await request.is_disconnected():
                    break
                message = await pubsub.get_message(
                    timeout=1.0, ignore_subscribe_messages=True
                )
                if message and message["type"] == "message":
                    data = json.loads(message["data"])
                    event_type = data.pop("type", "message")
                    yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
                elif time.time() - last_heartbeat > 15:
                    yield ": heartbeat\n\n"
                    last_heartbeat = time.time()
        finally:
            await pubsub.unsubscribe(REDIS_CHANNEL)
            await pubsub.close()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
