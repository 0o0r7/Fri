"""FastAPI app — REST endpoints + SSE live stream.

Serves cached snapshots from Redis (instant, no technocore round-trip) and
a single multiplexed SSE endpoint. Event fan-out defaults to the in-process
EventBus (FRI_EVENT_BUS=memory, zero Redis pub/sub commands); the legacy
Redis pub/sub fan-out remains available via FRI_EVENT_BUS=redis.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Receive, Scope, Send

from collector.reputation import SCHEMA_VERSION, ReputationScorer

from .collector import MONITORED_ROOMS, REDIS_CHANNEL, CollectorLoop
from .eventbus import EventBus
from .store import Store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fri.api")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
BASE_URL = os.environ.get("TECHNOCORE_BASE_URL", "https://technocore.chat")

COLLECTOR_RETRY_S = float(os.environ.get("FRI_COLLECTOR_RETRY_S", "30"))

# SSE event fan-out: "memory" (default) uses the in-process EventBus — the
# single-instance deployment needs no Redis pub/sub, and cutting it removes
# the largest per-command consumer (per-message PUBLISH, also replayed in
# bursts at every boot). "redis" restores pub/sub fan-out for multi-process
# deployments. Any other value falls back to memory with a warning.
EVENT_BUS_MODE = os.environ.get("FRI_EVENT_BUS", "memory").strip().lower()
if EVENT_BUS_MODE not in ("memory", "redis"):
    EVENT_BUS_MODE = "memory"

# The collector prunes fri:health:snapshots to 7 days, so asking for more
# than 168h can never return more data — it only widened the scan range.
MAX_SNAPSHOT_HOURS = 168

# Cap on concurrent /api/live SSE streams per client IP. Every open stream
# holds a subscription slot and a task; a runaway tab farm (or a
# naive scraper) can exhaust both. Tunable via env; a frontend opens one
# stream per tab, so the default leaves headroom for a handful of tabs
# behind one NAT address.
SSE_PER_IP_LIMIT = int(os.environ.get("FRI_SSE_PER_IP_LIMIT", "5"))


class SseGate:
    """Concurrent SSE-connection counter per client IP.

    enter() is check+increment in one synchronous step (no await between
    them), so two simultaneous requests cannot both slip past the cap.
    leave() runs in the stream's finally block, so disconnects — clean or
    aborted — always release the slot. Counts live in process memory: a
    restart resets them, which is the right failure mode for an
    abuse-mitigation valve. Direct (non-proxied) clients can spoof
    X-Forwarded-For to rotate buckets; that is accepted here — the gate
    targets accidental runaway connections, not determined adversaries.
    """

    def __init__(self, limit: int) -> None:
        self.limit = max(1, limit)
        self.counts: dict[str, int] = {}

    def enter(self, ip: str) -> bool:
        """Try to take a slot; False when the client is at the cap."""
        n = self.counts.get(ip, 0)
        if n >= self.limit:
            return False
        self.counts[ip] = n + 1
        return True

    def leave(self, ip: str) -> None:
        n = self.counts.get(ip, 0)
        if n <= 1:
            self.counts.pop(ip, None)
        else:
            self.counts[ip] = n - 1


sse_gate = SseGate(SSE_PER_IP_LIMIT)


class CacheHeaderMiddleware:
    """Audit P0: explicit cache semantics on every /api response.

    Snapshot REST reads are safe to share-cache for one snapshot cycle
    (30s), so CDN/browser re-polls stop hammering Redis on every view.
    /api/health must never be cached — it is the freshness probe; a cached
    "ok" would mask a dead backend and block the static fallback. /api/live
    sets its own no-cache headers (streaming), and non-2xx responses are
    left untouched so error answers are never cached.

    Implemented as raw ASGI (not BaseHTTPMiddleware) deliberately: the SSE
    stream must pass through with no extra response wrapper — wrapping has
    historically broken client-disconnect detection and heartbeats.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return
        path = scope["path"]

        async def send_wrapper(message) -> None:
            if message["type"] == "http.response.start":
                if path == "/api/health":
                    MutableHeaders(scope=message)["Cache-Control"] = "no-store"
                elif (
                    path != "/api/live"
                    and scope["method"] == "GET"
                    and 200 <= message["status"] < 300
                ):
                    MutableHeaders(scope=message)["Cache-Control"] = (
                        "public, max-age=30"
                    )
            await send(message)

        await self.app(scope, receive, send_wrapper)


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
    event_bus = EventBus() if EVENT_BUS_MODE == "memory" else None
    collector = CollectorLoop(store, BASE_URL, event_bus=event_bus)
    app.state.store = store
    app.state.event_bus = event_bus
    app.state.collector = collector
    app.state.collector_ready = False
    log.info("Event bus mode: %s", EVENT_BUS_MODE)

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
                "wrong. Managed providers require rediss:// with the full "
                "credential — Upstash: rediss://default:<PASSWORD>@<host>:6379 "
                "(the Redis URL, not the REST URL); Aiven Valkey: the Service "
                "URI from the service Overview page."
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
app.add_middleware(CacheHeaderMiddleware)


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


