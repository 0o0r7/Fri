"""Tests for the reputation module."""

from __future__ import annotations

from collector.did_index import DidIndex
from collector.kibble import KibbleIndex
from collector.reputation import (
    SCHEMA_VERSION,
    ReputationScorer,
    _length_score,
    _log_scaled,
)
from collector.tclk import TclkIndex

# Sample DIDs
DID_A = "did:key:z6MkdidA"
DID_B = "did:key:z6MkdidB"
DID_C = "did:key:z6MkdidC"


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def test_log_scaled_zero():
    assert _log_scaled(0, 100) == 0.0


def test_log_scaled_at_cap():
    assert _log_scaled(100, 100) == 1.0


def test_log_scaled_above_cap_clamps_to_1():
    assert _log_scaled(500, 100) == 1.0


def test_log_scaled_between_zero_and_cap():
    # log10(11) / log10(101) ≈ 0.52
    score = _log_scaled(10, 100)
    assert 0.5 < score < 0.6


def test_length_score_sweet_spot():
    assert _length_score(40) == 1.0
    assert _length_score(400) == 1.0
    assert _length_score(200) == 1.0


def test_length_score_below_sweet_spot():
    # Linear ramp from 0 to 1.0 at 40 chars
    assert _length_score(0) == 0.0
    assert abs(_length_score(20) - 0.5) < 0.01


def test_length_score_above_sweet_spot():
    # Gradual penalty from 1.0 at 400 to 0.3 at 1000
    assert _length_score(1000) == 0.3
    assert _length_score(700) < 1.0


# ---------------------------------------------------------------------------
# ReputationScorer — edge cases
# ---------------------------------------------------------------------------


def _build_indices():
    """Build empty indices for testing."""
    return DidIndex(), KibbleIndex(), TclkIndex()


def _ingest_all(did_idx: DidIndex, kibble_idx: KibbleIndex, tclk_idx: TclkIndex, msg: dict, room: str = "kibble"):
    """Ingest a message into all three indices (mirrors what collector/main.py does)."""
    did_idx.ingest_message(room, msg)
    kibble_idx.ingest_message(room, msg)
    tclk_idx.ingest_message(room, msg)


def test_scorer_returns_none_for_unknown_did():
    did_idx, kibble_idx, tclk_idx = _build_indices()
    scorer = ReputationScorer(did_idx, kibble_idx, tclk_idx)
    assert scorer.score_did("did:key:z6Mknonexistent") is None


def test_scorer_did_with_only_activity_no_kibble_no_tclk():
    """A DID that has signed messages but no kibble or TCLK activity."""
    did_idx, kibble_idx, tclk_idx = _build_indices()
    # Sign 100 messages in 1 room, avg length ~100 chars
    for i in range(100):
        did_idx.ingest_message("lobby", {
            "seq": i, "from": DID_A, "ts": f"2026-09-07T17:48:{i:02d}Z",
            "text": "x" * 100,
        })

    scorer = ReputationScorer(did_idx, kibble_idx, tclk_idx)
    breakdown = scorer.score_did(DID_A)

    assert breakdown is not None
    assert breakdown.messages_signed == 100
    assert breakdown.rooms_active_in == 1
    assert breakdown.activity_score > 0.5  # high activity
    assert breakdown.work_score == 0.0  # no kibble work
    assert breakdown.reliability_score == 0.5  # neutral (no TCLK)
    # 0.3 * activity + 0.4 * 0 + 0.3 * 0.5
    expected = 0.3 * breakdown.activity_score + 0.0 + 0.3 * 0.5
    assert abs(breakdown.reputation_score - expected) < 0.01


