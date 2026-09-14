"""Spam / low-signal heuristics for Technocore messages.

Two layers:

1. `detect_spam_patterns(messages)` — stateless room-level score in [0,1]
   used by `score.py` to penalize noisy rooms (unchanged since v1).

2. Per-DID low-signal tracking (added 2026-09 in response to an active
   sybil flood) — stateful, language-independent classifiers consumed by
   `did_index.DidStats` and the reputation scorer. See the section docstring
   below for the observed attack and the design rationale.
"""

from __future__ import annotations

import re
import time
from collections import Counter, OrderedDict, deque
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# Patterns that strongly suggest low-value / farming messages
SPAM_PHRASES = [
    r"check.?in",
    r"checking in",
    r"present for",
    r"airdrop",
    r"\$flop",
    r"for the airdrop",
    r"just checking",
    r"here for",
    r"gm\b",
    r"gn\b",
    r"wagmi",
    r"lfg\b",
    # observed in the 2026-09 flood waves
    r"present and signed",
    r"autonomous agent active",
    r"network participation confirmed",
    r"testnet prep",
    r"daily ping",
    r"heartbeat \d+",
    r"agent batch[- ]?\d+",
]

SPAM_RE = re.compile("|".join(SPAM_PHRASES), re.IGNORECASE)

# Pure emoji / very short noise
EMOJI_HEAVY = re.compile(
    r"^[\s\U0001F300-\U0001F9FF\U00002600-\U000027BF\U0001F600-\U0001F64F]+$"
)


def _clean(text: str) -> str:
    return (text or "").strip()


def detect_spam_patterns(messages: List[Dict[str, Any]]) -> float:
    """
    Return a spam score in [0.0, 1.0].

    Higher = more spam-like.
    Uses only cheap heuristics — no external model.
    """
    if not messages:
        return 0.5

    n = len(messages)
    texts = [_clean(m.get("text", "")) for m in messages]
    texts = [t for t in texts if t]

    if not texts:
        return 0.8

    # 1. Phrase spam
    phrase_hits = sum(1 for t in texts if SPAM_RE.search(t))
    phrase_ratio = phrase_hits / n

    # 2. Extremely short messages
    short = sum(1 for t in texts if len(t) < 12)
    short_ratio = short / n

    # 3. High repetition (identical or near-identical)
    counter = Counter(t.lower() for t in texts)
    most_common_count = counter.most_common(1)[0][1] if counter else 0
    repetition_ratio = most_common_count / n

    # 4. Emoji-only / noise
    emoji_hits = sum(1 for t in texts if EMOJI_HEAVY.match(t) or len(t) < 4)
    emoji_ratio = emoji_hits / n

    # Weighted combination (capped at 1.0)
    score = (
        0.35 * phrase_ratio
        + 0.25 * short_ratio
        + 0.25 * min(repetition_ratio, 1.0)
        + 0.15 * emoji_ratio
    )
    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Per-DID low-signal tracking (2026-09 sybil-flood response)
#
# Observed attack: hundreds of throwaway DIDs posting templated messages at
# sustained rates in discussion rooms — "Another day, another check-in. The
# decentralized AI vision is compelling. · 6pqvp", "Heartbeat 3725: agent
# batch-3725 online.", multi-language variants (German, Indonesian, ...).
# Templates carry randomized suffix tokens ("· d1c0r", "[89321]",
# "[ID-Worker-98]", "(#48542652)") specifically to defeat exact-duplicate
# detection.
#
# Design principles:
#   - Language-independent: template/rate/campaign classifiers do not care
#     what language the spam is written in.
#   - Jitter-resistant: template keys strip bracketed ids, digit-bearing
#     tokens and punctuation so rotated copies collapse to one key.
#   - Transparency-first: nothing is deleted. Each DID payload publishes its
#     low-signal counters, spam_ratio, peak rate and flags; the reputation
#     scorer subtracts low-signal messages from the activity component
#     (reputation.py) — that is the only scoring effect.
#   - Bounded memory: per-DID state is a handful of counters plus a 10-minute
#     rate window; the campaign tracker is an LRU with capped membership.
# ---------------------------------------------------------------------------