@app.get("/api/debug/sweep")
async def debug_sweep():
    """Registry-sweep observability: timing + counters of the last pass.

    Pure counters and timestamps — no DIDs, no bios, no store internals.
    Useful to confirm the sweep is alive, how far the shard walk got, and
    whether priority/pinned reconciliation ran (priority_healed > 0).
    """
    from backend.registry import LAST_SWEEP

    out = dict(LAST_SWEEP)
    out["sweep_running"] = (
        out.get("started_at") is not None
        and out.get("started_at") != out.get("finished_at")
    )
    return out


@app.get("/api/rooms")
async def rooms():
    return await app.state.store.get("fri:rooms") or {"rooms": []}


@app.get("/api/dids")
async def dids(q: str | None = None):
    """DID index snapshot — or a full-index search when `q` is present.

    The published snapshot caps per-DID detail at the top-500 by volume;
    a low-volume or registry-only DID would be unfindable through it.
    With ?q= the query runs against the LIVE full index (every DID ever
    observed or registered — substring match on the did string and the
    16-hex fingerprint), so "every DID stays queryable" actually holds.
    """
    if q and q.strip():
        collector = getattr(app.state, "collector", None)
        if collector is not None and getattr(app.state, "collector_ready", False):
            matches = collector.did_index.search(q, limit=500)
            return {
                "version": "1.2",
                "generated_at": _now(),
                "source": BASE_URL,
                "query": q.strip(),
                "total_dids": collector.did_index.total_dids,
                "total_messages_sampled": collector.did_index._total_messages_sampled,
                "dids": [s.to_dict() for s in matches],
            }
        # Collector not ready — best-effort filter over the cached view.
        payload = await app.state.store.get("fri:dids") or {"dids": []}
        needle = q.strip().lower()
        payload = {
            **payload,
            "query": needle,
            "dids": [
                d for d in payload.get("dids", [])
                if isinstance(d, dict) and needle in (d.get("did") or "").lower()
            ],
        }
        return payload
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


@app.get("/api/meta")
async def meta():
    """Methodology + semantics for every served number (audit P0).

    Each figure this API publishes is an OBSERVATION with a scope, not
    ground truth about the whole network. This endpoint documents the
    scope (monitored rooms, observation window — see the `window` block
    in /api/counts), the scoring method, and the known failure modes, so
    consumers can interpret — or challenge — the numbers instead of
    over-trusting them. Static per process; cached like other snapshots.
    """
    return {
        "service": "FRI — Flop Reputation Index",
        "base_url": BASE_URL,
        "schema_versions": {"reputation": SCHEMA_VERSION},
        "monitored_rooms": sorted(MONITORED_ROOMS),
        "methodology": {
            "sampling": (
                "Cumulative observation: at boot the collector hydrates "
                "from the committed baseline, re-merges the durable "
                "per-DID store, then a background sweep ingests the FULL "
                "retained ring of every major room via /r/<room>/export "
                "(seq-watermarked so nothing is double-counted), long-poll "
                "keeps monitored rooms live, and the persistent did-note "
                "registry indexes every self-published identity. Raw "
                "counters are cumulative observations, never estimates of "
                "the whole network."
            ),
            "room_selection": (
                "%d rooms are long-polled (key protocol rooms + events). "
                "Breadth comes from the periodic export sweep instead: "
                "technocore rate-limits (HTTP 429) aggressive polling, so "
                "the sweep reads each room's full ring at a polite cadence "
                "rather than holding hundreds of connections open. Dead "
                "rooms stay in the snapshot marked stale rather than being "
                "silently dropped." % len(MONITORED_ROOMS)
            ),
            "batch_vs_live": (
                "GitHub Actions batch runs produce the committed baseline "
                "dids.json used at boot; the live service adds observations "
                "on top and persists them durably (per-DID store keys + seq "
                "watermarks), so restarts and spin-downs no longer reset "
                "the index. Under message floods the live total_dids can "
                "exceed the batch baseline by a large factor — compare the "
                "window block in /api/counts and /api/health/snapshots "
                "before drawing conclusions from either."
            ),
            "durability": (
                "The source chat retains only ~10 MiB per room (hours under "
                "flood traffic) and forgets everything older. FRI is the "
                "archive: every DID once observed is persisted and "
                "re-merged at boot, and DIDs that published a did-note stay "
                "indexed through the persistent /kv/did-* registry even "
                "when all their messages churned out of every ring before "
                "they were ever sampled. Identity notes are "
                "self-published (identity_note: true) and carry no "
                "activity counters until real signed messages are seen. "
                "The registry sweep also self-heals: every pass re-fetches "
                "any did-note whose entry went missing from the durable "
                "store (eviction, flush, data loss), so the index "
                "converges back to the full persistent ledger instead of "
                "permanently forgetting what the store dropped. "
                "Operator-pinned identities (the persistent "
                "fri:reg:priority set, bootstrapped from FRI_PRIORITY_DIDS) "
                "are reconciled FIRST on every pass, so pinned DIDs come "
                "back within seconds of a restart even while the full "
                "1M+-note ledger is still being walked."
            ),
            "hydration_overlap": (
                "On boot the collector re-hydrates from the committed "
                "baseline; messages already counted there are not re-fetched "
                "and live ingest wins for known DIDs. Boot-relative metrics "
                "(peak rate windows) reset on every deploy or spin-down; "
                "committed cumulative counters persist."
            ),
            "scoring": (
                "Reputation is a weighted, log-scaled composite (activity, "
                "rooms, useful, posted/not, kibble, TCLK). Weights and caps "
                "are published in every /api/reputation snapshot. Activity "
                "uses effective_messages = messages_signed - low_signal_msgs: "
                "spam-flagged volume buys no reputation."
            ),
            "spam_integrity": (
                "Every message is classified into exactly one category "
                "(clean / phrase / template / campaign) and DIDs earn flags "
                "(phrase_spam, template_flood, campaign_template, "
                "rate_burst, new_did_flood). Flagged DIDs keep their raw "
                "counts and stay fully queryable — nothing is silently "
                "deleted — but their activity contributes zero to reputation "
                "scores. High-rate machine rooms are exempt from rate flags "
                "so legitimate feeds are not punished for volume."
            ),
            "stale_rooms": (
                "A monitored room that stops returning data keeps its last "
                "known state marked stale in /api/rooms; it is not dropped, "
                "so room totals never shrink merely because a room went "
                "quiet."
            ),
        },
        "limitations": [
            "Messages that churned out of technocore's ~10 MiB room rings "
            "before being observed are unrecoverable at the source; FRI "
            "indexes everything retained plus every self-published did-note, "
            "and keeps anything it has observed forever.",
            "total_dids includes flagged/spam DIDs (raw observation); reputation scoring excludes them.",
            "Registry-only identities (identity_note: true) have zero observed activity by definition — a profile is not participation.",
            "Restart cycles (e.g. free-tier spin-down) reset live rate windows and boot-relative metrics; durable counters and watermarks persist in the store.",
            "Single-instance event bus (FRI_EVENT_BUS=%s): SSE fan-out is per-process." % EVENT_BUS_MODE,
            "Snapshot history is capped at %dh (the store retains 7 days)." % MAX_SNAPSHOT_HOURS,
        ],
        "operational": {
            "event_bus_mode": EVENT_BUS_MODE,
            "sse_per_ip_limit": SSE_PER_IP_LIMIT,
            "cache": {"rest": "public, max-age=30 (snapshot cadence)", "sse": "no-cache", "health": "no-store"},
        },
    }


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


