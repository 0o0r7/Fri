"""Tests for the TCLK module."""

from __future__ import annotations

import json

from collector.tclk import (
    KNOWN_FRAME_TYPES,
    TclkContract,
    TclkIndex,
    parse_frame,
)


def _msg(seq: int, frm: str, text: str, ts: str | None = None) -> dict:
    return {
        "seq": seq,
        "from": frm,
        "text": text,
        "ts": ts or f"2026-09-07T17:48:{seq:02d}Z",
    }


def _tclk(payload: dict) -> str:
    """Build a tclk1 frame string from a dict (keys sorted, compact JSON)."""
    return "tclk1 " + json.dumps(payload, sort_keys=True, separators=(",", ":"))


# Sample DIDs
PAYER = "did:key:z6Mkpayer"
PAYEE = "did:key:z6Mkpayee"
ATTACKER = "did:key:z6Mkattacker"


# ---------------------------------------------------------------------------
# parse_frame
# ---------------------------------------------------------------------------


def test_parse_frame_offer():
    text = _tclk({"type": "offer", "from": PAYER, "amount": "1000", "asset": "FLOP"})
    parsed = parse_frame(text)
    assert parsed is not None
    assert parsed["type"] == "offer"
    assert parsed["amount"] == "1000"


def test_parse_frame_accept():
    text = _tclk({"type": "accept", "from": PAYEE, "contract": "0xabc", "ref": "0xdef", "statement": "0xghi", "nonce": "n1"})
    parsed = parse_frame(text)
    assert parsed is not None
    assert parsed["type"] == "accept"


def test_parse_frame_rejects_non_tclk():
    assert parse_frame("hello world") is None
    assert parse_frame("gm wagmi") is None
    assert parse_frame("") is None
    assert parse_frame(None) is None  # type: ignore[arg-type]


def test_parse_frame_rejects_malformed_json():
    # tclk1 prefix but broken JSON
    assert parse_frame("tclk1 {not valid json}") is None
    assert parse_frame("tclk1 ") is None


def test_parse_frame_rejects_no_type():
    assert parse_frame('tclk1 {"from":"x","amount":"1"}') is None


def test_parse_frame_handles_extra_whitespace():
    text = "  tclk1   " + json.dumps({"type": "offer", "from": "x"}) + "  "
    parsed = parse_frame(text)
    assert parsed is not None
    assert parsed["type"] == "offer"


def test_parse_frame_accepts_unknown_type():
    # We parse unknown types so the index can count them; they just don't
    # advance any contract state.
    text = _tclk({"type": "future_unknown_type", "from": "x"})
    parsed = parse_frame(text)
    assert parsed is not None
    assert parsed["type"] == "future_unknown_type"


# ---------------------------------------------------------------------------
# TclkContract state machine
# ---------------------------------------------------------------------------


def test_contract_state_progresses_proposed_to_receipted():
    c = TclkContract(contract_id="0xabc")
    assert c.state == "proposed"

    c.accept = {"from": PAYEE, "_ts": "t1"}
    assert c.state == "accepted"

    c.locks.append({"from": PAYER, "_ts": "t2"})
    assert c.state == "locked"

    c.reveals.append({"from": PAYEE, "_ts": "t3"})
    assert c.state == "revealed"

    c.receipts.append({"from": PAYER, "outcome": "claimed", "_ts": "t4"})
    assert c.state == "claimed"


def test_contract_state_refund_is_terminal():
    c = TclkContract(contract_id="0xabc")
    c.accept = {"from": PAYEE}
    c.locks.append({"from": PAYER})
    c.refunds.append({"from": PAYER, "_ts": "t"})
    assert c.state == "refunded"


def test_contract_state_cancel_is_terminal():
    c = TclkContract(contract_id="0xabc")
    c.cancels.append({"from": PAYER})
    assert c.state == "cancelled"


def test_contract_payer_payee_for_payer_role_offer():
    c = TclkContract(contract_id="0xabc")
    c.offer = {"role": "payer", "from": PAYER, "amount": "1000"}
    c.accept = {"from": PAYEE}
    assert c.payer_did == PAYER
    assert c.payee_did == PAYEE