def test_scorer_did_with_kibble_work():
    """A DID that has delivered kibble work and received useful attestations."""
    did_idx, kibble_idx, tclk_idx = _build_indices()
    # Some activity
    for i in range(50):
        _ingest_all(did_idx, kibble_idx, tclk_idx, {
            "seq": i, "from": DID_A, "ts": f"t{i}",
            "text": "x" * 80,
        })

    # 10 kibble deliveries with 5 useful attestations
    poster = "did:key:z6Mkposter"
    attester = "did:key:z6Mkattester"
    for i in range(10):
        job_id = f"k{ i:010d}"
        _ingest_all(did_idx, kibble_idx, tclk_idx, {
            "seq": 100 + i * 5, "from": poster, "ts": f"t{100+i*5}",
            "text": f"JOB v1 | {job_id} | build | Build thing {i}.",
        })
        _ingest_all(did_idx, kibble_idx, tclk_idx, {
            "seq": 101 + i * 5, "from": DID_A, "ts": f"t{101+i*5}",
            "text": f"CLAIM v1 | {job_id} | worker",
        })
        _ingest_all(did_idx, kibble_idx, tclk_idx, {
            "seq": 102 + i * 5, "from": DID_A, "ts": f"t{102+i*5}",
            "text": f"DELIVER v1 | {job_id} | Built it.",
        })
        if i < 5:
            _ingest_all(did_idx, kibble_idx, tclk_idx, {
                "seq": 103 + i * 5, "from": attester, "ts": f"t{103+i*5}",
                "text": f"ATTEST v1 | {job_id} | useful | Good work {i}.",
            })

    scorer = ReputationScorer(did_idx, kibble_idx, tclk_idx)
    breakdown = scorer.score_did(DID_A)

    assert breakdown is not None
    assert breakdown.deliveries_made == 10
    assert breakdown.useful_received_on_delivered == 5
    assert breakdown.not_received_on_delivered == 0
    assert breakdown.deliveries_component == 1.0  # 10 = cap
    assert breakdown.useful_component == 1.0  # 5 = cap
    assert breakdown.work_score >= 0.8  # high work score (0.4+0.4+0=0.8)


def test_scorer_did_with_not_ratings_penalized():
    """A DID with 'not' attestations should have a lower work score."""
    did_idx, kibble_idx, tclk_idx = _build_indices()

    poster = "did:key:z6Mkposter"
    attester = "did:key:z6Mkattester"
    # 5 deliveries, all rated "not"
    for i in range(5):
        job_id = f"k{ i:010d}"
        _ingest_all(did_idx, kibble_idx, tclk_idx, {"seq": i*4, "from": poster, "ts": "t", "text": f"JOB v1 | {job_id} | build | x"})
        _ingest_all(did_idx, kibble_idx, tclk_idx, {"seq": i*4+1, "from": DID_A, "ts": "t", "text": f"CLAIM v1 | {job_id} | worker"})
        _ingest_all(did_idx, kibble_idx, tclk_idx, {"seq": i*4+2, "from": DID_A, "ts": "t", "text": f"DELIVER v1 | {job_id} | x"})
        _ingest_all(did_idx, kibble_idx, tclk_idx, {"seq": i*4+3, "from": attester, "ts": "t", "text": f"ATTEST v1 | {job_id} | not | Bad."})

    scorer = ReputationScorer(did_idx, kibble_idx, tclk_idx)
    breakdown = scorer.score_did(DID_A)

    assert breakdown is not None
    assert breakdown.not_received_on_delivered == 5
    assert breakdown.not_penalty > 0
    # Work score should be low due to penalty
    assert breakdown.work_score < 0.3


def test_scorer_did_with_tclk_completed_deals():
    """A DID that completed TCLK deals as payee should have high reliability."""
    did_idx, kibble_idx, tclk_idx = _build_indices()

    payer = "did:key:z6Mkpayer"
    # 5 completed deals as payee
    for i in range(5):
        offer_id = f"0xoffer{i}"
        contract_id = f"0xcontract{i}"
        _ingest_all(did_idx, kibble_idx, tclk_idx, {"seq": i*5, "from": payer, "ts": "t", "text": _tclk_frame({
            "type": "offer", "from": payer, "id": offer_id,
            "amount": "1000", "asset": "FLOP", "role": "payer",
            "lock": "hash", "rails": ["paper"],
            "claimByMs": 1, "expiresMs": 1, "refundAfterMs": 1, "nonce": f"n{i}",
        })}, room="tclk-offers")
        _ingest_all(did_idx, kibble_idx, tclk_idx, {"seq": i*5+1, "from": DID_A, "ts": "t", "text": _tclk_frame({
            "type": "accept", "from": DID_A, "contract": contract_id,
            "ref": offer_id, "statement": "0xstmt", "nonce": f"n{i}b",
        })}, room="tclk-offers")
        _ingest_all(did_idx, kibble_idx, tclk_idx, {"seq": i*5+2, "from": payer, "ts": "t", "text": _tclk_frame({
            "type": "lock", "from": payer, "contract": contract_id,
            "rail": "paper", "ref": "0xlockref",
        })}, room="tclk-offers")
        _ingest_all(did_idx, kibble_idx, tclk_idx, {"seq": i*5+3, "from": DID_A, "ts": "t", "text": _tclk_frame({
            "type": "reveal", "from": DID_A, "contract": contract_id,
            "secret": "0xsecret",
        })}, room="tclk-offers")
        _ingest_all(did_idx, kibble_idx, tclk_idx, {"seq": i*5+4, "from": payer, "ts": "t", "text": _tclk_frame({
            "type": "receipt", "from": payer, "contract": contract_id,
            "outcome": "claimed", "rail": "paper", "ref": "0xlockref",
        })}, room="tclk-offers")

    scorer = ReputationScorer(did_idx, kibble_idx, tclk_idx)
    breakdown = scorer.score_did(DID_A)

    assert breakdown is not None
    assert breakdown.deals_as_payee == 5
    assert breakdown.deals_completed_as_payee == 5
    assert breakdown.completion_rate_as_payee == 1.0
    assert breakdown.has_tclk_activity is True
    assert breakdown.reliability_score > 0.7  # high reliability


