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


# ---------------------------------------------------------------------------
# Spam integrity (v1.1) — per-DID low-signal tracking
# ---------------------------------------------------------------------------

from collector.spam import CATEGORY_CLEAN, CATEGORY_PHRASE  # noqa: E402

FLOOD_TEMPLATE = "Another day, another check-in. The decentralized AI vision is compelling."


def test_ingest_message_classifies_low_signal_categories():
    idx = DidIndex()
    did = "did:key:z6MkSpam"
    idx.ingest_message("lobby", _msg(1, did, FLOOD_TEMPLATE + " · aa1"))
    idx.ingest_message("lobby", _msg(2, did, FLOOD_TEMPLATE + " · bb2"))
    out = idx.get(did).to_dict()
    # Message 1 hits the "check-in" phrase rule; message 2 repeats the DID's
    # own template (stronger signal, checked before phrase). Categories are
    # exclusive, so counters never double-subtract.
    assert out["phrase_msgs"] == 1
    assert out["template_msgs"] == 1
    assert out["low_signal_msgs"] == 2
    assert out["spam_ratio"] == 1.0


def test_didstats_rate_buckets_peak_and_prune():
    s = DidStats(did="did:key:z6Mktest")
    # 12 messages inside one minute, non-machine room → peak = 12.
    for i in range(12):
        s.ingest("lobby", f"2026-09-14T07:10:{i:02d}Z", f"distinct observation {i} about protocol {i}")
    assert s.peak_msgs_per_min == 12
    # Buckets prune to the rolling window (only one minute present here).
    assert len(s._rate_buckets) == 1
    assert "rate_burst" in s.spam_flags


def test_machine_room_rate_exempt():
    s = DidStats(did="did:key:z6MkMachine")
    for i in range(30):
        s.ingest("d-blockrewards-feed", f"2026-09-14T07:10:{i:02d}Z" if i < 60 else "", f"task {i} dispatch ok")
    assert s.peak_msgs_per_min == 0
    assert "rate_burst" not in s.spam_flags


def test_rate_buckets_prune_to_window():
    s = DidStats(did="did:key:z6Mktest")
    # One message per minute across 25 minutes → buckets keep last 10.
    for m in range(25):
        s.ingest("lobby", f"2026-09-14T07:{m:02d}:00Z", f"steady chatter minute {m} no repeats here")
    assert len(s._rate_buckets) <= 10
    assert s.peak_msgs_per_min == 1
    assert "rate_burst" not in s.spam_flags


def test_to_dict_publishes_spam_fields():
    idx = DidIndex()
    did = "did:key:z6MkClean"
    for i in range(3):
        idx.ingest_message("technocore", _msg(i, did, f"Distinct point {chr(97+i)}: signature batching differs from note batching."))
    out = idx.get(did).to_dict()
    for key in ("phrase_msgs", "template_msgs", "campaign_msgs", "low_signal_msgs",
                "spam_ratio", "peak_msgs_per_min", "spam_flags"):
        assert key in out
    assert out["spam_ratio"] == 0.0
    assert out["spam_flags"] == []


def test_hydrate_legacy_payload_without_spam_fields():
    idx = DidIndex()
    payload = {
        "total_dids": 1,
        "total_messages_sampled": 2,
        "dids": [{
            "did": "did:key:z6MkLegacy",
            "first_seen": "2026-09-07T17:48:13Z",
            "last_active": "2026-09-08T19:20:00Z",
            "messages_signed": 7,
            "rooms_breakdown": {"lobby": 7},
            "avg_message_length": 42.0,
        }],
    }
    restored = idx.hydrate(payload)
    assert restored == 1
    entry = idx.get("did:key:z6MkLegacy").to_dict()
    assert entry["phrase_msgs"] == 0
    assert entry["template_msgs"] == 0
    assert entry["campaign_msgs"] == 0
    assert entry["spam_flags"] == []


def test_hydrate_roundtrips_spam_counters():
    idx = DidIndex()
    did = "did:key:z6MkSpam"
    for i in range(30):
        idx.ingest_message("lobby", _msg(i, did, FLOOD_TEMPLATE + f" · t{i}"))
    payload = idx.snapshot()
    idx2 = DidIndex()
    idx2.hydrate(payload)
    a = idx.get(did).to_dict()
    b = idx2.get(did).to_dict()
    for key in ("phrase_msgs", "template_msgs", "campaign_msgs", "low_signal_msgs", "spam_ratio"):
        assert a[key] == b[key], key


def test_snapshot_total_counts_unchanged_by_spam():
    # Low-signal messages still count toward messages_sampled / unique DIDs —
    # nothing is deleted; only the reputation activity component excludes them.
    idx = DidIndex()
    idx.ingest_message("lobby", _msg(1, "did:key:z6MkSpam", FLOOD_TEMPLATE))
    assert idx.total_dids == 1
    assert idx.snapshot()["total_messages_sampled"] == 1


# ---------------------------------------------------------------------------
# observation_window — audit P0 window metadata
# ---------------------------------------------------------------------------


def test_observation_window_empty_index_is_safe():
    idx = DidIndex()
    w = idx.observation_window()
    assert w["window_start"] is None
    assert w["window_end"] is None
    assert w["messages_observed"] == 0
    assert w["unique_dids_observed"] == 0


def test_observation_window_covers_min_max_across_dids():
    idx = DidIndex()
    # b1: earlier window | b2: extends both ends | b3: inside b2's range
    idx.ingest_message("lobby", _msg(1, "did:key:b1", ts="2026-09-07T10:00:00Z"))
    idx.ingest_message("lobby", _msg(2, "did:key:b2", ts="2026-09-08T09:00:00Z"))
    idx.ingest_message("lobby", _msg(3, "did:key:b2", ts="2026-09-09T23:00:00Z"))
    idx.ingest_message("lobby", _msg(4, "did:key:b3", ts="2026-09-08T12:00:00Z"))
    w = idx.observation_window()
    assert w["window_start"] == "2026-09-07T10:00:00Z"  # b1 first_seen
    assert w["window_end"] == "2026-09-09T23:00:00Z"  # b2 last_active
    assert w["messages_observed"] == 4
    assert w["unique_dids_observed"] == 3


def test_observation_window_ignores_dids_without_timestamps():
    # A DID hydrated from a legacy baseline without ts fields must not
    # crash the window computation nor produce a bogus range.
    idx = DidIndex()
    idx.hydrate({
        "total_messages_sampled": 7,
        "dids": [{"did": "did:key:noTs", "messages_signed": 7}],
    })
    idx.ingest_message("lobby", _msg(1, "did:key:withTs", ts="2026-09-09T08:00:00Z"))
    w = idx.observation_window()
    assert w["window_start"] == "2026-09-09T08:00:00Z"
    assert w["window_end"] == "2026-09-09T08:00:00Z"
    assert w["messages_observed"] == 8  # hydrated 7 + 1 live
    assert w["unique_dids_observed"] == 2