def test_contract_payer_payee_for_payee_role_offer():
    c = TclkContract(contract_id="0xabc")
    c.offer = {"role": "payee", "from": PAYEE, "amount": "1000"}
    c.accept = {"from": PAYER}
    assert c.payer_did == PAYER
    assert c.payee_did == PAYEE


def test_contract_amount_asset_rails_lock_kind():
    c = TclkContract(contract_id="0xabc")
    c.offer = {
        "role": "payer",
        "from": PAYER,
        "amount": "1500",
        "asset": "FLOP",
        "rails": ["paper", "flop-htlc"],
        "lock": "hash",
    }
    assert c.amount == "1500"
    assert c.asset == "FLOP"
    assert c.rails == ["paper", "flop-htlc"]
    assert c.lock_kind == "hash"


def test_contract_receipt_outcome():
    c = TclkContract(contract_id="0xabc")
    assert c.receipt_outcome is None
    c.receipts.append({"from": PAYER, "outcome": "claimed"})
    assert c.receipt_outcome == "claimed"
    c.receipts.append({"from": PAYER, "outcome": "refunded"})
    # First receipt wins
    assert c.receipt_outcome == "claimed"


# ---------------------------------------------------------------------------
# TclkIndex
# ---------------------------------------------------------------------------


def test_index_ignores_non_tclk_messages():
    idx = TclkIndex()
    idx.ingest_message("tclk-offers", _msg(1, "did:key:z6Mktest", "hello world"))
    idx.ingest_message("tclk-offers", _msg(2, "did:key:z6Mktest", "gm wagmi"))
    snap = idx.snapshot()
    assert snap["total_contracts"] == 0
    assert snap["total_frames"] == 0
    assert snap["total_messages_sampled"] == 2


def test_index_counts_parse_failures():
    idx = TclkIndex()
    idx.ingest_message("tclk-offers", _msg(1, "did:key:z6Mktest", "tclk1 {broken"))
    snap = idx.snapshot()
    assert snap["total_contracts"] == 0
    assert snap["total_frames"] == 0
    assert snap["parse_failures"] == 1


def test_index_parses_full_deal_lifecycle():
    idx = TclkIndex()
    offer_id = "0xoffer123"
    contract_id = "0xcontract456"

    idx.ingest_message("tclk-offers", _msg(1, PAYER, _tclk({
        "type": "offer", "from": PAYER, "id": offer_id,
        "amount": "1000", "asset": "FLOP", "role": "payer",
        "lock": "hash", "rails": ["paper"],
        "claimByMs": 1789321687284, "expiresMs": 1788889687284,
        "refundAfterMs": 1789494487284, "nonce": "n1",
    }), ts="2026-09-07T17:48:00Z"))

    idx.ingest_message("tclk-offers", _msg(2, PAYEE, _tclk({
        "type": "accept", "from": PAYEE, "contract": contract_id,
        "ref": offer_id, "statement": "0xstmt", "nonce": "n2",
    }), ts="2026-09-07T17:48:01Z"))

    idx.ingest_message("tclk-offers", _msg(3, PAYER, _tclk({
        "type": "lock", "from": PAYER, "contract": contract_id,
        "rail": "paper", "ref": "0xlockref",
    }), ts="2026-09-07T17:48:02Z"))

    idx.ingest_message("tclk-offers", _msg(4, PAYEE, _tclk({
        "type": "reveal", "from": PAYEE, "contract": contract_id,
        "secret": "0xsecret",
    }), ts="2026-09-07T17:48:03Z"))

    idx.ingest_message("tclk-offers", _msg(5, PAYER, _tclk({
        "type": "receipt", "from": PAYER, "contract": contract_id,
        "outcome": "claimed", "rail": "paper", "ref": "0xlockref",
    }), ts="2026-09-07T17:48:04Z"))

    snap = idx.snapshot()
    assert snap["total_contracts"] == 2  # offer_id contract + contract_id contract
    assert snap["total_frames"] == 5
    assert snap["frames_by_type"]["offer"] == 1
    assert snap["frames_by_type"]["accept"] == 1
    assert snap["frames_by_type"]["lock"] == 1
    assert snap["frames_by_type"]["reveal"] == 1
    assert snap["frames_by_type"]["receipt"] == 1

    # The "real" contract is the one referenced by accept+ frames
    contract = idx.get(contract_id)
    assert contract is not None
    assert contract.state == "claimed"
    assert contract.payer_did == PAYER
    assert contract.payee_did == PAYEE
    assert contract.amount == "1000"
    assert contract.asset == "FLOP"
    assert contract.rails == ["paper"]
    assert contract.receipt_outcome == "claimed"

    # The offer_id contract only has the offer frame
    offer_contract = idx.get(offer_id)
    assert offer_contract is not None
    assert offer_contract.state == "proposed"
    assert offer_contract.offer is not None


