"""Tests for the in-process EventBus + its collector/SSE wiring.

Regression context: the collector used to PUBLISH every ingested message to
Redis pub/sub 24/7 (plus a full backlog replay at every boot). On
per-command-billed providers that was the largest command consumer and it
even coupled feed ingestion to Redis health: a failed publish aborted the
poll loop before `last_seq` advanced, so the same messages were re-fetched
and re-ingested. The bus removes Redis from the fan-out path entirely
(FRI_EVENT_BUS=memory default) while the redis mode stays available.
"""

import asyncio
import json

from backend.collector import REDIS_CHANNEL, CollectorLoop
from backend.eventbus import EventBus

from backend.app import _sse_frame, app, live, sse_gate


class FakeStore:
    """Minimal async stand-in for backend.store.Store (no Redis needed)."""

    def __init__(self) -> None:
        self.data: dict = {}
        self.published: list[tuple[str, dict]] = []

    async def set(self, key, value):
        self.data[key] = value

    async def get(self, key):
        return self.data.get(key)

    async def publish(self, channel, message):
        self.published.append((channel, message))

    async def ping(self):
        return True

    async def close(self):
        pass


def _run(coro):
    return asyncio.run(coro)


class TestEventBus:
    def test_fanout_delivers_independent_copies(self):
        """Two subscribers each get their own copy — one consumer popping
        the top-level 'type' key must not corrupt the event for the other
        (the SSE handler mutates the dict it receives)."""

        async def run():
            bus = EventBus()
            q1 = await bus.subscribe()
            q2 = await bus.subscribe()
            await bus.publish({"type": "feed", "room": "lobby"})
            e1 = q1.get_nowait()
            e1.pop("type")  # first consumer mutates its copy
            return q2.get_nowait()

        event = _run(run())
        assert event["type"] == "feed"  # second copy unharmed
        assert event["room"] == "lobby"

    def test_bounded_queue_drops_oldest(self):
        """A stalled client's queue keeps the NEWEST events, bounded size."""

        async def run():
            bus = EventBus(max_queue=2)
            q = await bus.subscribe()
            for i in range(5):
                await bus.publish({"type": "feed", "n": i})
            out = []
            while not q.empty():
                out.append(q.get_nowait()["n"])
            return out, bus.subscriber_count

        out, count = _run(run())
        assert out == [3, 4]  # oldest three dropped, newest kept
        assert count == 1

    def test_unsubscribe_is_idempotent_and_removes_delivery(self):
        async def run():
            bus = EventBus()
            q = await bus.subscribe()
            await bus.unsubscribe(q)
            await bus.unsubscribe(q)  # second call must not raise
            await bus.publish({"type": "counts"})
            return bus.subscriber_count, q.empty()

        count, empty = _run(run())
        assert count == 0
        assert empty is True


class TestCollectorWiring:
    def test_memory_mode_emit_bypasses_redis(self):
        """Default mode: events reach bus subscribers, Redis sees NOTHING."""

        async def run():
            store = FakeStore()
            bus = EventBus()
            q = await bus.subscribe()
            collector = CollectorLoop(store, event_bus=bus)
            await collector._emit({"type": "counts", "total_dids": 7})
            await collector.client.aclose()
            return q.get_nowait(), store.published

        event, published = _run(run())
        assert event["total_dids"] == 7
        assert published == []  # zero Redis PUBLISH commands

    def test_redis_mode_still_publishes(self):
        """FRI_EVENT_BUS=redis: no bus passed → legacy pub/sub path intact."""

        async def run():
            store = FakeStore()
            collector = CollectorLoop(store, event_bus=None)
            await collector._emit({"type": "counts", "total_dids": 3})
            await collector.client.aclose()
            return store.published

        published = _run(run())
        assert published == [(REDIS_CHANNEL, {"type": "counts", "total_dids": 3})]

    def test_publish_counts_goes_to_bus_not_redis(self):
        """End-to-end through the real _publish_counts aggregation path."""

        async def run():
            store = FakeStore()
            bus = EventBus()
            q = await bus.subscribe()
            collector = CollectorLoop(store, event_bus=bus)
            collector.did_index.ingest_message(
                "lobby",
                {
                    "from": "did:key:a1",
                    "ts": "2026-09-14T00:00:00Z",
                    "text": "hi",
                    "seq": 1,
                },
            )
            await collector._publish_counts()
            await collector.client.aclose()
            return store.data.get("fri:counts"), q.get_nowait(), store.published

        cached, event, published = _run(run())
        assert cached["total_dids"] == 1  # snapshot still written to Redis
        assert event["type"] == "counts"
        assert event["total_dids"] == 1
        assert published == []  # but no PUBLISH command


class TestSseFrame:
    def test_frame_format_matches_frontend_contract(self):
        assert _sse_frame({"type": "feed", "room": "x"}) == (
            'event: feed\ndata: {"room": "x"}\n\n'
        )

    def test_missing_type_defaults_to_message(self):
        assert _sse_frame({"a": 1}) == 'event: message\ndata: {"a": 1}\n\n'

    def test_none_returns_none(self):
        assert _sse_frame(None) is None


class TestLiveEndpointBusMode:
    class FakeRequest:
        def __init__(self, ip: str):
            self.headers = {"x-forwarded-for": f"{ip}, 10.0.0.1"}
            self.client = None

        async def is_disconnected(self):
            return False

    def test_stream_delivers_bus_events_and_releases_slot(self):
        """Route-level: a connected stream receives a published event as a
        well-formed SSE frame, and disconnect releases the SseGate slot."""

        async def run():
            original_bus = getattr(app.state, "event_bus", None)
            app.state.store = FakeStore()
            app.state.event_bus = EventBus()
            agen = None
            try:
                resp = await live(self.FakeRequest("8.8.8.8"))
                agen = resp.body_iterator
                first = asyncio.ensure_future(agen.__anext__())
                await asyncio.sleep(0.05)  # let stream() subscribe first
                await app.state.event_bus.publish(
                    {"type": "counts", "total_dids": 42}
                )
                frame = await asyncio.wait_for(first, timeout=5.0)
                return frame, sse_gate.counts.get("8.8.8.8")
            finally:
                if agen is not None:
                    await agen.aclose()  # triggers stream() finally
                app.state.event_bus = original_bus
                sse_gate.leave("8.8.8.8")  # belt-and-suspenders; noop if released

        frame, slots_held_during_stream = _run(run())
        assert frame.startswith("event: counts\ndata: ")
        assert json.loads(frame.split("data: ", 1)[1].strip()) == {"total_dids": 42}
        # after aclose() the finally block must have released the slot
        assert "8.8.8.8" not in sse_gate.counts
        assert slots_held_during_stream == 1
