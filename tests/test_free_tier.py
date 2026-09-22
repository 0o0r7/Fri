"""Free-tier hardening tests (2026-09-22 "stay free" decision).

The Sep 21-22 wedge chain was: DID flood blew past the Aiven free-1
ceiling → store writes failed OOM → an unguarded snapshot killed
collector.start() → the flat-cadence retry loop burned the F1 CPU quota
→ full worker wedge. These tests pin the five guards that break the
chain: capped rehydrate/recovery, prune enforcement, guarded boot,
the /rooms no-limit fallback, and the honest /api/health verdict.
"""

import asyncio
import json
import random
import time

import httpx
import pytest

from collector.did_index import DidIndex, did_note_fingerprint

import backend.collector as bc
from backend.app import _health_verdict
from backend.collector import IDX_ACTIVE_KEY, IDX_REG_KEY, CollectorLoop
from backend.eventbus import EventBus


def _fp(n: int) -> str:
    return f"{n:016x}"


def _did_for(fp: str) -> str:
    # Deterministic did whose fingerprint hash is NOT fp — tests store
    # entries by explicit fingerprint keys, so the did string is arbitrary.
    return f"did:key:z6Mk{fp}"


class FreeTierStore:
    """In-memory async store with the full prune-primitive surface."""

    def __init__(self, fail_set: bool = False) -> None:
        self.data: dict[str, str] = {}
        self.zsets: dict[str, dict[str, float]] = {}
        self.sets: dict[str, set[str]] = {}
        self.fail_set = fail_set
        self.errors = 0

    # -- high-level (never-raise parity with Store) --------------------
    async def set(self, key, value):
        if self.fail_set:
            self.errors += 1
            raise RuntimeError("OOM command not allowed because memory usage is above limit")
        self.data[key] = value

    async def get(self, key):
        raw = self.data.get(key)
        return json.loads(raw) if raw else None

    async def publish(self, channel, message):
        return True

    async def ping(self):
        return True

    def stats(self):
        return {"store_errors": self.errors}

    # -- low-level primitives (raising parity with Store) --------------
    async def scan_keys(self, match, chunk=500):
        import fnmatch

        return [k for k in self.data if fnmatch.fnmatch(k, match)]

    async def mget_raw(self, keys):
        return [self.data.get(k) for k in keys]

    async def mset_raw(self, mapping):
        if self.fail_set:
            self.errors += 1
            raise RuntimeError("OOM command not allowed because memory usage is above limit")
        self.data.update(mapping)

    async def sadd(self, key, members):
        self.sets.setdefault(key, set()).update(members)

    async def smembers(self, key):
        return set(self.sets.get(key, set()))

    async def scard(self, key):
        return len(self.sets.get(key, set()))

    async def spop(self, key, count):
        members = set(self.sets.get(key, set()))
        if not members or count <= 0:
            return []
        popped = random.sample(sorted(members), min(count, len(members)))
        self.sets[key] = members - set(popped)
        return popped

    async def zadd(self, key, score, member):
        self.zsets.setdefault(key, {})[member] = score

    async def zadd_multi(self, key, pairs):
        zs = self.zsets.setdefault(key, {})
        for score, member in pairs:
            zs[member] = score

    async def zcard(self, key):
        return len(self.zsets.get(key, {}))

    async def zrange(self, key, start, end):
        ranked = sorted(self.zsets.get(key, {}).items(), key=lambda kv: kv[1])
        return [m for m, _ in ranked[start : end + 1]]

    async def zrem(self, key, members):
        zs = self.zsets.get(key, {})
        removed = 0
        for m in members:
            if zs.pop(m, None) is not None:
                removed += 1
        return removed

    async def delete(self, keys):
        removed = 0
        for k in keys:
            if self.data.pop(k, None) is not None:
                removed += 1
        return removed

    async def dbsize(self):
        return len(self.data)

    async def close(self):
        pass


