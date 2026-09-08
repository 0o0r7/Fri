"""Unit tests for quality scoring."""

from collector.score import score_room


def test_high_quality_room():
    meta = {
        "room": "good-room",
        "nick_diversity": 0.92,
        "zero_response_share": 0.01,
        "idle_seconds": 60,
        "topic": "real agent coordination discussion",
        "window": 40,
    }
    messages = [
        {
            "seq": 1,
            "ts": "2026-09-07T08:00:00Z",
            "from": "did:key:z6Mkabcdef",
            "text": "Let's design a better mailbox pattern for agents.",
        },
        {
            "seq": 2,
            "ts": "2026-09-07T08:01:00Z",
            "from": "did:key:z6Mkuvwxyz",
            "text": "Agreed. Signed lane only makes sense for ownership claims.",
        },
        {
            "seq": 3,
            "ts": "2026-09-07T08:02:00Z",
            "from": "did:key:z6Mk123456",
            "text": "I can write a short patterns.md example if useful.",
        },
    ]
    result = score_room(meta, messages)
    assert result["score"] >= 60
    assert result["room"] == "good-room"
    assert "metrics" in result
    assert result["metrics"]["signed_ratio"] == 1.0


def test_low_quality_room():
    meta = {
        "room": "spam-room",
        "nick_diversity": 0.1,
        "zero_response_share": 0.8,
        "idle_seconds": 50000,
        "topic": None,
        "window": 20,
    }
    messages = [
        {"from": "~bot1", "text": "checking in for airdrop"},
        {"from": "~bot2", "text": "check-in $FLOP"},
        {"from": "~bot1", "text": "gm"},
        {"from": "~bot3", "text": "present for airdrop"},
    ]
    result = score_room(meta, messages)
    assert result["score"] < 40
