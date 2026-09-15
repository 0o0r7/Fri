"""Collector lifecycle tests — boot, poll, shutdown, degraded recovery.

Uses httpx.MockTransport as the fake HTTP transport (no technocore, no
long sleeps) plus the FakeStore pattern from test_backend.py. Covers the
audit P2 batch: collector lifecycle start/stop, poll-loop sequencing, and
a fake-transport regression for the redis-mode re-ingest bug (a failed
emit used to block last_seq advancement and double-count the window).
"""

import asyncio
import logging

import httpx
import pytest

from backend.app import _retry_collector_start, app
from backend.collector import MONITORED_ROOMS, CollectorLoop
from backend.eventbus import EventBus


class FakeStore:
    """Async in-memory store; optional failing publish (redis-mode outage).

    Implements the durable-persistence surface (scan/mget/mset/sets)
    used by the collector's no-DID-forgotten layer.
    """

    def __init__(self, fail_publish: bool = False) -> None:
        self.data: dict = {}
        self.published: list[tuple[str, dict]] = []
        self.fail_publish = fail_publish
        self._sets: dict[str, set] = {}

    async def set(self, key, value):
        self.data[key] = value

    async def get(self, key):
        return self.data.get(key)

    async def scan_keys(self, match: str, chunk: int = 500):
        import fnmatch

        return [k for k in self.data if fnmatch.fnmatch(k, match)]

    async def mget_raw(self, keys):
        import json as _json

        out = []
        for k in keys:
            v = self.data.get(k)
            out.append(v if isinstance(v, str) else (_json.dumps(v) if v is not None else None))
        return out

    async def mset_raw(self, mapping):
        self.data.update(mapping)

    async def sadd(self, key, members):
        self._sets.setdefault(key, set()).update(members)

    async def smembers(self, key):
        return set(self._sets.get(key, set()))

    async def publish(self, channel, message):
        self.published.append((channel, message))
        if self.fail_publish:
            raise RuntimeError("redis pub/sub down")

    async def ping(self):
        return True

    async def close(self):
        pass


def msg(did: str, seq: int, text: str = "hello") -> dict:
    return {
        "from": did,
        "ts": "2026-09-14T00:00:0%dZ" % (seq % 10),
        "text": text,
        "seq": seq,
    }


def make_collector(store, bus=None, handler=None) -> CollectorLoop:
    """CollectorLoop with its HTTP client swapped for a MockTransport."""

    def default_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rooms":
            return httpx.Response(
                200,
                json={
                    "rooms": [
                        {"room": r, "members": 3, "messages": 10}
                        for r in MONITORED_ROOMS
                    ]
                },
            )
        room = request.url.path.split("/")[-1]
        since = int(request.url.params.get("since", 0))
        messages = (
            [msg("did:key:l1", 1), msg("did:key:l1", 2)]
            if since == 0 and room == "lobby"
            else []
        )
        return httpx.Response(200, json={"messages": messages})

    c = CollectorLoop(store, base_url="http://technocore.test", event_bus=bus)
    c.client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler or default_handler),
        base_url="http://technocore.test",
    )
    return c


def _run(coro):
    return asyncio.run(coro)


