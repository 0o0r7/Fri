"""Tests for the kibble module."""

from __future__ import annotations

from collector.kibble import (
    KibbleIndex,
    KibbleJob,
    parse_frame,
)


def _msg(seq: int, frm: str, text: str, ts: str | None = None) -> dict:
    return {
        "seq": seq,
        "from": frm,
        "text": text,
        "ts": ts or f"2026-09-07T17:48:{seq:02d}Z",
    }


# ---------------------------------------------------------------------------
# parse_frame
# ---------------------------------------------------------------------------


def test_parse_frame_job():
    text = "JOB v1 | k22503027d2 | review | Audit data integrity across a dashboard."
    kind, jid, raw, fields = parse_frame(text)
    assert kind == "JOB"
    assert jid == "k22503027d2"
    assert fields["category"] == "review"
    assert fields["prompt"] == "Audit data integrity across a dashboard."


def test_parse_frame_claim():
    text = "CLAIM v1 | k22503027d2 | worker"
    kind, jid, raw, fields = parse_frame(text)
    assert kind == "CLAIM"
    assert jid == "k22503027d2"
    assert fields["role"] == "worker"


def test_parse_frame_result():
    text = "RESULT v1 | k22503027d2 | The system relies on the W3C Trace Context standard..."
    kind, jid, raw, fields = parse_frame(text)
    assert kind == "RESULT"
    assert jid == "k22503027d2"
    assert "W3C Trace Context" in fields["body"]


def test_parse_frame_deliver():
    text = "DELIVER v1 | k22503027d2 | Auto-delivered by VPS agent."
    kind, jid, raw, fields = parse_frame(text)
    assert kind == "DELIVER"
    assert jid == "k22503027d2"
    assert fields["body"] == "Auto-delivered by VPS agent."


def test_parse_frame_attest_with_ref():
    text = "ATTEST v1 | kf3ff87de9b | not | rh:4ef7bd4e11566c5b | The delivery is thin boilerplate."
    kind, jid, raw, fields = parse_frame(text)
    assert kind == "ATTEST"
    assert jid == "kf3ff87de9b"
    assert fields["rating"] == "not"
    assert fields["ref"] == "rh:4ef7bd4e11566c5b"
    assert fields["body"] == "The delivery is thin boilerplate."


def test_parse_frame_attest_without_ref():
    text = "ATTEST v1 | kca707aaa40 | useful | Verified solution via GLM-5.3-Flash reasoning."
    kind, jid, raw, fields = parse_frame(text)
    assert kind == "ATTEST"
    assert jid == "kca707aaa40"
    assert fields["rating"] == "useful"
    assert fields["ref"] is None
    assert fields["body"] == "Verified solution via GLM-5.3-Flash reasoning."


def test_parse_frame_accept():
    text = "ACCEPT v1 | k38ccf45c72 | Empirical verification passed."
    kind, jid, raw, fields = parse_frame(text)
    assert kind == "ACCEPT"
    assert jid == "k38ccf45c72"
    assert fields["body"] == "Empirical verification passed."


def test_parse_frame_rejects_non_kibble():
    assert parse_frame("hello world") is None
    assert parse_frame("gm wagmi") is None
    assert parse_frame("") is None
    assert parse_frame(None) is None  # type: ignore[arg-type]


def test_parse_frame_rejects_no_v1_marker():
    assert parse_frame("JOB v2 | k12345abcdef | review | test") is None
    assert parse_frame("JOB | k12345abcdef | review | test") is None


def test_parse_frame_accepts_extra_whitespace():
    text = "JOB   v1  |   k22503027d2   |   review   |   Audit data."
    kind, jid, raw, fields = parse_frame(text)
    assert kind == "JOB"
    assert jid == "k22503027d2"
    assert fields["category"] == "review"
    assert fields["prompt"] == "Audit data."


def test_parse_frame_body_can_contain_pipes():
    text = "RESULT v1 | k22503027d2 | The answer is: a | b | c"
    kind, jid, raw, fields = parse_frame(text)
    assert kind == "RESULT"
    assert fields["body"] == "The answer is: a | b | c"


# ---------------------------------------------------------------------------
# KibbleJob state machine
# ---------------------------------------------------------------------------


def test_job_state_progresses_posted_to_attested():
    j = KibbleJob(job_id="k12345abcdef")
    assert j.state == "posted"
    j.claims.append({"did": "did:key:a", "ts": "t", "seq": 1, "role": "worker", "raw_text": "x"})
    assert j.state == "claimed"
    j.deliveries.append({"did": "did:key:a", "ts": "t", "seq": 2, "body": "x", "raw_text": "x"})
    assert j.state == "delivered"
    j.results.append({"did": "did:key:a", "ts": "t", "seq": 3, "body": "x", "raw_text": "x"})
    assert j.state == "resulted"
    j.accepts.append({"did": "did:key:b", "ts": "t", "seq": 4, "body": "x", "raw_text": "x"})
    assert j.state == "accepted"
    j.attestations.append({"did": "did:key:b", "ts": "t", "seq": 5, "rating": "useful", "ref": None, "body": "x", "raw_text": "x"})
    assert j.state == "attested"