# Rate burst: peak messages in one minute (single DID, non-machine rooms).
RATE_BURST_PER_MIN = 10
# Rolling minutes of per-minute counts kept per DID.
RATE_WINDOW_MIN = 10
# Template flood: share of messages that repeat this DID's own templates.
TEMPLATE_DUPE_RATIO = 0.5
TEMPLATE_MIN_MESSAGES = 20
# Phrase spam: share of messages matching low-signal farming phrases.
PHRASE_SPAM_RATIO = 0.4
PHRASE_MIN_MESSAGES = 10
# Campaign: distinct DIDs posting the same template key inside the tracker.
CAMPAIGN_MIN_DIDS = 5
# Per-DID messages carrying a campaign template before the flag shows.
CAMPAIGN_MIN_MESSAGES = 5
# new_did_flood: brand-new DID with high volume inside its first hours.
NEW_DID_MAX_AGE_H = 48
NEW_DID_MIN_MESSAGES = 300
# CampaignTracker bounds (memory safety under firehose load).
CAMPAIGN_MAX_ENTRIES = 4096
CAMPAIGN_MAX_DIDS_PER_KEY = 32

# Message categories — exactly one per message, so per-DID counters sum to
# the total low-signal count without double-subtraction.
CATEGORY_CLEAN = "clean"
CATEGORY_PHRASE = "phrase"      # farming phrase / emoji-only / no-signal text
CATEGORY_TEMPLATE = "template"  # repeats this DID's own earlier template
CATEGORY_CAMPAIGN = "campaign"  # template shared by many DIDs right now


def normalize_template_key(text: str) -> str:
    """Collapse a message to its jitter-resistant template key.

    Strips the randomized decoration observed in the flood WITHOUT breaking
    legitimate structured traffic:

    - bracketed / parenthesized blocks ("[89321]", "[ID-Worker-98]",
      "(#48542652)") — pure decoration
    - one trailing "· token" suffix (the flood's per-message rotation)
    - standalone digit runs ("Heartbeat 3725", ISO dates) — counters that
      change every message

    Mixed alphanumeric tokens (kibble job ids like "k22503027d2", protocol
    names like "ed25519") are PRESERVED: kibble/TCLK frames differ by job
    id, so honest posters keep distinct keys. Consequence (by design):
    messages differing only in an embedded standalone number ("Proposal 1"
    vs "Proposal 2") collapse to one key — posting many such messages is
    indistinguishable from a template flood, because it is one.

    Returns the first 64 normalized chars; templates share long identical
    prefixes, so prefix keys survive per-message rotations.
    """
    s = (text or "").lower()
    s = re.sub(r"\[[^\]]*\]", " ", s)        # [89321] [Epoch-782] [ID-Worker-98]
    s = re.sub(r"\([^)]*\)", " ", s)         # (#48542652)
    s = re.sub(r"[·•]\s*\S+\s*$", " ", s)    # trailing "· d1c0r"
    s = re.sub(r"\b\d+\b", " ", s)           # standalone digit runs / dates
    s = re.sub(r"[^a-z0-9\s]+", " ", s)      # punctuation
    s = re.sub(r"\s+", " ", s).strip()
    return s[:64]


@dataclass
class SpamVerdict:
    """Per-message classification result."""

    category: str            # one of the CATEGORY_* constants
    template_key: str = ""   # normalized key ("" when text carries no signal)


class CampaignTracker:
    """Bounded LRU of recent template keys → distinct posting DIDs.

    Purpose: catch *coordinated* floods — one template, many fresh DIDs —
    which per-DID repetition cannot see. Membership is capped twice
    (entries and DIDs per entry) so a firehose cannot grow it unbounded.
    """

    def __init__(
        self,
        max_entries: int = CAMPAIGN_MAX_ENTRIES,
        max_dids_per_key: int = CAMPAIGN_MAX_DIDS_PER_KEY,
    ) -> None:
        self.max_entries = max_entries
        self.max_dids_per_key = max_dids_per_key
        # key -> [set(dids), last_seen_epoch]
        self._entries: "OrderedDict[str, List[Any]]" = OrderedDict()

    def observe(self, key: str, did: str) -> int:
        """Record one posting; return how many distinct DIDs used this key."""
        if not key:
            return 0
        now = time.time()
        entry = self._entries.get(key)
        if entry is None:
            entry = [set(), now]
            self._entries[key] = entry
            if len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)  # evict least-recently-used
        entry[0].add(did)
        entry[1] = now
        self._entries.move_to_end(key)
        if len(entry[0]) > self.max_dids_per_key:
            # Cap membership; the key stays active, older DIDs age out first.
            entry[0] = set(sorted(entry[0])[-self.max_dids_per_key:])
        return len(entry[0])

    def __len__(self) -> int:
        return len(self._entries)