def make_collector(store) -> CollectorLoop:
    """CollectorLoop with a MockTransport that answers rooms + room reads."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rooms":
            return httpx.Response(
                200,
                json={"rooms": [{"room": "lobby", "members": 3, "messages": 10}]},
            )
        return httpx.Response(200, json={"messages": []})

    c = CollectorLoop(store, base_url="http://technocore.test", event_bus=EventBus())
    c.client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://technocore.test",
    )
    return c


def seed_entry(store: FreeTierStore, fp: str, *, signed: int, first_seen: str,
               last_active: str | None = None, identity: bool = False) -> None:
    entry = {
        "did": _did_for(fp),
        "first_seen": first_seen,
        "messages_signed": signed,
    }
    if last_active:
        entry["last_active"] = last_active
    if identity:
        entry["identity_note"] = True
        entry["profile_bio"] = f"bio {fp}"
    store.data[f"fri:d:{fp}"] = json.dumps(entry, separators=(",", ":"))


class TestGuardedStart:
    def test_start_completes_and_spawns_all_tasks_when_store_fails(self):
        """A store at its ceiling (every write OOMs) must NOT kill boot:
        start() returns, all 10 supervised loops spawn, stop() is clean —
        this is the anti-retry-storm guarantee."""

        async def run():
            store = FreeTierStore(fail_set=True)
            c = make_collector(store)
            await c.start()  # must not raise
            task_count = len(c._tasks)
            names = {t.get_name() for t in c._tasks}
            await asyncio.sleep(0)  # let rehydrate/boot tasks settle
            await c.stop()
            cancelled = all(t.cancelled() for t in c._tasks)
            return task_count, names, cancelled

        task_count, names, cancelled = asyncio.run(run())
        assert task_count == 10
        assert "prune" in names and "did-persist" in names
        assert cancelled

    def test_guard_sets_degraded_but_does_not_raise(self):
        async def run():
            c = make_collector(FreeTierStore())

            async def boom():
                raise RuntimeError("upstream exploded")

            await c._guard("step", boom)
            return c.technocore_ok

        assert asyncio.run(run()) is False


class TestPrune:
    def test_prune_once_enforces_caps_and_protects_pins(self, monkeypatch):
        monkeypatch.setattr(bc, "KEEP_ACTIVE", 5)
        monkeypatch.setattr(bc, "KEEP_REGISTRY", 4)

        async def run():
            store = FreeTierStore()
            # 8 active entries, volumes 1..8 (top-5 by volume must survive)
            for n in range(1, 9):
                fp = _fp(n)
                seed_entry(
                    store, fp, signed=n,
                    first_seen="2026-09-01T00:00:00Z",
                    last_active="2026-09-20T00:00:00Z",
                )
                await store.zadd_multi(IDX_ACTIVE_KEY, [(float(n), fp)])
            # 9 registry entries; fp 100 is a pinned operator DID (newest)
            for n in range(50, 59):
                fp = _fp(n)
                seed_entry(store, fp, signed=0, first_seen="2026-09-02T00:00:00Z",
                           identity=True)
                await store.zadd_multi(IDX_REG_KEY, [(float(n), fp)])
            store.sets["fri:reg:priority"] = {_fp(50)}  # pin the LOWEST-scored one
            store.sets["fri:reg:known"] = {_fp(n) for n in range(200)}

            c = make_collector(store)
            await c._load_protected_fps()
            stats = await c._prune_once()
            active_card = await store.zcard(IDX_ACTIVE_KEY)
            reg_card = await store.zcard(IDX_REG_KEY)
            # Batched convergence: one cycle removes `excess` members, so
            # with a pin inside the set the cap is reached on the next pass.
            await c._prune_once()
            reg_card_converged = await store.zcard(IDX_REG_KEY)
            return c, store, stats, active_card, reg_card, reg_card_converged

        c, store, stats, active_card, reg_card, reg_card_converged = asyncio.run(run())
        # active: 8 -> 5 cap, lowest-volume (1,2,3) evicted
        assert stats["active_evicted"] == 3
        assert active_card == 5
        assert f"fri:d:{_fp(1)}" not in store.data
        assert f"fri:d:{_fp(8)}" in store.data
        # reg: 9 -> cap 4 in ONE pass (window extends past the pin);
        # the pin (fp50, LOWEST score = first candidate unprotected)
        # must survive
        assert stats["reg_evicted"] == 5
        assert reg_card == 4
        assert reg_card_converged == 4
        assert _fp(50) in store.zsets[IDX_REG_KEY]
        assert f"fri:d:{_fp(50)}" in store.data
        # known set: 200 members — cap not set here, nothing trimmed
        assert stats["known_trimmed"] == 0

    def test_prune_trims_known_and_junk_sets(self, monkeypatch):
        monkeypatch.setattr(bc, "KEEP_KNOWN", 6)
        monkeypatch.setattr(bc, "KEEP_JUNK", 3)

        async def run():
            store = FreeTierStore()
            store.sets["fri:reg:known"] = {_fp(n) for n in range(10)}
            store.sets["fri:reg:junk"] = {_fp(n) for n in range(20, 25)}
            c = make_collector(store)
            stats = await c._prune_once()
            return store, stats

        store, stats = asyncio.run(run())
        assert stats["known_trimmed"] == 4
        assert len(store.sets["fri:reg:known"]) == 6
        assert stats["junk_trimmed"] == 2
        assert len(store.sets["fri:reg:junk"]) == 3

    def test_prune_never_raises_on_store_errors(self, monkeypatch):
        async def run():
            store = FreeTierStore(fail_set=True)
            c = make_collector(store)
            stats = await c._prune_once()
            return stats

        stats = asyncio.run(run())
        assert "dbsize" in stats  # completed, errors swallowed


class TestRecoveryRehydrate:
    def test_oversized_store_is_pruned_and_indexed_at_boot(self, monkeypatch):
        monkeypatch.setattr(bc, "KEEP_ACTIVE", 5)
        monkeypatch.setattr(bc, "KEEP_REGISTRY", 3)

        async def run():
            store = FreeTierStore()
            for n in range(1, 9):  # active 1..8, top-5 survive
                seed_entry(store, _fp(n), signed=n,
                           first_seen="2026-09-01T00:00:00Z",
                           last_active="2026-09-20T00:00:00Z")
            for n in range(50, 59):  # 9 registry identities, 3 survive
                seed_entry(store, _fp(n), signed=0,
                           first_seen="2026-09-02T00:00:00Z", identity=True)
            store.sets["fri:reg:priority"] = {_fp(58)}  # pin the oldest-reg one
            c = make_collector(store)
            await c._rehydrate_did_entries({})
            active_card = await store.zcard(IDX_ACTIVE_KEY)
            reg_card = await store.zcard(IDX_REG_KEY)
            return c, store, active_card, reg_card

        c, store, active_card, reg_card = asyncio.run(run())
        # survivors: 5 active (volumes 4..8) + 3 reg + 1 pinned = 9 keys
        kept = [k for k in store.data if k.startswith("fri:d:")]
        assert len(kept) == 9
        assert f"fri:d:{_fp(8)}" in store.data  # highest volume kept
        assert f"fri:d:{_fp(3)}" not in store.data  # lowest volume evicted
        assert f"fri:d:{_fp(58)}" in store.data  # pinned survives
        # eviction indexes rebuilt for the survivors
        assert active_card == 5
        assert reg_card == 4  # 3 kept + 1 pinned
        # RAM index bounded: 5 active + 4 registry entries
        assert c.did_index.registry_only_count() == 4

    def test_right_sized_store_hydrates_everything(self):
        async def run():
            store = FreeTierStore()
            seed_entry(store, _fp(1), signed=7,
                       first_seen="2026-09-01T00:00:00Z",
                       last_active="2026-09-20T00:00:00Z")
            seed_entry(store, _fp(2), signed=0,
                       first_seen="2026-09-02T00:00:00Z", identity=True)
            c = make_collector(store)
            await c._rehydrate_did_entries({})
            return c, store

        c, store = asyncio.run(run())
        assert len([k for k in store.data if k.startswith("fri:d:")]) == 2
        assert c.did_index.get(_did_for(_fp(1))) is not None
        assert c.did_index.registry_only_count() == 1

    def test_empty_store_with_watermarks_resets_watermarks(self):
        async def run():
            store = FreeTierStore()
            c = make_collector(store)
            wm = {"lobby": {"lo": 5, "hi": 9}}
            await c._rehydrate_did_entries(wm)
            return c._seq_lo, c._seq_hi

        lo, hi = asyncio.run(run())
        assert lo == {} and hi == {}


class TestRoomsFallback:
    def test_limited_fetch_failure_falls_back_to_no_limit(self):
        """Upstream regression (2026-09-21): /rooms?limit=N hangs. A failing
        limited fetch must fall back to the no-limit form, which works."""

        async def run():
            calls: list[str] = []

            def handler(request: httpx.Request) -> httpx.Response:
                calls.append(request.url.params.get("limit"))
                if request.url.params.get("limit") is not None:
                    return httpx.Response(500)
                return httpx.Response(
                    200,
                    json={"rooms": [
                        {"room": "lobby", "members": 3, "messages": 10},
                        {"room": "kibble", "members": 5, "messages": 20},
                    ]},
                )

            store = FreeTierStore()
            c = CollectorLoop(store, base_url="http://technocore.test",
                              event_bus=EventBus())
            c.client = httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url="http://technocore.test",
            )
            try:
                await c._fetch_rooms()
                metas = dict(c.room_metas)
                ok = c.technocore_ok
            finally:
                await c.client.aclose()
            return metas, ok, calls

        metas, ok, calls = asyncio.run(run())
        assert calls == ["150", None]  # limited attempt, then no-limit
        assert set(metas) == {"lobby", "kibble"}
        assert ok is True

    def test_total_failure_keeps_cached_metas(self):
        async def run():
            def handler(request: httpx.Request) -> httpx.Response:
                raise httpx.ConnectError("black-holed")

            store = FreeTierStore()
            c = CollectorLoop(store, base_url="http://technocore.test",
                              event_bus=EventBus())
            c.room_metas["lobby"] = {"room": "lobby", "members": 3}
            c.client = httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url="http://technocore.test",
            )
            try:
                await c._fetch_rooms()
                metas = dict(c.room_metas)
                ok = c.technocore_ok
            finally:
                await c.client.aclose()
            return metas, ok

        metas, ok = asyncio.run(run())
        assert metas == {"lobby": {"room": "lobby", "members": 3}}
        assert ok is False


class TestHealthVerdict:
    def _collector(self, ok: bool = True, success_age: float = 0.0):
        class Stub:
            pass

        s = Stub()
        s.technocore_ok = ok
        s.last_success = time.time() - success_age
        s._tasks = []
        s._loop_failures = {}
        s.prune_stats = {"active_evicted": 0}
        return s

    def test_ready_healthy_collector_reports_ok(self):
        out = _health_verdict(
            {"status": "ok", "stale": False}, True, self._collector(), None
        )
        assert out["status"] == "ok"
        assert out["stale"] is False

    def test_frozen_payload_cannot_mask_dead_technocore(self):
        """The exact Sep 21 lie: payload says ok, collector says degraded."""
        out = _health_verdict(
            {"status": "ok", "stale": False},
            True,
            self._collector(ok=False, success_age=9_000),
            None,
        )
        assert out["status"] == "degraded"
        assert out["stale"] is True

    def test_not_ready_is_never_ok(self):
        fresh = _health_verdict(
            {"status": "ok", "stale": False}, False, None, None
        )
        assert fresh["status"] in ("starting", "degraded")
        assert fresh["stale"] is True


class TestDidIndexRamCap:
    def test_registry_only_entries_capped_oldest_first(self):
        idx = DidIndex()
        idx.max_registry = 5
        for n in range(10):
            did = f"did:key:z6Mk{n:02d}"
            idx.register_identity(did, bio=f"bot {n}")
            # Backdate immediately: the NEXT registration's eviction scan
            # must see deterministic ages (first_seen None ties otherwise).
            idx._dids[did].first_seen = f"2026-09-{n + 1:02d}T00:00:00Z"
        assert idx.registry_only_count() == 5
        # oldest (first_seen 09-01) evicted, newest (09-06..09-10) kept
        assert idx.get("did:key:z6Mk00") is None
        assert idx.get("did:key:z6Mk09") is not None

    def test_observed_message_upgrades_and_frees_registry_slot(self):
        idx = DidIndex()
        idx.max_registry = 2
        idx.register_identity("did:key:aaa")
        idx.register_identity("did:key:bbb")
        assert idx.registry_only_count() == 2
        idx.ingest_message("lobby", {
            "from": "did:key:aaa", "ts": "2026-09-20T00:00:00Z",
            "text": "hello", "seq": 1,
        })
        assert idx.registry_only_count() == 1
        # a third identity now fits without eviction pressure
        idx.register_identity("did:key:ccc")
        assert idx.registry_only_count() == 2
        assert idx.get("did:key:aaa") is not None  # upgraded, still tracked
