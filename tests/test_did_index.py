"""Tests for the DID index module."""

from __future__ import annotations

from collector.did_index import DidIndex, DidStats


def _msg(seq: int, frm: str, text: str = "hello", ts: str | None = None) -> dict:
    return {
        "seq": seq,
        "from": frm,
        "text": text,
        "ts": ts or f"2026-09-07T17:48:{seq:02d}Z",
    }


# ---------------------------------------------------------------------------
# DidStats
# ---------------------------------------------------------------------------


def test_didstats_ignores_empty_text_in_avg():
    s = DidStats(did="did:key:z6Mktest")
    s.ingest("lobby", "2026-09-07T17:48:00Z", "")
    s.ingest("lobby", "2026-09-07T17:48:01Z", "hello world")
    out = s.to_dict()
    assert out["messages_signed"] == 2
    # (0 + 11) / 2 = 5.5
    assert out["avg_message_length"] == 5.5


def test_didstats_tracks_first_and_last_seen():
    s = DidStats(did="did:key:z6Mktest")
    s.ingest("lobby", "2026-09-07T17:48:00Z", "first")
    s.ingest("lobby", "2026-09-07T18:00:00Z", "second")
    s.ingest("lobby", "2026-09-07T17:30:00Z", "earlier")  # earlier ts
    out = s.to_dict()
    assert out["first_seen"] == "2026-09-07T17:30:00Z"
    assert out["last_active"] == "2026-09-07T18:00:00Z"


def test_didstats_breakdown_sorted_by_count_desc():
    s = DidStats(did="did:key:z6Mktest")
    s.ingest("a", "2026-09-07T17:48:00Z", "x")
    s.ingest("a", "2026-09-07T17:48:01Z", "x")
    s.ingest("a", "2026-09-07T17:48:02Z", "x")
    s.ingest("b", "2026-09-07T17:48:03Z", "x")
    s.ingest("c", "2026-09-07T17:48:04Z", "x")
    s.ingest("c", "2026-09-07T17:48:05Z", "x")
    out = s.to_dict()
    # breakdown is a dict; check sorted order by extracting items
    items = list(out["rooms_breakdown"].items())
    assert items == [("a", 3), ("c", 2), ("b", 1)]


# ---------------------------------------------------------------------------
# DidIndex
# ---------------------------------------------------------------------------


def test_didindex_ignores_unsigned_messages():
    idx = DidIndex()
    idx.ingest_message("lobby", _msg(1, "~alice", "hi"))
    idx.ingest_message("lobby", _msg(2, "did:key:z6Mkreal", "signed"))
    snap = idx.snapshot()
    assert snap["total_dids"] == 1
    assert snap["dids"][0]["did"] == "did:key:z6Mkreal"


def test_didindex_ignores_malformed_from():
    idx = DidIndex()
    idx.ingest_message("lobby", _msg(1, "", "no from"))
    idx.ingest_message("lobby", _msg(2, "not-a-did", "weird from"))
    idx.ingest_message("lobby", {"from": 42, "text": "x", "ts": "x"})  # non-str
    snap = idx.snapshot()
    assert snap["total_dids"] == 0


def test_didindex_aggregates_across_rooms():
    idx = DidIndex()
    did_a = "did:key:z6MkrealA"
    did_b = "did:key:z6MkrealB"
    idx.ingest_message("lobby", _msg(1, did_a, "hello"))
    idx.ingest_message("lobby", _msg(2, did_b, "world"))
    idx.ingest_message("tclk-offers", _msg(3, did_a, "tclk1 {...}"))
    idx.ingest_message("kibble", _msg(4, did_a, "CLAIM v1 | k123 | worker"))

    snap = idx.snapshot()
    assert snap["total_dids"] == 2
    assert snap["total_messages_sampled"] == 4

    a = next(d for d in snap["dids"] if d["did"] == did_a)
    b = next(d for d in snap["dids"] if d["did"] == did_b)
    assert a["messages_signed"] == 3
    assert a["rooms_active_in"] == 3
    assert set(a["rooms"]) == {"lobby", "tclk-offers", "kibble"}
    assert b["messages_signed"] == 1
    assert b["rooms_active_in"] == 1


def test_didindex_top_dids_sorts_by_messages_signed():
    idx = DidIndex()
    did_a = "did:key:z6Mkaaa"
    did_b = "did:key:z6Mkbbb"
    did_c = "did:key:z6Mkccc"

    # B has the most messages
    for i in range(5):
        idx.ingest_message("lobby", _msg(i, did_b, "x"))
    for i in range(3):
        idx.ingest_message("lobby", _msg(i + 10, did_a, "y"))
    for i in range(2):
        idx.ingest_message("lobby", _msg(i + 20, did_c, "z"))

    snap = idx.snapshot(top_limit=10)
    assert [d["did"] for d in snap["dids"]] == [did_b, did_a, did_c]


def test_didindex_top_dids_tiebreaker_by_rooms_active_in():
    idx = DidIndex()
    did_a = "did:key:z6Mkaaa"
    did_b = "did:key:z6Mkbbb"

    # Both have 2 messages; B is in 2 rooms, A is in 1 room
    idx.ingest_message("lobby", _msg(1, did_a, "x"))
    idx.ingest_message("lobby", _msg(2, did_a, "x"))
    idx.ingest_message("lobby", _msg(1, did_b, "y"))
    idx.ingest_message("other", _msg(2, did_b, "y"))

    snap = idx.snapshot(top_limit=10)
    # Tie on messages_signed (2 each), B wins on rooms_active_in (2 vs 1)
    assert snap["dids"][0]["did"] == did_b
    assert snap["dids"][1]["did"] == did_a


def test_didindex_top_limit_caps_output():
    idx = DidIndex()
    for i in range(10):
        idx.ingest_message("lobby", _msg(i, f"did:key:z6Mkdid{i:02d}", "x"))
    snap = idx.snapshot(top_limit=3)
    assert snap["total_dids"] == 10  # total is uncapped
    assert len(snap["dids"]) == 3  # but the list is capped


def test_didindex_fingerprint_is_16_hex_chars():
    idx = DidIndex()
    did = "did:key:z6Mktest"
    idx.ingest_message("lobby", _msg(1, did, "x"))
    snap = idx.snapshot()
    fp = snap["dids"][0]["fingerprint"]
    assert isinstance(fp, str)
    assert len(fp) == 16
    assert all(c in "0123456789abcdef" for c in fp)


def test_didindex_handles_missing_fields():
    idx = DidIndex()
    # Missing ts, missing text, missing from
    idx.ingest_message("lobby", {})
    idx.ingest_message("lobby", {"from": "did:key:z6Mktest"})  # no ts, no text
    snap = idx.snapshot()
    assert snap["total_dids"] == 1
    d = snap["dids"][0]
    assert d["messages_signed"] == 1
    assert d["first_seen"] is None
    assert d["last_active"] is None
    assert d["avg_message_length"] == 0.0


def test_didindex_get_returns_none_for_unknown():
    idx = DidIndex()
    assert idx.get("did:key:z6Mknonexistent") is None


def test_didindex_ingest_messages_bulk():
    idx = DidIndex()
    did = "did:key:z6Mktest"
    msgs = [_msg(i, did, f"msg {i}") for i in range(5)]
    idx.ingest_messages("lobby", msgs)
    snap = idx.snapshot()
    assert snap["total_messages_sampled"] == 5
    assert snap["dids"][0]["messages_signed"] == 5
