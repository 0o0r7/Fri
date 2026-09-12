"""Boot-time hydration tests — live indices restored from committed batch JSON.

Guards the P1 fix for "live index starts empty at boot": every backend
restart used to collapse /api/counts to whatever the 11 seeded rooms saw
recently, made daily_active ≈ total_dids in health snapshots (everything
looked brand-new), and wiped all TCLK/kibble deal history from reputation
until the firehose refilled it. hydrate() restores the exact state that
snapshot() published.

Core property under test — for each index, the round trip

    index → snapshot() → fresh_index.hydrate(snapshot)

must preserve counts, derived states, and every reputation-relevant
attribution (deliveries_made, useful_received_on_delivered, deals_as_payee,
deals_completed_as_payee, deals_refunded_as_payer, ...). Where the snapshot
does not publish data (frame timestamps, result/accept authors) the tests
assert the documented drift instead of inventing equality.

The last test class hydrates the repo's REAL data/*.json — a schema-drift
canary: if the batch collector ever changes the published shape, this test
breaks before production boot does.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.collector import CollectorLoop
from collector.did_index import DidIndex
from collector.kibble import KibbleIndex
from collector.tclk import TclkIndex

from test_backend import FakeStore

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

PAYER = "did:key:payer111111"
PAYEE = "did:key:payee222222"
POSTER = "did:key:poster333333"
WORKER = "did:key:worker444444"
RATER = "did:key:rater555555555"


def _tclk_msg(frame: dict, ts: str, seq: int) -> dict:
    return {
        "from": frame.get("from", ""),
        "ts": ts,
        "text": f"tclk1 {json.dumps(frame)}",
        "seq": seq,
    }


class TestDidHydrate:
    def test_roundtrip_preserves_reputation_inputs(self):
        idx = DidIndex()
        idx.ingest_message("lobby", {"from": PAYER, "ts": "2026-09-12T10:00:00Z",
                                     "text": "x" * 50, "seq": 1})
        idx.ingest_message("kibble", {"from": PAYER, "ts": "2026-09-12T11:00:00Z",
                                      "text": "y" * 150, "seq": 2})
        idx.ingest_message("kibble", {"from": PAYEE, "ts": "2026-09-12T12:00:00Z",
                                      "text": "z", "seq": 3})
        snap = idx.snapshot(top_limit=500)

        fresh = DidIndex()
        assert fresh.hydrate(snap) == 2
        assert fresh.total_dids == 2

        a = fresh.get(PAYER)
        assert a.messages_signed == 2
        assert a.rooms == {"lobby": 1, "kibble": 1}
        assert a.first_seen == "2026-09-12T10:00:00Z"
        assert a.last_active == "2026-09-12T11:00:00Z"
        assert a.total_text_chars == 200  # avg round-trips exactly
        assert a.to_dict() == idx.get(PAYER).to_dict()

    def test_hydrate_is_idempotent_and_live_ingest_wins(self):
        idx = DidIndex()
        idx.ingest_message("lobby", {"from": PAYER, "ts": "2026-09-12T10:00:00Z",
                                     "text": "hi", "seq": 1})
        snap = idx.snapshot(top_limit=500)

        fresh = DidIndex()
        assert fresh.hydrate(snap) == 1
        assert fresh.hydrate(snap) == 0  # second call: all entries known

        # Live ingest on top of hydrated state increments, never resets
        fresh.ingest_message("lobby", {"from": PAYER, "ts": "2026-09-12T12:00:00Z",
                                       "text": "again", "seq": 2})
        assert fresh.get(PAYER).messages_signed == 2

    def test_garbage_fields_do_not_crash(self):
        fresh = DidIndex()
        restored = fresh.hydrate({
            "total_messages_sampled": "not-a-number",
            "dids": [
                {"did": PAYER, "messages_signed": "bad", "avg_message_length": None},
                "not-a-dict",
                {"did": ""},
                None,
            ],
        })
        assert restored == 1
        assert fresh.get(PAYER).messages_signed == 0


class TestKibbleHydrate:
    def _build(self) -> KibbleIndex:
        idx = KibbleIndex()
        msgs = [
            (POSTER, "2026-09-12T10:00:00Z", "JOB v1 | k22503027d2 | build | do a thing"),
            (WORKER, "2026-09-12T10:05:00Z", "CLAIM v1 | k22503027d2 | worker"),
            (WORKER, "2026-09-12T10:10:00Z", "DELIVER v1 | k22503027d2 | here you go"),
            (RATER, "2026-09-12T10:15:00Z", "ATTEST v1 | k22503027d2 | useful | solid work"),
            (POSTER, "2026-09-12T10:20:00Z", "RESULT v1 | k22503027d2 | done"),
        ]
        for seq, (did, ts, text) in enumerate(msgs, 1):
            idx.ingest_message("kibble", {"from": did, "ts": ts, "text": text,
                                          "seq": seq})
        return idx

    def test_roundtrip_preserves_state_counts_and_attribution(self):
        idx = self._build()
        snap = idx.snapshot(top_limit=500)

        fresh = KibbleIndex()
        assert fresh.hydrate(snap) == 1
        assert fresh.total_jobs == 1
        assert fresh.total_frames == idx.total_frames
        assert fresh._frames_by_kind == idx._frames_by_kind

        orig, hyd = idx.get("k22503027d2"), fresh.get("k22503027d2")
        assert hyd.state == orig.state == "attested"

        a, b = orig.to_dict(), hyd.to_dict()
        # Documented drift: frame timestamps are not published, so
        # last_activity falls back to poster_ts after hydration.
        assert a.pop("last_activity") > b.pop("last_activity")
        assert a == b  # everything else is exact

        # Reputation-relevant did_stats are exact (these feed the work score)
        orig_stats, hyd_stats = idx.did_stats(), fresh.did_stats()
        for did in (POSTER, WORKER, RATER):
            for key in ("jobs_posted", "jobs_claimed", "deliveries_made",
                        "useful_received_on_delivered", "not_received_on_delivered",
                        "attestations_given", "attestations_useful", "attestations_not"):
                assert hyd_stats[did][key] == orig_stats[did][key], (did, key)
        assert hyd_stats[WORKER]["useful_received_on_delivered"] == 1
        # Documented drift: result/accept authors are not published, so
        # results_posted loses attribution (it feeds no reputation input).
        assert orig_stats[POSTER]["results_posted"] == 1
        assert hyd_stats[POSTER]["results_posted"] == 0

    def test_useful_not_totals_survive_attribution_shuffle(self):
        """Ratings publish only as aggregates; totals must stay exact even
        when individual rating→attester assignment is best-effort."""
        idx = KibbleIndex()
        idx.ingest_message("kibble", {"from": POSTER, "ts": "2026-09-12T10:00:00Z",
                                      "text": "JOB v1 | kbad01aa01 | review | x", "seq": 1})
        for i, (did, rating) in enumerate(
            [(WORKER, "useful"), (RATER, "not"), (PAYEE, "useful")], 2
        ):
            idx.ingest_message("kibble", {
                "from": did, "ts": f"2026-09-12T10:0{i}:00Z",
                "text": f"ATTEST v1 | kbad01aa01 | {rating} | note {i}", "seq": i,
            })
        snap = idx.snapshot(top_limit=500)
        job = snap["jobs"][0]
        assert job["useful_count"] == 2 and job["not_count"] == 1

        fresh = KibbleIndex()
        fresh.hydrate(snap)
        hyd = fresh.get("kbad01aa01")
        assert hyd.useful_count == 2
        assert hyd.not_count == 1
        assert len(hyd.attestations) == 3
        assert {a["did"] for a in hyd.attestations} == {WORKER, RATER, PAYEE}


class TestTclkHydrate:
    def _build(self) -> TclkIndex:
        """Full lifecycle (receipted/claimed) + an unaccepted offer."""
        idx = TclkIndex()
        offer = {"type": "offer", "id": "off1", "role": "payer", "from": PAYER,
                 "amount": "100", "asset": "FLOP", "rails": ["paper"],
                 "lock": "htlc"}
        seq = 0
        for frame, ts in [
            (offer, "2026-09-12T10:00:00Z"),
            ({"type": "accept", "contract": "ctr1", "ref": "off1", "from": PAYEE},
             "2026-09-12T10:01:00Z"),
            ({"type": "lock", "contract": "ctr1", "from": PAYER},
             "2026-09-12T10:02:00Z"),
            ({"type": "reveal", "contract": "ctr1", "from": PAYEE},
             "2026-09-12T10:03:00Z"),
            ({"type": "receipt", "contract": "ctr1", "from": PAYEE,
              "outcome": "claimed"}, "2026-09-12T10:04:00Z"),
            ({"type": "offer", "id": "off2", "role": "payer", "from": POSTER,
              "amount": "5", "asset": "FLOP", "rails": ["paper"]},
             "2026-09-12T10:05:00Z"),
        ]:
            seq += 1
            idx.ingest_message("tclk-offers", _tclk_msg(frame, ts, seq))
        return idx

    def test_roundtrip_is_exact_for_published_fields(self):
        idx = self._build()
        snap = idx.snapshot(top_limit=500)
        # 3 entries: the accepted contract (ctr1), the raw offer-keyed entry
        # kept in parallel by live ingest (off1, linked), and off2 (proposed)
        assert snap["total_contracts"] == 3

        fresh = TclkIndex()
        assert fresh.hydrate(snap) == 3
        assert fresh.total_contracts == idx.total_contracts
        assert fresh.total_frames == idx.total_frames
        assert fresh._frames_by_type == idx._frames_by_type

        for cid in ("ctr1", "off1", "off2"):
            assert fresh.get(cid).to_dict() == idx.get(cid).to_dict(), cid
        assert fresh.get("ctr1").state == "claimed"
        assert fresh.get("off2").state == "proposed"
        assert fresh.get("off1").offer_linked_elsewhere is True

    def test_reputation_attribution_matches_live_ingest(self):
        idx = self._build()
        snap = idx.snapshot(top_limit=500)
        fresh = TclkIndex()
        fresh.hydrate(snap)

        orig, hyd = idx.did_stats(), fresh.did_stats()
        for did in (PAYER, PAYEE, POSTER):
            for key in ("offers_made", "offers_accepted", "deals_as_payer",
                        "deals_as_payee", "deals_completed_as_payee",
                        "deals_refunded_as_payer"):
                assert hyd[did][key] == orig[did][key], (did, key)
        assert hyd[PAYEE]["deals_completed_as_payee"] == 1

    def test_roleless_offer_attribution(self):
        """Offers without a role field (39/86 in production data): the
        payer_did property derives the payer from the accept frame, so the
        synthetic accept must carry the published payer_did."""
        idx = TclkIndex()
        frames = [
            ({"type": "offer", "id": "offR", "from": PAYER, "amount": "1",
              "asset": "FLOP", "rails": ["paper"]}, "2026-09-12T10:00:00Z"),
            ({"type": "accept", "contract": "ctrR", "ref": "offR", "from": PAYEE},
             "2026-09-12T10:01:00Z"),
        ]
        for i, (f, ts) in enumerate(frames, 1):
            idx.ingest_message("tclk-offers", _tclk_msg(f, ts, i))
        snap = idx.snapshot(top_limit=500)

        fresh = TclkIndex()
        fresh.hydrate(snap)
        c = fresh.get("ctrR")
        entry = snap["contracts"][0]
        # Invariant: hydration reproduces the PUBLISHED payer/payee values
        # (for role-less offers the payer_did property returns the accepter
        # — whatever the batch published, hydration must round-trip it).
        assert c.payer_did == entry["payer_did"]
        assert c.payee_did == entry["payee_did"]
        assert c.to_dict() == idx.get("ctrR").to_dict()

    def test_offer_keyed_entry_not_double_counted(self):
        """Production data keeps the raw offer-keyed entry next to the
        accepted contract-id entry (13 pairs in the current batch).
        Hydration must mark it offer_linked_elsewhere, exactly like live
        ingest does, or did_stats counts the deal twice."""
        idx = self._build()  # off1 accepted → _contracts has ctr1 AND off1
        assert idx.get("off1").offer_linked_elsewhere is True
        snap = idx.snapshot(top_limit=500)

        fresh = TclkIndex()
        fresh.hydrate(snap)
        assert fresh.get("off1").offer_linked_elsewhere is True
        assert fresh.did_stats()[PAYER]["offers_made"] == idx.did_stats()[PAYER]["offers_made"]

    def test_refunded_state_without_receipt_keeps_live_semantics(self):
        """A refund frame (no receipt) must NOT gain deals_refunded_as_payer
        through hydration — live contracts of the same shape get none, and
        hydration must not silently change reputation semantics."""
        idx = TclkIndex()
        frames = [
            ({"type": "offer", "id": "off3", "role": "payer", "from": PAYER,
              "amount": "9", "asset": "FLOP", "rails": ["paper"]},
             "2026-09-12T10:00:00Z"),
            ({"type": "accept", "contract": "ctr3", "ref": "off3", "from": PAYEE},
             "2026-09-12T10:01:00Z"),
            ({"type": "refund", "contract": "ctr3", "from": PAYER},
             "2026-09-12T10:02:00Z"),
        ]
        for i, (f, ts) in enumerate(frames, 1):
            idx.ingest_message("tclk-offers", _tclk_msg(f, ts, i))
        snap = idx.snapshot(top_limit=500)
        assert snap["contracts"][0]["state"] == "refunded"

        fresh = TclkIndex()
        fresh.hydrate(snap)
        c = fresh.get("ctr3")
        assert c.state == "refunded"
        assert c.receipts == []  # no invented receipt
        assert fresh.did_stats()[PAYER]["deals_refunded_as_payer"] == 0
        assert fresh.get("ctr3").to_dict() == idx.get("ctr3").to_dict()


class TestCollectorSeedingHydrates:
    def test_seed_from_committed_hydrates_indices_and_store(self, tmp_path):
        dids = {
            "version": "1.0", "total_dids": 1, "total_messages_sampled": 10,
            "dids": [{
                "did": PAYER, "first_seen": "2026-09-12T10:00:00Z",
                "last_active": "2026-09-12T11:00:00Z", "messages_signed": 7,
                "rooms_active_in": 2, "rooms": ["lobby", "kibble"],
                "rooms_breakdown": {"lobby": 5, "kibble": 2},
                "avg_message_length": 40.0,
            }],
        }
        kibble = {
            "version": "1.0", "total_jobs": 1, "total_frames": 2,
            "total_messages_sampled": 10,
            "frames_by_kind": {"JOB": 1, "DELIVER": 1},
            "jobs": [{
                "job_id": "kseed01aa01", "category": "build", "prompt": "p",
                "poster_did": POSTER, "poster_ts": "2026-09-12T10:00:00Z",
                "poster_seq": 1, "state": "delivered",
                "claims_count": 1, "results_count": 0, "deliveries_count": 1,
                "accepts_count": 0, "attestations_count": 0,
                "useful_count": 0, "not_count": 0,
                "claimer_dids": [WORKER], "deliverer_dids": [WORKER],
                "attester_dids": [], "first_seen": "2026-09-12T10:00:00Z",
                "last_activity": "2026-09-12T10:10:00Z",
            }],
        }
        tclk = {
            "version": "1.0", "total_contracts": 1, "total_frames": 2,
            "total_messages_sampled": 10, "parse_failures": 0,
            "frames_by_type": {"offer": 1, "lock": 1},
            "contracts": [{
                "contract_id": "ctrSeed", "state": "locked",
                "payer_did": PAYER, "payee_did": PAYEE,
                "amount": "5", "asset": "FLOP", "rails": ["paper"],
                "lock_kind": "htlc", "job": None,
                "offer_ts": "2026-09-12T10:00:00Z",
                "accept_ts": "2026-09-12T10:01:00Z",
                "lock_count": 1, "reveal_count": 0, "refund_count": 0,
                "cancel_count": 0, "receipt_count": 0, "receipt_outcome": None,
                "heartbeat_count": 0,
                "first_seen": "2026-09-12T10:00:00Z",
                "last_activity": "2026-09-12T10:02:00Z",
                "offer_frame": {"type": "offer", "id": "offSeed", "role": "payer",
                                "from": PAYER, "amount": "5", "asset": "FLOP",
                                "rails": ["paper"]},
            }],
        }
        for name, payload in [("dids.json", dids), ("kibble.json", kibble),
                              ("tclk.json", tclk),
                              ("latest.json", {"rooms": []}),
                              ("reputation.json", {"dids": []})]:
            (tmp_path / name).write_text(json.dumps(payload))

        async def run():
            collector = CollectorLoop(FakeStore(), base_url="https://x.example")
            try:
                await collector._seed_from_committed(data_dir=tmp_path)
            finally:
                await collector.client.aclose()
            return collector

        collector = asyncio.run(run())
        assert collector.did_index.total_dids == 1
        assert collector.did_index.get(PAYER).messages_signed == 7
        assert collector.kibble_index.total_jobs == 1
        assert collector.kibble_index.get("kseed01aa01").state == "delivered"
        assert collector.tclk_index.total_contracts == 1
        assert collector.tclk_index.get("ctrSeed").state == "locked"
        store_data = collector.store.data
        assert set(store_data) >= {
            "fri:rooms", "fri:dids", "fri:kibble", "fri:tclk", "fri:reputation",
        }

    def test_health_snapshot_sane_right_after_boot_hydration(self, tmp_path):
        """The boot-accuracy fix end-to-end: with a hydrated index, the first
        health snapshot already reports committed DIDs as active/new instead
        of daily_active ≈ total_dids."""
        hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        two_days_ago = (datetime.now(timezone.utc) - timedelta(days=2)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        dids = {
            "total_messages_sampled": 5,
            "dids": [
                {"did": PAYER, "first_seen": two_days_ago, "last_active": hour_ago,
                 "messages_signed": 3, "rooms": ["lobby"],
                 "rooms_breakdown": {"lobby": 3}, "avg_message_length": 10.0},
                {"did": PAYEE, "first_seen": hour_ago, "last_active": hour_ago,
                 "messages_signed": 2, "rooms": ["lobby"],
                 "rooms_breakdown": {"lobby": 2}, "avg_message_length": 10.0},
            ],
        }
        (tmp_path / "dids.json").write_text(json.dumps(dids))

        async def run():
            collector = CollectorLoop(FakeStore(), base_url="https://x.example")
            try:
                await collector._seed_from_committed(data_dir=tmp_path)
                await collector._write_health_snapshot()
            finally:
                await collector.client.aclose()
            return collector

        collector = asyncio.run(run())
        (member,) = collector.store.zsets["fri:health:snapshots"].keys()
        snap = json.loads(member)
        assert snap["daily_active_agents"] == 2  # hydrated last_active used
        assert snap["new_dids_per_day"] == 1     # PAYEE only (PAYER 2d old)
        assert snap["total_dids"] == 2


class TestRealDataHydration:
    """Schema-drift canary: hydrate the repo's actual committed batch JSON.

    If the batch collector ever changes the published shape, these break
    before a production boot does.
    """

    def test_real_data_files_exist(self):
        assert (DATA_DIR / "dids.json").exists(), "batch snapshots missing"

    def test_real_dids_roundtrip(self):
        payload = json.loads((DATA_DIR / "dids.json").read_text())
        fresh = DidIndex()
        restored = fresh.hydrate(payload)
        assert restored == len(payload["dids"]) > 0
        assert fresh.total_dids == len(payload["dids"])
        for entry in payload["dids"][:5]:
            assert fresh.get(entry["did"]).to_dict() == entry

    def test_real_kibble_roundtrip(self):
        payload = json.loads((DATA_DIR / "kibble.json").read_text())
        fresh = KibbleIndex()
        assert fresh.hydrate(payload) == len(payload["jobs"])
        for entry in payload["jobs"][:5]:
            hyd = fresh.get(entry["job_id"])
            a = dict(entry)
            b = hyd.to_dict()
            a.pop("last_activity")
            b.pop("last_activity")
            assert a == b, entry["job_id"]

    def test_real_tclk_roundtrip(self):
        payload = json.loads((DATA_DIR / "tclk.json").read_text())
        fresh = TclkIndex()
        assert fresh.hydrate(payload) == len(payload["contracts"])
        assert fresh.total_contracts == payload["total_contracts"]
        mismatches = []
        for entry in payload["contracts"]:
            hyd = fresh.get(entry["contract_id"])
            if hyd is None or hyd.to_dict() != entry:
                mismatches.append(entry["contract_id"])
        assert mismatches == []
        # linked-offer pairs behave exactly like live ingest
        for entry in payload["contracts"]:
            oid = (entry.get("offer_frame") or {}).get("id")
            if oid and oid == entry["contract_id"] and entry["state"] == "proposed":
                c = fresh.get(oid)
                linked = any(
                    ((e.get("offer_frame") or {}).get("id") == oid
                     and e["contract_id"] != oid)
                    for e in payload["contracts"]
                )
                assert c.offer_linked_elsewhere == linked, oid
