"""Backend tests — health-snapshot aggregation + REST route smoke tests.

Regression guard for the `_write_health_snapshot` dataclass bug: the function
called `.get()` on DidStats / TclkContract / KibbleJob dataclass instances.
Every call raised AttributeError, the loop's try/except swallowed it, and the
7-day ecosystem-health history silently never wrote a single snapshot in
production (verified 2026-09-13: /api/health/snapshots returned count 0 on a
healthy backend).

These tests exercise the real aggregation against populated indices and the
real route handlers against an in-memory fake store — no Redis, no network.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone

from collector.did_index import DidStats
from collector.kibble import KibbleJob
from collector.tclk import TclkContract

from backend.app import app, counts, health, health_snapshots, rooms
from backend.collector import CollectorLoop


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeStore:
    """Minimal async stand-in for backend.store.Store (no Redis needed)."""

    def __init__(self) -> None:
        self.data: dict = {}
        self.zsets: dict = {}

    async def set(self, key, value):
        self.data[key] = value

    async def get(self, key):
        return self.data.get(key)

    async def zadd(self, key, score, member):
        self.zsets.setdefault(key, {})[member] = score

    async def zremrangebyscore(self, key, min_score, max_score):
        z = self.zsets.get(key, {})
        self.zsets[key] = {
            m: s for m, s in z.items() if not (min_score <= s <= max_score)
        }

    async def zrange(self, key, start, end):
        return list(self.zsets.get(key, {}).keys())

    async def ping(self):
        return True

    async def publish(self, channel, message):
        pass

    async def close(self):
        pass


class DownStore(FakeStore):
    """FakeStore that reports Redis as unreachable."""

    async def ping(self):
        return False


def _build_collector(now: datetime) -> CollectorLoop:
    """CollectorLoop with indices populated through their real ingest paths."""

    collector = CollectorLoop(FakeStore(), base_url="https://technocore.chat")

    def msg(did: str, ts: datetime) -> dict:
        return {"from": did, "ts": _iso(ts), "text": "hello world", "seq": 1}

    # a1: active + new  |  a2: seen 30h ago (neither)  |  a3: new + active
    collector.did_index.ingest_message(
        "kibble", msg("did:key:a1", now - timedelta(hours=1))
    )
    collector.did_index.ingest_message(
        "lobby", msg("did:key:a2", now - timedelta(hours=30))
    )
    collector.did_index.ingest_message(
        "meta", msg("did:key:a3", now - timedelta(hours=2))
    )

    # kibble: accepted + attested (count) + posted (does not count)
    collector.kibble_index._jobs["j1"] = KibbleJob(
        job_id="j1", accepts=[{"did": "did:key:a1"}]
    )
    collector.kibble_index._jobs["j2"] = KibbleJob(
        job_id="j2", attestations=[{"rating": "useful"}]
    )
    collector.kibble_index._jobs["j3"] = KibbleJob(job_id="j3")

    # tclk: c1 in-flight (locked → active) | c2 receipted "claimed" → terminal
    collector.tclk_index._contracts["c1"] = TclkContract(
        contract_id="c1", locks=[{"rail": "paper"}]
    )
    collector.tclk_index._contracts["c2"] = TclkContract(
        contract_id="c2", receipts=[{"outcome": "claimed"}]
    )

    return collector


class TestHealthSnapshot:
    def test_snapshot_written_with_correct_aggregates(self):
        """The regression: pre-fix this raised AttributeError and wrote nothing."""
        now = datetime.now(timezone.utc)

        async def run():
            collector = _build_collector(now)
            try:
                await collector._write_health_snapshot()
            finally:
                await collector.client.aclose()
            return collector.store

        store = asyncio.run(run())
        members = list(store.zsets.get("fri:health:snapshots", {}).keys())
        assert len(members) == 1, "exactly one snapshot must be written"

        snap = json.loads(members[0])
        assert snap["daily_active_agents"] == 2  # a1 + a3 (a2 is 30h old)
        assert snap["new_dids_per_day"] == 2  # a1 + a3 (a2 first seen 30h ago)
        assert snap["tclk_deal_volume"] == 1  # c1 active; c2 receipted → terminal
        assert snap["kibble_completion_rate"] == 0.6667  # 2 accepted/attested of 3
        assert snap["total_dids"] == 3
        assert snap["total_jobs"] == 3
        assert snap["total_contracts"] == 2
        assert snap["total_rooms"] == 0  # room_metas empty in this fixture
        assert snap["timestamp"].endswith("Z")

    def test_tclk_states_match_original_terminal_vocabulary(self):
        """Guards the semantics the fix relies on: derived `state` values.

        Terminal set ("claimed", "refunded", "cancelled") == KNOWN_OUTCOMES
        (TCLK SPEC §3.5 receipt outcomes); in-flight states are
        proposed/accepted/locked/revealed.
        """
        now = datetime.now(timezone.utc)

        async def run():
            collector = _build_collector(now)
            try:
                states = {
                    cid: c.state
                    for cid, c in collector.tclk_index._contracts.items()
                }
            finally:
                await collector.client.aclose()
            return states

        states = asyncio.run(run())
        assert states["c1"] == "locked"  # in-flight → counted active
        assert states["c2"] == "claimed"  # terminal outcome → not active


class TestRoutes:
    def _install(self, store: FakeStore) -> FakeStore:
        app.state.store = store
        return store

    def test_health_ok_returns_cached_health(self):
        async def run():
            store = self._install(FakeStore())
            store.data["fri:health"] = {"status": "ok", "stale": False}
            return await health()

        assert asyncio.run(run()) == {"status": "ok", "stale": False}

    def test_health_returns_503_when_redis_down(self):
        async def run():
            self._install(DownStore())
            resp = await health()
            return resp.status_code, json.loads(resp.body)

        status, body = asyncio.run(run())
        assert status == 503
        assert body["status"] == "unavailable"

    def test_counts_and_rooms_defaults(self):
        async def run():
            store = self._install(FakeStore())
            store.data["fri:counts"] = {"total_dids": 5}
            c = await counts()
            r = await rooms()  # absent key → default shape
            return c, r

        c, r = asyncio.run(run())
        assert c == {"total_dids": 5}
        assert r == {"rooms": []}

    def test_health_snapshots_filters_by_hours(self):
        now = datetime.now(timezone.utc)
        fresh = {"timestamp": _iso(now)}
        old = {"timestamp": _iso(now - timedelta(days=8))}

        async def run():
            store = self._install(FakeStore())
            zset = store.zsets.setdefault("fri:health:snapshots", {})
            zset[json.dumps(fresh)] = now.timestamp()
            zset[json.dumps(old)] = (now - timedelta(days=8)).timestamp()
            return await health_snapshots(hours=24)

        result = asyncio.run(run())
        assert result["count"] == 1
        assert result["snapshots"] == [fresh]