def test_index_handles_refund_branch():
    idx = TclkIndex()
    offer_id = "0xoffer"
    contract_id = "0xcontract"

    idx.ingest_message("tclk-offers", _msg(1, PAYER, _tclk({
        "type": "offer", "from": PAYER, "id": offer_id,
        "amount": "1000", "asset": "FLOP", "role": "payer",
        "lock": "hash", "rails": ["paper"],
        "claimByMs": 1, "expiresMs": 1, "refundAfterMs": 1, "nonce": "n1",
    }), ts="2026-09-07T17:48:00Z"))

    idx.ingest_message("tclk-offers", _msg(2, PAYEE, _tclk({
        "type": "accept", "from": PAYEE, "contract": contract_id,
        "ref": offer_id, "statement": "0xstmt", "nonce": "n2",
    }), ts="2026-09-07T17:48:01Z"))

    idx.ingest_message("tclk-offers", _msg(3, PAYER, _tclk({
        "type": "lock", "from": PAYER, "contract": contract_id,
        "rail": "paper", "ref": "0xlockref",
    }), ts="2026-09-07T17:48:02Z"))

    # No reveal — payee didn't deliver
    idx.ingest_message("tclk-offers", _msg(4, PAYER, _tclk({
        "type": "refund", "from": PAYER, "contract": contract_id,
        "reason": "no reveal before refundAfterMs",
    }), ts="2026-09-07T17:48:03Z"))

    idx.ingest_message("tclk-offers", _msg(5, PAYER, _tclk({
        "type": "receipt", "from": PAYER, "contract": contract_id,
        "outcome": "refunded", "rail": "paper", "ref": "0xlockref",
    }), ts="2026-09-07T17:48:04Z"))

    contract = idx.get(contract_id)
    assert contract.state == "refunded"
    assert contract.receipt_outcome == "refunded"


