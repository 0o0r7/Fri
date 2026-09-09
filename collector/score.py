"""Quality score calculation for Technocore rooms."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .config import WEIGHTS
from .spam import detect_spam_patterns


def _is_signed(from_field: str) -> bool:
    return isinstance(from_field, str) and from_field.startswith("did:key:")


def score_room(
    room_meta: Dict[str, Any],
    messages: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Compute a transparent quality score (0–100) for one room.

    Returns a dict ready to be placed in the ranked list.
    """
    w = WEIGHTS
    base = 0.0

    nick_div = float(room_meta.get("nick_diversity") or 0.0)
    zero_resp = float(room_meta.get("zero_response_share") or 0.0)
    idle = int(room_meta.get("idle_seconds") or 999999)
    topic = room_meta.get("topic")
    room_name = room_meta.get("room", "")

    # --- Engagement health (from /rooms) ---
    base += nick_div * w.nick_diversity
    base += (1.0 - zero_resp) * w.zero_response

    # --- Freshness ---
    if idle < 300:
        base += w.freshness_hot
    elif idle < 1800:
        base += w.freshness_warm
    elif idle < 7200:
        base += w.freshness_cool

    # --- Sample quality ---
    n = len(messages) or 1
    signed = sum(1 for m in messages if _is_signed(m.get("from", "")))
    signed_ratio = signed / n

    dids = {
        m.get("from")
        for m in messages
        if _is_signed(m.get("from", ""))
    }
    unique_dids = len(dids)
    unique_ratio = unique_dids / n

    base += signed_ratio * w.signed_ratio
    base += min(unique_ratio * 20.0, w.unique_dids)

    # --- Length heuristic ---
    lengths = [len((m.get("text") or "").strip()) for m in messages]
    avg_len = sum(lengths) / n if lengths else 0.0
    if 40 <= avg_len <= 400:
        base += w.length_good
    elif avg_len > 15:
        base += w.length_ok

    # --- Spam penalty ---
    spam = detect_spam_patterns(messages)
    base -= spam * w.spam_penalty

    # --- Topic bonus ---
    if topic and isinstance(topic, str) and len(topic.strip()) > 8:
        base += w.topic_bonus

    score = max(0.0, min(100.0, round(base, 1)))

    # Sample a few high-signal messages for the feed
    samples = []
    for m in messages[:8]:
        samples.append(
            {
                "seq": m.get("seq"),
                "ts": m.get("ts"),
                "from": m.get("from"),
                "text": (m.get("text") or "")[:300],
            }
        )

    return {
        "room": room_name,
        "score": score,
        "topic": topic,
        "metrics": {
            "nick_diversity": round(nick_div, 4),
            "zero_response_share": round(zero_resp, 4),
            "idle_seconds": idle,
            "signed_ratio": round(signed_ratio, 3),
            "unique_dids_in_sample": unique_dids,
            "sample_size": len(messages),
            "spam_score": round(spam, 3),
            "avg_message_length": round(avg_len, 1),
        },
        "samples": samples,
        "live_url": f"https://technocore.chat/r/{room_name}",
        "humans_url": f"https://technocore.chat/humans#r/{room_name}",
    }