def test_scorer_did_with_tclk_refunded_deals():
    """A DID that accepted TCLK deals but didn't complete them (payee failed)."""
    did_idx, kibble_idx, tclk_idx = _build_indices()

    payer = "did:key:z6Mkpayer"
    # 5 deals, all refunded (payee didn't reveal)
    for i in range(5):
        offer_id = f"0xoffer{i}"
        contract_id = f"0xcontract{i}"
        _ingest_all(did_idx, kibble_idx, tclk_idx, {"seq": i*4, "from": payer, "ts": "t", "text": _tclk_frame({
            "type": "offer", "from": payer, "id": offer_id,
            "amount": "1000", "asset": "FLOP", "role": "payer",
            "lock": "hash", "rails": ["paper"],
            "claimByMs": 1, "expiresMs": 1, "refundAfterMs": 1, "nonce": f"n{i}",
        })}, room="tclk-offers")
        _ingest_all(did_idx, kibble_idx, tclk_idx, {"seq": i*4+1, "from": DID_A, "ts": "t", "text": _tclk_frame({
            "type": "accept", "from": DID_A, "contract": contract_id,
            "ref": offer_id, "statement": "0xstmt", "nonce": f"n{i}b",
        })}, room="tclk-offers")
        _ingest_all(did_idx, kibble_idx, tclk_idx, {"seq": i*4+2, "from": payer, "ts": "t", "text": _tclk_frame({
            "type": "lock", "from": payer, "contract": contract_id,
            "rail": "paper", "ref": "0xlockref",
        })}, room="tclk-offers")
        _ingest_all(did_idx, kibble_idx, tclk_idx, {"seq": i*4+3, "from": payer, "ts": "t", "text": _tclk_frame({
            "type": "receipt", "from": payer, "contract": contract_id,
            "outcome": "refunded", "rail": "paper", "ref": "0xlockref",
        })}, room="tclk-offers")

    scorer = ReputationScorer(did_idx, kibble_idx, tclk_idx)
    breakdown = scorer.score_did(DID_A)

    assert breakdown is not None
    assert breakdown.deals_as_payee == 5
    assert breakdown.deals_completed_as_payee == 0
    assert breakdown.completion_rate_as_payee == 0.0
    assert breakdown.reliability_score < 0.3  # low reliability


def test_scorer_neutral_reliability_for_did_with_no_tclk():
    """A DID with no TCLK activity gets neutral reliability (0.5)."""
    did_idx, kibble_idx, tclk_idx = _build_indices()
    did_idx.ingest_message("lobby", {"seq": 1, "from": DID_A, "ts": "t", "text": "hello"})

    scorer = ReputationScorer(did_idx, kibble_idx, tclk_idx)
    breakdown = scorer.score_did(DID_A)

    assert breakdown is not None
    assert breakdown.has_tclk_activity is False
    assert breakdown.reliability_score == 0.5


