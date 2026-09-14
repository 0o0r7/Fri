"""Fake-transport tests for the SSE redis-mode path, heartbeat + SseGate.

The memory (EventBus) SSE path is covered in test_eventbus.py. These tests
drive the LEGACY redis pub/sub fan-out (FRI_EVENT_BUS=redis) through a fake
pub/sub transport — no real Redis — plus the per-IP SSE gate and the
heartbeat contract that applies to both fan-out modes.
"""

import asyncio
import json

from backend.app import SseGate, app, live, sse_gate
from backend.collector import REDIS_CHANNEL


class FakePubSub:
    """Stand-in for redis.asyncio PubSub (decode_responses=True).

    Honors the same call signature the /api/live stream uses:
    subscribe(*channels), get_message(timeout, ignore_subscribe_messages),
    unsubscribe(*channels), close().
    """

    def __init__(self, messages: list[dict] | None = None) -> None:
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []
        self.closed = False
        self._queue: asyncio.Queue = asyncio.Queue()
        for m in messages or []:
            self._queue.put_nowait(m)

    async def subscribe(self, *channels):
        self.subscribed.extend(channels)

    async def get_message(self, timeout=1.0, ignore_subscribe_messages=False):
        try:
            msg = await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        if ignore_subscribe_messages and msg.get("type") != "message":
            return None  # consume silently, like redis-py
        return msg

    async def unsubscribe(self, *channels):
        self.unsubscribed.extend(channels)

    async def close(self):
        self.closed = True


class PubSubStore:
    """FakeStore with a pubsub() factory — the redis-mode SSE transport."""

    def __init__(self, pubsub: FakePubSub) -> None:
        self._pubsub = pubsub

    def pubsub(self):
        return self._pubsub

    async def ping(self):
        return True

    async def get(self, key):
        return None

    async def close(self):
        pass


class FakeRequest:
    def __init__(self, ip: str):
        self.headers = {"x-forwarded-for": f"{ip}, 10.0.0.1"}
        self.client = None

    async def is_disconnected(self):
        return False


def _run(coro):
    return asyncio.run(coro)


def _install_redis_mode(store) -> None:
    """Point app.state at the fake transport (redis fan-out mode)."""
    app.state.event_bus = None  # redis mode — no in-process bus
    app.state.store = store


def _restore_mode(original_bus) -> None:
    app.state.event_bus = original_bus


class TestRedisModeSseStream:
    def test_stream_delivers_published_message_as_sse_frame(self):
        """A message pushed into the pub/sub transport reaches the SSE
        stream as a well-formed frame; disconnect unsubscribes + closes."""

        async def run():
            ps = FakePubSub(
                messages=[
                    {
                        "type": "message",
                        "channel": REDIS_CHANNEL,
                        "data": json.dumps({"type": "counts", "total_dids": 9}),
                    }
                ]
            )
            original_bus = getattr(app.state, "event_bus", None)
            _install_redis_mode(PubSubStore(ps))
            agen = None
            try:
                resp = await live(FakeRequest("9.9.9.9"))
                agen = resp.body_iterator
                frame = await asyncio.wait_for(agen.__anext__(), timeout=5.0)
                return frame, ps
            finally:
                if agen is not None:
                    await agen.aclose()  # triggers stream() finally
                _restore_mode(original_bus)
                sse_gate.leave("9.9.9.9")  # belt-and-suspenders

        frame, ps = _run(run())
        assert frame.startswith("event: counts\ndata: ")
        assert json.loads(frame.split("data: ", 1)[1].strip()) == {"total_dids": 9}
        assert ps.subscribed == [REDIS_CHANNEL]
        assert ps.unsubscribed == [REDIS_CHANNEL]
        assert ps.closed is True
        assert "9.9.9.9" not in sse_gate.counts  # slot released

    def test_subscribe_confirmation_is_not_forwarded_as_event(self):
        """redis-py yields a 'subscribe' confirmation on the channel; the
        stream must consume it silently (ignore_subscribe_messages) and
        emit nothing for it."""

        async def run():
            ps = FakePubSub(
                messages=[
                    {"type": "subscribe", "channel": REDIS_CHANNEL, "data": 1}
                ]
            )
            original_bus = getattr(app.state, "event_bus", None)
            _install_redis_mode(PubSubStore(ps))
            agen = None
            try:
                resp = await live(FakeRequest("9.9.9.2"))
                agen = resp.body_iterator
                got_frame = None
                try:
                    got_frame = await asyncio.wait_for(
                        agen.__anext__(), timeout=0.4
                    )
                except asyncio.TimeoutError:
                    pass
                return got_frame
            finally:
                if agen is not None:
                    await agen.aclose()
                _restore_mode(original_bus)
                sse_gate.leave("9.9.9.2")

        assert _run(run()) is None  # no SSE frame for the confirmation

    def test_heartbeat_frame_when_transport_is_silent(self, monkeypatch):
        """No data for >15s → the stream emits an SSE comment heartbeat so
        proxies do not kill the idle connection."""

        class FastClock:
            """Stands in for the time module inside backend.app — each
            time.time() call jumps 20s, so one loop iteration crosses the
            15s heartbeat threshold."""

            def __init__(self):
                self.t = 1_000_000.0

            def time(self):
                self.t += 20.0
                return self.t

        monkeypatch.setattr("backend.app.time", FastClock())

        async def run():
            ps = FakePubSub()  # always silent
            original_bus = getattr(app.state, "event_bus", None)
            _install_redis_mode(PubSubStore(ps))
            agen = None
            try:
                resp = await live(FakeRequest("9.9.9.3"))
                agen = resp.body_iterator
                frame = await asyncio.wait_for(agen.__anext__(), timeout=5.0)
                return frame
            finally:
                if agen is not None:
                    await agen.aclose()
                _restore_mode(original_bus)
                sse_gate.leave("9.9.9.3")

        assert _run(run()) == ": heartbeat\n\n"


class TestSseGate:
    def test_enter_caps_at_limit_and_leave_releases(self):
        gate = SseGate(3)
        assert gate.enter("ip") is True
        assert gate.enter("ip") is True
        assert gate.enter("ip") is True
        assert gate.enter("ip") is False  # at cap
        gate.leave("ip")
        assert gate.enter("ip") is True  # slot freed
        gate.leave("ip")
        gate.leave("ip")
        gate.leave("ip")
        assert gate.counts == {}  # fully released, no zero-entry leftovers

    def test_leave_unknown_ip_is_noop(self):
        gate = SseGate(2)
        gate.leave("never-entered")  # must not raise
        assert gate.counts == {}

    def test_enter_slots_are_per_ip(self):
        gate = SseGate(1)
        assert gate.enter("a") is True
        assert gate.enter("b") is True  # different bucket
        assert gate.enter("a") is False

    def test_over_cap_request_answers_429(self):
        """Route-level: an IP at the cap gets the structured 429 body the
        frontend uses to fall back to REST polling."""

        async def run():
            original_bus = getattr(app.state, "event_bus", None)
            sse_gate.counts["6.6.6.6"] = sse_gate.limit  # simulate held slots
            try:
                return await live(FakeRequest("6.6.6.6"))
            finally:
                sse_gate.leave("6.6.6.6")
                _restore_mode(original_bus)

        resp = _run(run())
        assert resp.status_code == 429
        body = json.loads(resp.body)
        assert body["error"] == "too_many_streams"