def test_job_useful_and_not_counts():
    j = KibbleJob(job_id="k12345abcdef")
    j.attestations = [
        {"did": "a", "rating": "useful"},
        {"did": "b", "rating": "useful"},
        {"did": "c", "rating": "not"},
        {"did": "d", "rating": "weird"},  # unknown rating, doesn't count
    ]
    assert j.useful_count == 2
    assert j.not_count == 1


# ---------------------------------------------------------------------------
# KibbleIndex
# ---------------------------------------------------------------------------


def test_index_ignores_non_kibble_messages():
    idx = KibbleIndex()
    idx.ingest_message("kibble", _msg(1, "did:key:z6Mktest", "hello world"))
    idx.ingest_message("kibble", _msg(2, "did:key:z6Mktest", "gm wagmi"))
    snap = idx.snapshot()
    assert snap["total_jobs"] == 0
    assert snap["total_frames"] == 0
    assert snap["total_messages_sampled"] == 2


def test_index_parses_full_job_lifecycle():
    idx = KibbleIndex()
    poster = "did:key:z6Mkposter"
    worker = "did:key:z6Mkworker"
    attester = "did:key:z6Mkattester"

    idx.ingest_message("kibble", _msg(1, poster, "JOB v1 | kaaa001 | build | Build a thing."))
    idx.ingest_message("kibble", _msg(2, worker, "CLAIM v1 | kaaa001 | worker"))
    idx.ingest_message("kibble", _msg(3, worker, "DELIVER v1 | kaaa001 | Built it."))
    idx.ingest_message("kibble", _msg(4, worker, "RESULT v1 | kaaa001 | The thing has 3 parts."))
    idx.ingest_message("kibble", _msg(5, attester, "ATTEST v1 | kaaa001 | useful | rh:abc123 | Good work."))

    snap = idx.snapshot()
    assert snap["total_jobs"] == 1
    assert snap["total_frames"] == 5
    assert snap["frames_by_kind"]["JOB"] == 1
    assert snap["frames_by_kind"]["CLAIM"] == 1
    assert snap["frames_by_kind"]["DELIVER"] == 1
    assert snap["frames_by_kind"]["RESULT"] == 1
    assert snap["frames_by_kind"]["ATTEST"] == 1

    job = snap["jobs"][0]
    assert job["state"] == "attested"
    assert job["category"] == "build"
    assert job["prompt"] == "Build a thing."
    assert job["poster_did"] == poster
    assert job["claims_count"] == 1
    assert job["deliveries_count"] == 1
    assert job["results_count"] == 1
    assert job["attestations_count"] == 1
    assert job["useful_count"] == 1
    assert job["not_count"] == 0
    assert worker in job["claimer_dids"]
    assert worker in job["deliverer_dids"]
    assert attester in job["attester_dids"]


def test_index_handles_multiple_workers_per_job():
    idx = KibbleIndex()
    poster = "did:key:z6Mkposter"
    w1 = "did:key:z6Mkw1"
    w2 = "did:key:z6Mkw2"

    idx.ingest_message("kibble", _msg(1, poster, "JOB v1 | kbbb001 | review | Review this."))
    idx.ingest_message("kibble", _msg(2, w1, "CLAIM v1 | kbbb001 | worker"))
    idx.ingest_message("kibble", _msg(3, w2, "CLAIM v1 | kbbb001 | worker"))
    idx.ingest_message("kibble", _msg(4, w1, "DELIVER v1 | kbbb001 | My review."))
    idx.ingest_message("kibble", _msg(5, w2, "DELIVER v1 | kbbb001 | My review too."))

    job = idx.snapshot()["jobs"][0]
    assert job["claims_count"] == 2
    assert job["deliveries_count"] == 2
    assert set(job["claimer_dids"]) == {w1, w2}
    assert set(job["deliverer_dids"]) == {w1, w2}