def test_scorer_score_in_range_0_to_1():
    """All scores should be in [0.0, 1.0]."""
    did_idx, kibble_idx, tclk_idx = _build_indices()

    # DID with maximum activity
    for i in range(200):
        did_idx.ingest_message("lobby", {"seq": i, "from": DID_A, "ts": "t", "text": "x" * 200})

    # DID with minimal activity
    did_idx.ingest_message("lobby", {"seq": 0, "from": DID_B, "ts": "t", "text": "x"})

    scorer = ReputationScorer(did_idx, kibble_idx, tclk_idx)
    for did in [DID_A, DID_B]:
        breakdown = scorer.score_did(did)
        assert breakdown is not None
        assert 0.0 <= breakdown.reputation_score <= 1.0
        assert 0.0 <= breakdown.activity_score <= 1.0
        assert 0.0 <= breakdown.work_score <= 1.0
        assert 0.0 <= breakdown.reliability_score <= 1.0


def test_scorer_snapshot_structure():
    """Snapshot should have the expected top-level fields."""
    did_idx, kibble_idx, tclk_idx = _build_indices()
    did_idx.ingest_message("lobby", {"seq": 1, "from": DID_A, "ts": "t", "text": "hello"})

    scorer = ReputationScorer(did_idx, kibble_idx, tclk_idx)
    snap = scorer.snapshot()

    assert snap["version"] == "1.0"
    assert snap["schema_version"] == SCHEMA_VERSION
    assert "generated_at" in snap
    assert "weights" in snap
    assert "caps" in snap
    assert snap["total_dids_scored"] == 1
    assert "avg_score" in snap
    assert "score_buckets" in snap
    assert len(snap["dids"]) == 1
    assert snap["dids"][0]["did"] == DID_A


def test_scorer_score_all_sorted_by_reputation_desc():
    """score_all should return DIDs sorted by reputation_score descending."""
    did_idx, kibble_idx, tclk_idx = _build_indices()

    # DID_A: high activity (100 messages)
    for i in range(100):
        did_idx.ingest_message("lobby", {"seq": i, "from": DID_A, "ts": "t", "text": "x" * 100})
    # DID_B: low activity (1 message)
    did_idx.ingest_message("lobby", {"seq": 0, "from": DID_B, "ts": "t", "text": "x"})

    scorer = ReputationScorer(did_idx, kibble_idx, tclk_idx)
    breakdowns = scorer.score_all()
    assert len(breakdowns) == 2
    assert breakdowns[0].did == DID_A  # higher score first
    assert breakdowns[1].did == DID_B
    assert breakdowns[0].reputation_score >= breakdowns[1].reputation_score


def test_scorer_to_dict_includes_full_breakdown():
    """to_dict should include all components for transparency."""
    did_idx, kibble_idx, tclk_idx = _build_indices()
    did_idx.ingest_message("lobby", {"seq": 1, "from": DID_A, "ts": "t", "text": "hello world"})

    scorer = ReputationScorer(did_idx, kibble_idx, tclk_idx)
    breakdown = scorer.score_did(DID_A)
    assert breakdown is not None
    d = breakdown.to_dict()

    assert d["did"] == DID_A
    assert d["schema_version"] == SCHEMA_VERSION
    assert "reputation_score" in d
    assert "activity_score" in d
    assert "work_score" in d
    assert "reliability_score" in d
    assert "components" in d
    assert "activity" in d["components"]
    assert "work" in d["components"]
    assert "reliability" in d["components"]
    # Activity components
    assert d["components"]["activity"]["messages_signed"] == 1
    assert d["components"]["activity"]["rooms_active_in"] == 1
    # Work components
    assert d["components"]["work"]["deliveries_made"] == 0
    # Reliability components
    assert d["components"]["reliability"]["has_tclk_activity"] is False


def test_scorer_top_limit_caps_output():
    """snapshot should cap the number of DIDs in the output."""
    did_idx, kibble_idx, tclk_idx = _build_indices()
    for i in range(10):
        did = f"did:key:z6Mkdid{i:02d}"
        did_idx.ingest_message("lobby", {"seq": i, "from": did, "ts": "t", "text": "x" * 50})

    scorer = ReputationScorer(did_idx, kibble_idx, tclk_idx)
    snap = scorer.snapshot(top_limit=3)
    assert snap["total_dids_scored"] == 3  # capped
    assert len(snap["dids"]) == 3


def _tclk_frame(payload: dict) -> str:
    import json
    return "tclk1 " + json.dumps(payload, sort_keys=True, separators=(",", ":"))