def _sse_frame(data: dict | None) -> str | None:
    """Format one SSE frame (pops the event type off a private event copy)."""
    if data is None:
        return None
    event_type = data.pop("type", "message")
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


@app.get("/api/live")
async def live(request: Request):
    """Server-Sent Events stream — fans out live collector events.

    Event types: counts, feed, rooms, dids, kibble, tclk, reputation, health
    Concurrent streams per client IP are capped (SseGate) — over the cap
    answers 429 so the frontend falls back to REST polling gracefully.
    """
    # Behind the Vercel rewrite the socket peer is Vercel's edge; the
    # original client IP rides in X-Forwarded-For (first hop wins).
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or (
        request.client.host if request.client else "unknown"
    )
    if not sse_gate.enter(ip):
        return JSONResponse(
            status_code=429,
            content={
                "error": "too_many_streams",
                "detail": f"max {sse_gate.limit} concurrent SSE streams per client",
            },
        )

    async def stream():
        bus = getattr(app.state, "event_bus", None)
        queue: asyncio.Queue | None = None
        pubsub = None
        if bus is not None:
            queue = await bus.subscribe()
        else:
            pubsub = app.state.store.pubsub()
            await pubsub.subscribe(REDIS_CHANNEL)
        try:
            last_heartbeat = time.time()
            while True:
                if await request.is_disconnected():
                    break
                data: dict | None = None
                if queue is not None:
                    try:
                        data = await asyncio.wait_for(queue.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        pass
                else:
                    message = await pubsub.get_message(
                        timeout=1.0, ignore_subscribe_messages=True
                    )
                    if message and message["type"] == "message":
                        data = json.loads(message["data"])
                frame = _sse_frame(data)
                if frame is not None:
                    yield frame
                elif time.time() - last_heartbeat > 15:
                    yield ": heartbeat\n\n"
                    last_heartbeat = time.time()
        finally:
            sse_gate.leave(ip)
            if queue is not None and bus is not None:
                await bus.unsubscribe(queue)
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(REDIS_CHANNEL)
                    await pubsub.close()
                except Exception:
                    pass  # pub/sub cleanup is best-effort; slot already released

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
