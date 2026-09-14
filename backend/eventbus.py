"""In-process event bus — default replacement for Redis pub/sub fan-out.

Why this exists: the collector used to publish EVERY ingested message (plus
each snapshot/counts/health update) to a Redis pub/sub channel. That traffic
flows 24/7 whether or not anyone is watching, and on per-command-billed
providers (Upstash free = 500K commands/month) it was the single largest
command consumer — a single boot that replays a room backlog can burn
thousands of PUBLISH commands alone. FRI deploys single-instance (one Render
free web service), so fan-out inside the process is functionally identical
for every SSE client:

- same event payloads, same delivery semantics (fire-and-forget live feed)
- near-instant delivery: no Redis round-trip, no 1-second get_message poll
- a Redis outage can no longer break the live feed, and no longer corrupts
  poll sequencing (a failed publish used to abort the last_seq update,
  causing the same messages to be re-fetched and re-ingested)
- zero Redis commands for pub/sub in any mode

Trade-off: subscribers must live in the same process as the collector.
Multi-process / multi-instance deployments can set FRI_EVENT_BUS=redis to
restore the legacy Redis pub/sub fan-out unchanged.

Slow-consumer policy: each subscriber gets a bounded queue; when it is full
the OLDEST event is dropped so the newest data always wins and a stalled
client can never grow memory unboundedly. SSE clients already tolerate gaps
(the ticker filters by timestamp and deduplicates).
"""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("fri.eventbus")


class EventBus:
    """Fan-out bus: one publisher (the collector), many SSE subscribers."""

    def __init__(self, max_queue: int = 500) -> None:
        self.max_queue = max(1, int(max_queue))
        self._subs: set[asyncio.Queue] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    async def publish(self, event: dict) -> None:
        """Deliver an event to every subscriber.

        Each subscriber receives its own shallow copy, so a consumer that
        mutates the top level (the SSE handler pops the "type" key) cannot
        corrupt the event for others. Delivery is best-effort per
        subscriber: a full queue drops its oldest event instead of blocking
        the collector.
        """
        for q in list(self._subs):
            if q.full():
                try:
                    q.get_nowait()  # drop oldest — newest data wins
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(dict(event))
            except asyncio.QueueFull:  # pragma: no cover — defensive
                pass

    async def subscribe(self) -> asyncio.Queue:
        """Register a subscriber queue (call unsubscribe() when done)."""
        q: asyncio.Queue = asyncio.Queue(maxsize=self.max_queue)
        self._subs.add(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue) -> None:
        """Remove a subscriber; unknown queues are ignored (idempotent)."""
        self._subs.discard(q)
