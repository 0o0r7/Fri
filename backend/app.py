"""FastAPI app — REST endpoints + SSE live stream.

Serves cached snapshots from Redis (instant, no technocore round-trip) and
a single multiplexed SSE endpoint that fans out Redis pub/sub events.
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from .collector import REDIS_CHANNEL, CollectorLoop
from .store import Store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fri.api")

REDIS_URL = "redis://redis:6379"
BASE_URL = "https://technocore.chat"


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = Store(REDIS_URL)
    collector = CollectorLoop(store, BASE_URL)
    await collector.start()
    app.state.store = store
    app.state.collector = collector
    log.info("FRI backend ready")
    yield
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


# ---------------------------------------------------------------------------
# REST endpoints — instant reads from Redis cache
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health():
    return await app.state.store.get("fri:health") or {"status": "starting"}


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
