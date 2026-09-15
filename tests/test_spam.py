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


# ---------------------------------------------------------------------------
# Per-DID low-signal tracking (2026-09 sybil-flood response)
# ---------------------------------------------------------------------------

from collections import OrderedDict  # noqa: E402

from collector.spam import (  # noqa: E402
    CAMPAIGN_MAX_ENTRIES,
    CAMPAIGN_MIN_DIDS,
    CATEGORY_CAMPAIGN,
    CATEGORY_CLEAN,
    CATEGORY_PHRASE,
    CATEGORY_TEMPLATE,
    RATE_BURST_PER_MIN,
    CampaignTracker,
    DidSpamEvaluator,
    compute_flags,
    normalize_template_key,
)

FLOOD_TEMPLATE = "Another day, another check-in. The decentralized AI vision is compelling."


def test_template_key_collapses_jitter_suffixes():
    assert normalize_template_key(FLOOD_TEMPLATE + " · 6pqvp") == normalize_template_key(
        FLOOD_TEMPLATE + " · z18rr"
    )


def test_template_key_collapses_bracketed_and_counter_ids():
    a = normalize_template_key("Heartbeat 3725: agent batch-3725 online. Tracking FLOP network growth.")
    b = normalize_template_key("Heartbeat 9001: agent batch-9001 online. Tracking FLOP network growth.")
    assert a == b
    assert normalize_template_key("batch local identity persisted ahead of flop testnet [89321]") == \
        normalize_template_key("batch local identity persisted ahead of flop testnet [99999]")


def test_template_key_preserves_mixed_alnum_ids():
    # Kibble/TCLK frames differ by job id — honest posters must keep distinct keys.
    assert normalize_template_key("JOB k22503027d2 review: audit the dashboard") != \
        normalize_template_key("JOB k77777777x2 review: audit the dashboard")
    # Protocol names survive.
    assert "ed25519" in normalize_template_key("Ed25519 signature verified. The cryptographic layer is solid.")


def test_campaign_tracker_counts_distinct_dids():
    tr = CampaignTracker()
    key = normalize_template_key(FLOOD_TEMPLATE)
    for i in range(CAMPAIGN_MIN_DIDS - 1):
        assert tr.observe(key, f"did:key:z6Mk{i}") < CAMPAIGN_MIN_DIDS
    assert tr.observe(key, "did:key:z6MkFinal") >= CAMPAIGN_MIN_DIDS
    # Same DID reposting does not increase distinct count.
    assert tr.observe(key, "did:key:z6MkFinal") >= CAMPAIGN_MIN_DIDS


def test_campaign_tracker_lru_bound():
    tr = CampaignTracker(max_entries=10)
    for i in range(50):
        tr.observe(f"key-{i}", "did:key:z6MkOne")
    assert len(tr) <= 10


def test_evaluator_phrase_category():
    ev = DidSpamEvaluator()
    v = ev.observe("lobby", "did:key:z6MkA", "checking in for the airdrop wave")
    assert v.category == CATEGORY_PHRASE


def test_evaluator_template_repeat_per_did():
    ev = DidSpamEvaluator()
    did = "did:key:z6MkA"
    neutral = "Node synced. Curious to see what the next network upgrade brings."
    v1 = ev.observe("lobby", did, neutral + " · aaa1")
    v2 = ev.observe("lobby", did, neutral + " · bbb2")
    assert v1.category == CATEGORY_CLEAN  # first sighting is clean
    assert v2.category == CATEGORY_TEMPLATE


def test_evaluator_farming_phrase_wins_on_first_sighting():
    # The flood template contains "check-in": the phrase rule fires even on
    # the first message, before any template repetition exists.
    ev = DidSpamEvaluator()
    v1 = ev.observe("lobby", "did:key:z6MkA", FLOOD_TEMPLATE + " · aaa1")
    assert v1.category == CATEGORY_PHRASE


def test_evaluator_campaign_once_five_dids_share_template():
    ev = DidSpamEvaluator()
    key_text = FLOOD_TEMPLATE + " · tail"
    # Four distinct DIDs are not yet a campaign.
    for i in range(4):
        ev.observe("lobby", f"did:key:z6Mk{i}", key_text)
    v_fifth = ev.observe("lobby", "did:key:z6MkFifth", key_text)
    assert v_fifth.category == CATEGORY_CAMPAIGN


def test_evaluator_noise_and_short_texts():
    ev = DidSpamEvaluator()
    assert ev.observe("lobby", "did:key:z6MkA", "🚀🚀🚀").category == CATEGORY_PHRASE
    assert ev.observe("lobby", "did:key:z6MkA", "ok").category == CATEGORY_PHRASE


def test_evaluator_key_memory_is_bounded():
    ev = DidSpamEvaluator()
    did = "did:key:z6MkA"
    for i in range(200):
        ev.observe("lobby", did, f"unique message number {i} about widget {i % 9} design")
    hist, counts = ev._recent[did]
    assert len(hist) <= ev._key_cap
    assert len(counts) <= ev._key_cap


def test_evaluator_did_tracking_is_lru_capped():
    """Per-DID state must not grow with the network size — the unbounded
    dict OOM-killed the Render instance. Beyond the cap, the least
    recently active DID is evicted (graceful classifier degradation)."""
    ev = DidSpamEvaluator()
    for i in range(20000):
        did = f"did:key:z6MkFiller{i:06d}"
        ev.observe("lobby", did, f"distinct filler message body number {i}")
    assert len(ev._recent) <= 16384 + 1  # cap (+1 while inserting)
    # The very first filler was evicted; a fresh DID survives.
    assert f"did:key:z6MkFiller000000" not in ev._recent
    assert f"did:key:z6MkFiller019999" in ev._recent
    # Re-activating an old DID re-inserts it cleanly (no stale duplicate).
    ev._remember("did:key:z6MkFiller000000", "some/key")
    assert "did:key:z6MkFiller000000" in ev._recent


def test_compute_flags_phrase_spam():
    flags = compute_flags(20, phrase_msgs=10, template_msgs=0, campaign_msgs=0,
                          peak_msgs_per_min=0, first_seen=None, last_active=None)
    assert "phrase_spam" in flags


def test_compute_flags_template_and_campaign():
    flags = compute_flags(60, phrase_msgs=0, template_msgs=40, campaign_msgs=10,
                          peak_msgs_per_min=0, first_seen=None, last_active=None)
    assert "template_flood" in flags and "campaign_template" in flags


def test_compute_flags_rate_burst():
    flags = compute_flags(30, 0, 0, 0, peak_msgs_per_min=RATE_BURST_PER_MIN,
                          first_seen=None, last_active=None)
    assert "rate_burst" in flags


def test_compute_flags_new_did_flood():
    flags = compute_flags(400, 0, 0, 0, 0,
                          first_seen="2026-09-14T06:00:00Z",
                          last_active="2026-09-14T09:00:00Z")
    assert "new_did_flood" in flags
    # Old DID with same volume: no flag.
    flags_old = compute_flags(400, 0, 0, 0, 0,
                              first_seen="2026-08-01T06:00:00Z",
                              last_active="2026-09-14T09:00:00Z")
    assert "new_did_flood" not in flags_old


def test_compute_flags_clean_did():
    assert compute_flags(40, 0, 0, 0, 1, None, None) == []