class TestLifecycle:
    def test_start_seeds_snapshots_and_tasks_stop_cancels_all(self):
        """start(): committed baseline → Redis, /rooms via HTTP, seed poll,
        full snapshot pass, 6 background loops. stop(): every task cancelled
        and the HTTP client closed — no dangling work after shutdown."""

        async def run():
            store = FakeStore()
            c = make_collector(store, bus=EventBus())
            await c.start()
            keys = sorted(k for k in store.data if k.startswith("fri:"))
            task_count = len(c._tasks)
            last_seq = c.last_seq.get("lobby", 0)
            dids = c.did_index.total_dids
            await c.stop()
            cancelled = all(t.cancelled() for t in c._tasks)
            closed = c.client.is_closed
            return keys, task_count, last_seq, dids, cancelled, closed

        keys, task_count, last_seq, dids, cancelled, closed = _run(run())
        assert set(keys) >= {
            "fri:rooms",
            "fri:dids",
            "fri:kibble",
            "fri:tclk",
            "fri:reputation",
            "fri:counts",
            "fri:health",
        }
        assert task_count == 9  # 6 core loops + persist + backfill + registry
        assert last_seq == 2  # seeded from the mock lobby backlog
        assert dids >= 2  # committed baseline hydration + live seed
        assert cancelled
        assert closed

    def test_poll_room_ingests_advances_seq_and_emits_feed(self):
        """The long-poll loop: messages land in the index, last_seq moves
        forward, and every message becomes a feed event for SSE clients."""

        async def run():
            store = FakeStore()
            bus = EventBus()
            q = await bus.subscribe()
            c = make_collector(store, bus)
            task = asyncio.create_task(c._poll_room("lobby"))
            try:
                frame = await asyncio.wait_for(q.get(), timeout=5.0)
                seq = c.last_seq.get("lobby")
                known = c.did_index.get("did:key:l1") is not None
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                await c.client.aclose()
            return frame, seq, known

        frame, seq, known = _run(run())
        assert frame["type"] == "feed"
        assert frame["room"] == "lobby"
        assert seq == 2
        assert known

    def test_poll_failure_sets_degraded_then_recovers(self):
        """HTTP 500 → technocore_ok=False; the next successful poll flips
        it back and ingestion resumes with the correct seq cursor."""

        async def run():
            state = {"calls": 0}

            def handler(request: httpx.Request) -> httpx.Response:
                state["calls"] += 1
                if state["calls"] == 1:
                    return httpx.Response(500)
                return httpx.Response(
                    200, json={"messages": [msg("did:key:l1", 5)]}
                )

            store = FakeStore()
            c = make_collector(store, bus=EventBus(), handler=handler)
            task = asyncio.create_task(c._poll_room("lobby"))
            try:
                for _ in range(40):
                    await asyncio.sleep(0.05)
                    if not c.technocore_ok:
                        break
                degraded = not c.technocore_ok
                for _ in range(120):
                    await asyncio.sleep(0.05)
                    if c.last_seq.get("lobby") == 5:
                        break
                recovered = (
                    c.last_seq.get("lobby") == 5 and c.technocore_ok
                )
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                await c.client.aclose()
            return degraded, recovered

        degraded, recovered = _run(run())
        assert degraded
        assert recovered

    def test_failed_publish_does_not_rewind_last_seq(self):
        """Redis-mode regression (fake transport): a failing PUBLISH must
        not abort the poll loop before last_seq advances — that re-fetched
        and re-ingested the same window until Redis recovered, inflating
        counters. With the guard, the feed degrades but counters stay
        exact and the window is ingested exactly once."""

        async def run():
            store = FakeStore(fail_publish=True)
            c = make_collector(store, bus=None)  # redis fan-out mode
            task = asyncio.create_task(c._poll_room("lobby"))
            try:
                for _ in range(100):
                    await asyncio.sleep(0.02)
                    if c.last_seq.get("lobby") == 2:
                        break
                seq = c.last_seq.get("lobby")
                await asyncio.sleep(1.3)  # allow retries to re-poll
                stats = c.did_index.get("did:key:l1")
                signed = stats.messages_signed if stats else -1
                attempts = len(store.published)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                await c.client.aclose()
            return seq, signed, attempts

        seq, signed, attempts = _run(run())
        assert seq == 2  # advanced despite publish failures
        assert signed == 2  # ingested exactly once — no re-ingest inflation
        assert attempts >= 1  # publish was genuinely attempted

    def test_hydration_summary_logged(self, caplog):
        """P2 log-search aid: one greppable boot line stating what the
        committed baseline restored, after per-file hydration lines."""

        async def run():
            c = make_collector(FakeStore())
            try:
                await c._seed_from_committed()
            finally:
                await c.client.aclose()

        with caplog.at_level(logging.INFO, logger="fri.collector"):
            _run(run())
        assert any(
            "Committed-baseline hydration complete" in r.message
            for r in caplog.records
        )


class TestCollectorRetry:
    def test_retry_recovers_when_redis_returns(self, monkeypatch):
        """Degraded boot → _retry_collector_start keeps probing; once the
        store answers PING and start() succeeds, collector_ready flips."""

        monkeypatch.setattr("backend.app.COLLECTOR_RETRY_S", 0.01)

        async def run():
            store = FakeStore()
            pings = {"n": 0}

            async def flaky_ping():
                pings["n"] += 1
                return pings["n"] > 3  # down for ~3 retry cycles

            store.ping = flaky_ping

            started = {"n": 0}

            class StubCollector:
                async def start(self):
                    started["n"] += 1

            original_ready = getattr(app.state, "collector_ready", None)
            app.state.collector_ready = False
            try:
                task = asyncio.create_task(
                    _retry_collector_start(StubCollector(), store, app)
                )
                for _ in range(500):
                    await asyncio.sleep(0.01)
                    if app.state.collector_ready:
                        break
                done = task.done()
                return (
                    app.state.collector_ready,
                    started["n"],
                    done,
                    pings["n"],
                )
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                app.state.collector_ready = original_ready or False

        ready, started, done, pings = _run(run())
        assert ready is True
        assert started == 1  # start() succeeded exactly once
        assert done  # retry loop exited by itself
        assert pings >= 4

    def test_retry_stays_degraded_while_redis_down(self, monkeypatch):
        """PING keeps failing → no start() attempt, collector_ready stays
        False, and the loop keeps waiting (service stays up, degraded)."""

        monkeypatch.setattr("backend.app.COLLECTOR_RETRY_S", 0.01)

        async def run():
            store = FakeStore()

            async def down_ping():
                return False

            store.ping = down_ping
            started = {"n": 0}

            class StubCollector:
                async def start(self):
                    started["n"] += 1

            original_ready = getattr(app.state, "collector_ready", None)
            app.state.collector_ready = False
            task = asyncio.create_task(
                _retry_collector_start(StubCollector(), store, app)
            )
            try:
                await asyncio.sleep(0.15)
                return app.state.collector_ready, started["n"]
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                app.state.collector_ready = original_ready or False

        ready, started = _run(run())
        assert ready is False
        assert started == 0


@pytest.fixture(autouse=True)
def _restore_app_state():
    """Keep the module-level app.state pristine between tests."""
    yield
    app.state.collector_ready = False
    if hasattr(app.state, "_collector_retry_task"):
        del app.state._collector_retry_task