def test_index_did_stats_aggregates_across_jobs():
    idx = KibbleIndex()
    poster = "did:key:z6Mkposter"
    worker = "did:key:z6Mkworker"
    attester = "did:key:z6Mkattester"

    # Job 1: worker delivers, attester says useful
    idx.ingest_message("kibble", _msg(1, poster, "JOB v1 | kaaa001 | build | Build."))
    idx.ingest_message("kibble", _msg(2, worker, "CLAIM v1 | kaaa001 | worker"))
    idx.ingest_message("kibble", _msg(3, worker, "DELIVER v1 | kaaa001 | Done."))
    idx.ingest_message("kibble", _msg(4, attester, "ATTEST v1 | kaaa001 | useful | Good."))

    # Job 2: same worker delivers, same attester says not
    idx.ingest_message("kibble", _msg(5, poster, "JOB v1 | kaaa002 | build | Build more."))
    idx.ingest_message("kibble", _msg(6, worker, "CLAIM v1 | kaaa002 | worker"))
    idx.ingest_message("kibble", _msg(7, worker, "DELIVER v1 | kaaa002 | Done again."))
    idx.ingest_message("kibble", _msg(8, attester, "ATTEST v1 | kaaa002 | not | Bad."))

    stats = idx.did_stats()

    assert stats[poster]["jobs_posted"] == 2
    assert stats[poster]["attestations_received_on_posted"] == 2
    assert stats[poster]["useful_received_on_posted"] == 1
    assert stats[poster]["not_received_on_posted"] == 1

    assert stats[worker]["jobs_claimed"] == 2
    assert stats[worker]["deliveries_made"] == 2
    assert stats[worker]["attestations_received_on_delivered"] == 2
    assert stats[worker]["useful_received_on_delivered"] == 1
    assert stats[worker]["not_received_on_delivered"] == 1

    assert stats[attester]["attestations_given"] == 2
    assert stats[attester]["attestations_useful"] == 1
    assert stats[attester]["attestations_not"] == 1


def test_index_snapshot_sorts_jobs_by_last_activity_desc():
    idx = KibbleIndex()
    idx.ingest_message("kibble", _msg(1, "did:key:a", "JOB v1 | kaaa001 | build | Old job.", ts="2026-09-01T00:00:00Z"))
    idx.ingest_message("kibble", _msg(2, "did:key:b", "JOB v1 | kaaa002 | build | New job.", ts="2026-09-07T00:00:00Z"))
    idx.ingest_message("kibble", _msg(3, "did:key:c", "JOB v1 | kaaa003 | build | Middle job.", ts="2026-09-04T00:00:00Z"))

    snap = idx.snapshot()
    job_ids = [j["job_id"] for j in snap["jobs"]]
    assert job_ids == ["kaaa002", "kaaa003", "kaaa001"]


def test_index_snapshot_top_limit_caps_output():
    idx = KibbleIndex()
    for i in range(10):
        idx.ingest_message("kibble", _msg(i, "did:key:a", f"JOB v1 | kaaa{i:03d} | build | Job {i}"))
    snap = idx.snapshot(top_limit=3)
    assert snap["total_jobs"] == 10
    assert len(snap["jobs"]) == 3


def test_index_snapshot_includes_state_and_category_counts():
    idx = KibbleIndex()
    idx.ingest_message("kibble", _msg(1, "did:key:a", "JOB v1 | kaaa001 | build | Build."))
    idx.ingest_message("kibble", _msg(2, "did:key:b", "JOB v1 | kaaa002 | review | Review."))
    idx.ingest_message("kibble", _msg(3, "did:key:c", "JOB v1 | kaaa003 | build | Build 2."))
    idx.ingest_message("kibble", _msg(4, "did:key:d", "CLAIM v1 | kaaa001 | worker"))

    snap = idx.snapshot()
    assert snap["jobs_by_state"] == {"claimed": 1, "posted": 2}
    assert snap["jobs_by_category"] == {"build": 2, "review": 1}


def test_index_get_returns_none_for_unknown():
    idx = KibbleIndex()
    assert idx.get("knonexistent") is None


def test_index_handles_missing_fields():
    idx = KibbleIndex()
    # Empty message
    idx.ingest_message("kibble", {})
    # No from
    idx.ingest_message("kibble", {"text": "JOB v1 | kaaa001 | build | x", "ts": "t", "seq": 1})
    # No ts, no seq
    idx.ingest_message("kibble", {"from": "did:key:a", "text": "JOB v1 | kaaa002 | build | x"})

    snap = idx.snapshot()
    assert snap["total_jobs"] == 2
    # First job has no poster (parsed, but no from)
    job = next(j for j in snap["jobs"] if j["job_id"] == "kaaa001")
    assert job["poster_did"] is None


def test_index_first_job_frame_wins_for_poster():
    """If we see multiple JOB frames for the same id (replay/echo), the
    first one wins for poster_did, poster_ts, category, prompt."""
    idx = KibbleIndex()
    idx.ingest_message("kibble", _msg(1, "did:key:a", "JOB v1 | kaaa001 | build | Original."))
    idx.ingest_message("kibble", _msg(2, "did:key:b", "JOB v1 | kaaa001 | review | Echo."))

    job = idx.get("kaaa001")
    assert job.poster_did == "did:key:a"
    assert job.category == "build"
    assert job.prompt == "Original."
