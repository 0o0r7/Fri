"""Unit tests for spam heuristics."""

from collector.spam import detect_spam_patterns


def test_empty():
    assert detect_spam_patterns([]) == 0.5


def test_clean_messages():
    msgs = [
        {"text": "We should coordinate the next offer frame on the signed lane."},
        {"text": "I verified the signature — looks correct."},
        {"text": "Topic proposal: agent memory patterns for Technocore."},
    ]
    score = detect_spam_patterns(msgs)
    assert score < 0.3


def test_spammy_messages():
    msgs = [
        {"text": "checking in for airdrop"},
        {"text": "check-in $FLOP"},
        {"text": "present for the airdrop"},
        {"text": "gm"},
        {"text": "gm"},
    ]
    score = detect_spam_patterns(msgs)
    assert score > 0.5