def test_index_did_stats_aggregates_across_contracts():
    idx = TclkIndex()
    offer1 = "0xoffer1"
    contract1 = "0xcontract1"
    offer2 = "0xoffer2"
    contract2 = "0xcontract2"

    # Deal 1: completed (payee reveals, payer receipts claimed)
    idx.ingest_message("tclk-offers", _msg(1, PAYER, _tclk({
        "type": "offer", "from": PAYER, "id": offer1,
        "amount": "1000", "asset": "FLOP", "role": "payer",
        "lock": "hash", "rails": ["paper"],
        "claimByMs": 1, "expiresMs": 1, "refundAfterMs": 1, "nonce": "n1",
    })))
    idx.ingest_message("tclk-offers", _msg(2, PAYEE, _tclk({
        "type": "accept", "from": PAYEE, "contract": contract1,
        "ref": offer1, "statement": "0xstmt", "nonce": "n2",
    })))
    idx.ingest_message("tclk-offers", _msg(3, PAYER, _tclk({
        "type": "lock", "from": PAYER, "contract": contract1,
        "rail": "paper", "ref": "0xlockref1",
    })))
    idx.ingest_message("tclk-offers", _msg(4, PAYEE, _tclk({
        "type": "reveal", "from": PAYEE, "contract": contract1,
        "secret": "0xsecret1",
    })))
    idx.ingest_message("tclk-offers", _msg(5, PAYER, _tclk({
        "type": "receipt", "from": PAYER, "contract": contract1,
        "outcome": "claimed", "rail": "paper", "ref": "0xlockref1",
    })))

    # Deal 2: refunded (payee doesn't reveal, payer refunds)
    idx.ingest_message("tclk-offers", _msg(6, PAYER, _tclk({
        "type": "offer", "from": PAYER, "id": offer2,
        "amount": "2000", "asset": "FLOP", "role": "payer",
        "lock": "hash", "rails": ["paper"],
        "claimByMs": 1, "expiresMs": 1, "refundAfterMs": 1, "nonce": "n3",
    })))
    idx.ingest_message("tclk-offers", _msg(7, PAYEE, _tclk({
        "type": "accept", "from": PAYEE, "contract": contract2,
        "ref": offer2, "statement": "0xstmt2", "nonce": "n4",
    })))
    idx.ingest_message("tclk-offers", _msg(8, PAYER, _tclk({
        "type": "lock", "from": PAYER, "contract": contract2,
        "rail": "paper", "ref": "0xlockref2",
    })))
    idx.ingest_message("tclk-offers", _msg(9, PAYER, _tclk({
        "type": "refund", "from": PAYER, "contract": contract2,
        "reason": "no reveal",
    })))
    idx.ingest_message("tclk-offers", _msg(10, PAYER, _tclk({
        "type": "receipt", "from": PAYER, "contract": contract2,
        "outcome": "refunded", "rail": "paper", "ref": "0xlockref2",
    })))

    stats = idx.did_stats()

    # Payer stats
    assert stats[PAYER]["offers_made"] == 2
    assert stats[PAYER]["locks_posted"] == 2
    assert stats[PAYER]["refunds_posted"] == 1
    assert stats[PAYER]["receipts_posted"] == 2
    assert stats[PAYER]["receipts_claimed"] == 1
    assert stats[PAYER]["receipts_refunded"] == 1
    assert stats[PAYER]["deals_as_payer"] == 2
    assert stats[PAYER]["deals_refunded_as_payer"] == 1
    assert stats[PAYER]["refund_rate_as_payer"] == 0.5  # 1 refund / 2 deals

    # Payee stats
    assert stats[PAYEE]["offers_accepted"] == 2
    assert stats[PAYEE]["reveals_posted"] == 1  # only in deal 1
    assert stats[PAYEE]["deals_as_payee"] == 2
    assert stats[PAYEE]["deals_completed_as_payee"] == 1  # deal 1 claimed


def test_index_snapshot_sorts_contracts_by_last_activity_desc():
    idx = TclkIndex()
    idx.ingest_message("tclk-offers", _msg(1, PAYER, _tclk({
        "type": "offer", "from": PAYER, "id": "0xold",
        "amount": "1", "asset": "FLOP", "role": "payer",
        "lock": "hash", "rails": ["paper"],
        "claimByMs": 1, "expiresMs": 1, "refundAfterMs": 1, "nonce": "n1",
    }), ts="2026-09-01T00:00:00Z"))
    idx.ingest_message("tclk-offers", _msg(2, PAYER, _tclk({
        "type": "offer", "from": PAYER, "id": "0xnew",
        "amount": "1", "asset": "FLOP", "role": "payer",
        "lock": "hash", "rails": ["paper"],
        "claimByMs": 1, "expiresMs": 1, "refundAfterMs": 1, "nonce": "n2",
    }), ts="2026-09-07T00:00:00Z"))
    idx.ingest_message("tclk-offers", _msg(3, PAYER, _tclk({
        "type": "offer", "from": PAYER, "id": "0xmid",
        "amount": "1", "asset": "FLOP", "role": "payer",
        "lock": "hash", "rails": ["paper"],
        "claimByMs": 1, "expiresMs": 1, "refundAfterMs": 1, "nonce": "n3",
    }), ts="2026-09-04T00:00:00Z"))

    snap = idx.snapshot()
    ids = [c["contract_id"] for c in snap["contracts"]]
    assert ids == ["0xnew", "0xmid", "0xold"]


def test_index_snapshot_top_limit_caps_output():
    idx = TclkIndex()
    for i in range(10):
        idx.ingest_message("tclk-offers", _msg(i, PAYER, _tclk({
            "type": "offer", "from": PAYER, "id": f"0xoffer{i}",
            "amount": "1", "asset": "FLOP", "role": "payer",
            "lock": "hash", "rails": ["paper"],
            "claimByMs": 1, "expiresMs": 1, "refundAfterMs": 1, "nonce": f"n{i}",
        })))
    snap = idx.snapshot(top_limit=3)
    assert snap["total_contracts"] == 10
    assert len(snap["contracts"]) == 3


