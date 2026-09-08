"""Simple spam / low-signal heuristics for Technocore messages."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List

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