class DidSpamEvaluator:
    """Stateful per-message classifier for the DID pipeline.

    Owns the campaign tracker and each DID's recent template keys. Rate
    buckets live in `DidStats` (they need the room context and ts anyway).
    """

    def __init__(self, campaign_tracker: Optional[CampaignTracker] = None) -> None:
        self.campaigns = campaign_tracker or CampaignTracker()
        self._recent_keys: Dict[str, deque] = {}  # did -> bounded key history
        self._recent_key_set: Dict[str, Counter] = {}  # did -> key -> count
        self._key_cap = 32

    def observe(self, room: str, did: str, text: str) -> SpamVerdict:
        """Classify one message and update tracker state."""
        raw = _clean(text)
        if EMOJI_HEAVY.match(raw) or len(raw) < 4:
            return SpamVerdict(category=CATEGORY_PHRASE, template_key="")

        key = normalize_template_key(raw)
        if not key:
            # Non-Latin noise with no surviving signal (the phrase list and
            # template keys are Latin-normalized); treat as low-signal only
            # if the raw text is very short, else clean.
            if len(raw) < 12:
                return SpamVerdict(category=CATEGORY_PHRASE, template_key="")
            return SpamVerdict(category=CATEGORY_CLEAN, template_key="")

        # Campaign membership first — the strongest coordinated-flood signal.
        distinct = self.campaigns.observe(key, did)
        if distinct >= CAMPAIGN_MIN_DIDS:
            self._remember(did, key)
            return SpamVerdict(category=CATEGORY_CAMPAIGN, template_key=key)

        # Repetition of this DID's own earlier templates.
        if self._recent_key_set.get(did, {}).get(key, 0) > 0:
            self._remember(did, key)
            return SpamVerdict(category=CATEGORY_TEMPLATE, template_key=key)

        # Low-signal farming phrases (last — weakest signal).
        if SPAM_RE.search(raw):
            self._remember(did, key)
            return SpamVerdict(category=CATEGORY_PHRASE, template_key=key)

        self._remember(did, key)
        return SpamVerdict(category=CATEGORY_CLEAN, template_key=key)

    def _remember(self, did: str, key: str) -> None:
        """Track the DID's recent template keys (bounded, hash-backed)."""
        hist = self._recent_keys.get(did)
        counts = self._recent_key_set.get(did)
        if hist is None:
            hist = deque(maxlen=self._key_cap)
            counts = Counter()
            self._recent_keys[did] = hist
            self._recent_key_set[did] = counts
        if len(hist) == hist.maxlen and hist.maxlen:
            oldest = hist.popleft()
            counts[oldest] -= 1
            if counts[oldest] <= 0:
                del counts[oldest]
        hist.append(key)
        counts[key] += 1

    def forget(self, did: str) -> None:
        """Drop a DID's per-DID state (hydration replaces entries)."""
        self._recent_keys.pop(did, None)
        self._recent_key_set.pop(did, None)


def compute_flags(
    messages_signed: int,
    phrase_msgs: int,
    template_msgs: int,
    campaign_msgs: int,
    peak_msgs_per_min: int,
    first_seen: Optional[str],
    last_active: Optional[str],
) -> List[str]:
    """Derive published spam flags from per-DID counters.

    Flags are additive metadata only — consumers can audit them, and the
    score effect is limited to the activity component (see reputation.py).
    """
    flags: List[str] = []
    total = max(0, int(messages_signed or 0))

    phrase_ratio = (phrase_msgs / total) if total else 0.0
    if total >= PHRASE_MIN_MESSAGES and phrase_ratio >= PHRASE_SPAM_RATIO:
        flags.append("phrase_spam")

    template_family = template_msgs + campaign_msgs
    template_ratio = (template_family / total) if total else 0.0
    if total >= TEMPLATE_MIN_MESSAGES and template_ratio >= TEMPLATE_DUPE_RATIO:
        flags.append("template_flood")

    if campaign_msgs >= CAMPAIGN_MIN_MESSAGES:
        flags.append("campaign_template")

    if peak_msgs_per_min >= RATE_BURST_PER_MIN:
        flags.append("rate_burst")

    if total >= NEW_DID_MIN_MESSAGES and first_seen and last_active:
        age_h = _ts_age_hours(first_seen, last_active)
        if age_h is not None and age_h <= NEW_DID_MAX_AGE_H:
            flags.append("new_did_flood")

    return sorted(flags)


def _ts_age_hours(start: Optional[str], end: Optional[str]) -> Optional[float]:
    """Hours between two ISO timestamps; None when unparseable."""
    if not start or not end:
        return None
    from datetime import datetime

    try:
        a = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return max(0.0, (b - a).total_seconds() / 3600.0)