def test_index_snapshot_aggregate_counts():
    idx = TclkIndex()
    idx.ingest_message("tclk-offers", _msg(1, PAYER, _tclk({
        "type": "offer", "from": PAYER, "id": "0xoffer1",
        "amount": "1000", "asset": "FLOP", "role": "payer",
        "lock": "hash", "rails": ["paper", "flop-htlc"],
        "claimByMs": 1, "expiresMs": 1, "refundAfterMs": 1, "nonce": "n1",
    })))
    idx.ingest_message("tclk-offers", _msg(2, PAYER, _tclk({
        "type": "offer", "from": PAYER, "id": "0xoffer2",
        "amount": "2000", "asset": "PAPER", "role": "payer",
        "lock": "hash", "rails": ["paper"],
        "claimByMs": 1, "expiresMs": 1, "refundAfterMs": 1, "nonce": "n2",
    })))

    snap = idx.snapshot()
    assert snap["contracts_by_state"] == {"proposed": 2}
    assert snap["contracts_by_rail"] == {"paper": 2, "flop-htlc": 1}
    assert snap["contracts_by_asset"] == {"FLOP": 1, "PAPER": 1}


def test_index_handles_missing_fields():
    idx = TclkIndex()
    # Empty message
    idx.ingest_message("tclk-offers", {})
    # No from
    idx.ingest_message("tclk-offers", {"text": _tclk({"type": "offer", "id": "0x1"}), "ts": "t", "seq": 1})

    snap = idx.snapshot()
    assert snap["total_contracts"] == 1
    contract = idx.get("0x1")
    assert contract is not None
    assert contract.payer_did is None  # no role field
    assert contract.payee_did is None


def test_index_get_by_offer_id():
    idx = TclkIndex()
    idx.ingest_message("tclk-offers", _msg(1, PAYER, _tclk({
        "type": "offer", "from": PAYER, "id": "0xoffer",
        "amount": "1", "asset": "FLOP", "role": "payer",
        "lock": "hash", "rails": ["paper"],
        "claimByMs": 1, "expiresMs": 1, "refundAfterMs": 1, "nonce": "n1",
    })))
    # Look up by offer id
    contract = idx.get_by_offer_id("0xoffer")
    assert contract is not None
    assert contract.contract_id == "0xoffer"
    # Unknown offer id
    assert idx.get_by_offer_id("0xnonexistent") is None


def test_index_handles_unknown_frame_type_gracefully():
    """Unknown frame types are counted but don't crash."""
    idx = TclkIndex()
    idx.ingest_message("tclk-offers", _msg(1, "did:key:z6Mkx", _tclk({
        "type": "future_type_v2", "from": "did:key:z6Mkx", "contract": "0xc",
    })))
    snap = idx.snapshot()
    assert snap["total_frames"] == 1
    assert snap["frames_by_type"]["unknown"] == 1


def test_known_frame_types_complete():
    """Ensure we know all 8 frame types from the SPEC."""
    assert KNOWN_FRAME_TYPES == frozenset({
        "offer", "accept", "lock", "reveal",
        "refund", "cancel", "receipt", "heartbeat",
    })


def test_index_first_offer_wins():
    """If we see multiple offer frames for the same id (replay/echo), the
    first one wins."""
    idx = TclkIndex()
    idx.ingest_message("tclk-offers", _msg(1, PAYER, _tclk({
        "type": "offer", "from": PAYER, "id": "0xoffer",
        "amount": "1000", "asset": "FLOP", "role": "payer",
        "lock": "hash", "rails": ["paper"],
        "claimByMs": 1, "expiresMs": 1, "refundAfterMs": 1, "nonce": "n1",
    })))
    idx.ingest_message("tclk-offers", _msg(2, ATTACKER, _tclk({
        "type": "offer", "from": ATTACKER, "id": "0xoffer",
        "amount": "9999", "asset": "FLOP", "role": "payer",
        "lock": "hash", "rails": ["paper"],
        "claimByMs": 1, "expiresMs": 1, "refundAfterMs": 1, "nonce": "n2",
    })))
    contract = idx.get("0xoffer")
    assert contract.offer is not None
    assert contract.offer["from"] == PAYER  # first one wins
    assert contract.offer["amount"] == "1000"
