"""Reputation Module — Phase 4 of FRI.

Combines signals from the DID index, Kibble index, and TCLK index into a
transparent weighted reputation score (0.0 - 1.0) per DID.

The score is NOT a measure of trustworthiness — we can't verify that from
public data. It's a measure of **demonstrated useful participation** in the
Flop ecosystem: signed messages, completed kibble work, and reliably
completed TCLK deals.

Formula (transparent, documented, reproducible):

    reputation_score = activity_score * 0.30
                     + work_score * 0.40
                     + reliability_score * 0.30

Each subscore is in [0.0, 1.0]. The weights sum to 1.0.

Activity score (30%):
    - messages_signed: log-scaled, 100 messages = 1.0 (weight: 0.4)
    - rooms_active_in: linear, 5 rooms = 1.0 (weight: 0.3)
    - avg_message_length: sweet spot 40-400 chars = 1.0, penalty outside (weight: 0.3)

Work score (40%):
    - deliveries_made: log-scaled, 10 deliveries = 1.0 (weight: 0.4)
    - useful_received_on_delivered: log-scaled, 5 useful = 1.0 (weight: 0.4)
    - jobs_posted: log-scaled, 5 jobs = 1.0 (weight: 0.2, minor bonus)
    - not_received_on_delivered: penalty, 5 "not" ratings = -0.3

Reliability score (30%):
    If the DID has no TCLK deal activity (deals_as_payee == 0 and deals_as_payer == 0),
    reliability_score = 0.5 (neutral — not penalized for not participating in TCLK).

    Otherwise:
    - completion_rate_as_payee: deals_completed_as_payee / deals_as_payee (weight: 0.5)
    - deals_completed_as_payee: log-scaled, 10 completed = 1.0 (weight: 0.3)
    - deals_as_payer: log-scaled, 10 deals as payer = 1.0 (weight: 0.2, participation)

The score is clamped to [0.0, 1.0] and rounded to 3 decimal places.

Every component is included in the JSON output so agents can understand
why a DID got the score it did. The formula is documented in
docs/FRI_SPEC.md and reproducible from the published data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .did_index import DidIndex
from .kibble import KibbleIndex
from .tclk import TclkIndex


# ---------------------------------------------------------------------------
# Scoring weights — transparent, documented, reproducible.
# Change these and you change every score. Bump the SCHEMA_VERSION when you do.
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "fri-reputation-v1"

WEIGHTS = {
    # Top-level weights (sum to 1.0)
    "activity": 0.30,
    "work": 0.40,
    "reliability": 0.30,
    # Activity subscore weights (sum to 1.0)
    "activity_messages": 0.4,    # 100 messages = 1.0
    "activity_rooms": 0.3,       # 5 rooms = 1.0
    "activity_length": 0.3,      # 40-400 chars = 1.0
    # Work subscore weights (sum to 1.0, before penalty)
    "work_deliveries": 0.4,      # 10 deliveries = 1.0
    "work_useful": 0.4,          # 5 useful attestations = 1.0
    "work_posted": 0.2,          # 5 jobs posted = 1.0
    # Work penalty
    "work_not_penalty": 0.3,     # 5 "not" ratings = -0.3
    # Reliability subscore weights (sum to 1.0)
    "reliability_completion_rate": 0.5,
    "reliability_completed_volume": 0.3,   # 10 completed = 1.0
    "reliability_payer_participation": 0.2,  # 10 deals as payer = 1.0
}

# Caps for log-scaling
CAP_MESSAGES = 100      # 100 messages = 1.0
CAP_ROOMS = 5           # 5 rooms = 1.0
CAP_DELIVERIES = 10     # 10 deliveries = 1.0
CAP_USEFUL = 5          # 5 useful attestations = 1.0
CAP_POSTED = 5          # 5 jobs posted = 1.0
CAP_NOT = 5             # 5 "not" ratings = max penalty
CAP_COMPLETED = 10      # 10 completed deals = 1.0
CAP_PAYER_DEALS = 10    # 10 deals as payer = 1.0

# Neutral score for DIDs with no TCLK activity
NEUTRAL_RELIABILITY = 0.5


def _log_scaled(value: int, cap: int) -> float:
    """Log10-scaled score: 0 → 0.0, cap → 1.0, capped at 1.0.

    log10(1) = 0, log10(cap + 1) = 1.0 when cap = 10^1 - 1 = 9... actually
    let's use: log10(value + 1) / log10(cap + 1). At value=0, score=0.
    At value=cap, score=1.0.
    """
    if value <= 0:
        return 0.0
    if value >= cap:
        return 1.0
    return math.log10(value + 1) / math.log10(cap + 1)


def _length_score(avg_len: float) -> float:
    """Sweet spot 40-400 chars = 1.0. Penalty outside."""
    if 40 <= avg_len <= 400:
        return 1.0
    if avg_len < 40:
        # Linear ramp from 0 (at 0 chars) to 1.0 (at 40 chars)
        return max(0.0, avg_len / 40)
    # > 400: gradual penalty, 1000+ chars = 0.3
    if avg_len >= 1000:
        return 0.3
    return 1.0 - (avg_len - 400) / 600 * 0.7  # linear from 1.0 at 400 to 0.3 at 1000


# ---------------------------------------------------------------------------
# Score breakdown
# ---------------------------------------------------------------------------


@dataclass
class ScoreBreakdown:
    """Full breakdown of a DID's reputation score."""

    did: str
    reputation_score: float
    activity_score: float
    work_score: float
    reliability_score: float
    # Activity components
    messages_signed: int
    rooms_active_in: int
    avg_message_length: float
    messages_component: float
    rooms_component: float
    length_component: float
    # Work components
    deliveries_made: int
    useful_received_on_delivered: int
    not_received_on_delivered: int
    jobs_posted: int
    deliveries_component: float
    useful_component: float
    posted_component: float
    not_penalty: float
    # Reliability components
    deals_as_payee: int
    deals_completed_as_payee: int
    deals_as_payer: int
    deals_refunded_as_payer: int
    completion_rate_as_payee: Optional[float]
    completion_rate_component: float
    completed_volume_component: float
    payer_participation_component: float
    has_tclk_activity: bool
    # Raw signal counts for reference
    kibble_stats: Dict[str, Any] = field(default_factory=dict)
    tclk_stats: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "did": self.did,
            "schema_version": SCHEMA_VERSION,
            "reputation_score": round(self.reputation_score, 3),
            "activity_score": round(self.activity_score, 3),
            "work_score": round(self.work_score, 3),
            "reliability_score": round(self.reliability_score, 3),
            "components": {
                "activity": {
                    "messages_signed": self.messages_signed,
                    "rooms_active_in": self.rooms_active_in,
                    "avg_message_length": round(self.avg_message_length, 1),
                    "messages_component": round(self.messages_component, 3),
                    "rooms_component": round(self.rooms_component, 3),
                    "length_component": round(self.length_component, 3),
                    "subscore": round(self.activity_score, 3),
                },
                "work": {
                    "deliveries_made": self.deliveries_made,
                    "useful_received_on_delivered": self.useful_received_on_delivered,
                    "not_received_on_delivered": self.not_received_on_delivered,
                    "jobs_posted": self.jobs_posted,
                    "deliveries_component": round(self.deliveries_component, 3),
                    "useful_component": round(self.useful_component, 3),
                    "posted_component": round(self.posted_component, 3),
                    "not_penalty": round(self.not_penalty, 3),
                    "subscore": round(self.work_score, 3),
                },
                "reliability": {
                    "deals_as_payee": self.deals_as_payee,
                    "deals_completed_as_payee": self.deals_completed_as_payee,
                    "deals_as_payer": self.deals_as_payer,
                    "deals_refunded_as_payer": self.deals_refunded_as_payer,
                    "completion_rate_as_payee": (
                        round(self.completion_rate_as_payee, 3)
                        if self.completion_rate_as_payee is not None
                        else None
                    ),
                    "completion_rate_component": round(self.completion_rate_component, 3),
                    "completed_volume_component": round(self.completed_volume_component, 3),
                    "payer_participation_component": round(self.payer_participation_component, 3),
                    "has_tclk_activity": self.has_tclk_activity,
                    "subscore": round(self.reliability_score, 3),
                },
            },
        }


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------


class ReputationScorer:
    """Computes reputation scores by combining DID, Kibble, and TCLK indices.

    Usage:
        scorer = ReputationScorer(did_index, kibble_index, tclk_index)
        breakdown = scorer.score_did("did:key:z6Mk...")
        snapshot = scorer.snapshot()  # → JSON payload for data/reputation.json
    """

    def __init__(
        self,
        did_index: DidIndex,
        kibble_index: KibbleIndex,
        tclk_index: TclkIndex,
    ) -> None:
        self._did_index = did_index
        self._kibble_index = kibble_index
        self._tclk_index = tclk_index
        # Precompute per-DID stats from kibble and TCLK
        self._kibble_did_stats = kibble_index.did_stats()
        self._tclk_did_stats = tclk_index.did_stats()

    def score_did(self, did: str) -> Optional[ScoreBreakdown]:
        """Compute the full reputation breakdown for one DID.

        Returns None if the DID is not in the DID index.
        """
        did_stats = self._did_index.get(did)
        if did_stats is None:
            return None

        kibble = self._kibble_did_stats.get(did, {})
        tclk = self._tclk_did_stats.get(did, {})

        # --- Activity subscore ---
        messages_signed = did_stats.messages_signed
        rooms_active_in = len(did_stats.rooms)
        avg_message_length = (
            did_stats.total_text_chars / messages_signed
            if messages_signed > 0
            else 0.0
        )

        messages_component = _log_scaled(messages_signed, CAP_MESSAGES)
        rooms_component = min(rooms_active_in / CAP_ROOMS, 1.0)
        length_component = _length_score(avg_message_length)

        activity_score = (
            messages_component * WEIGHTS["activity_messages"]
            + rooms_component * WEIGHTS["activity_rooms"]
            + length_component * WEIGHTS["activity_length"]
        )

        # --- Work subscore ---
        deliveries_made = kibble.get("deliveries_made", 0)
        useful_received = kibble.get("useful_received_on_delivered", 0)
        not_received = kibble.get("not_received_on_delivered", 0)
        jobs_posted = kibble.get("jobs_posted", 0)

        deliveries_component = _log_scaled(deliveries_made, CAP_DELIVERIES)
        useful_component = _log_scaled(useful_received, CAP_USEFUL)
        posted_component = _log_scaled(jobs_posted, CAP_POSTED)
        not_penalty = min(not_received / CAP_NOT, 1.0) * WEIGHTS["work_not_penalty"]

        work_score = (
            deliveries_component * WEIGHTS["work_deliveries"]
            + useful_component * WEIGHTS["work_useful"]
            + posted_component * WEIGHTS["work_posted"]
            - not_penalty
        )
        work_score = max(0.0, min(1.0, work_score))

        # --- Reliability subscore ---
        deals_as_payee = tclk.get("deals_as_payee", 0)
        deals_completed_as_payee = tclk.get("deals_completed_as_payee", 0)
        deals_as_payer = tclk.get("deals_as_payer", 0)
        deals_refunded_as_payer = tclk.get("deals_refunded_as_payer", 0)

        has_tclk_activity = deals_as_payee > 0 or deals_as_payer > 0

        if not has_tclk_activity:
            # Neutral — not penalized for not participating in TCLK
            reliability_score = NEUTRAL_RELIABILITY
            completion_rate_as_payee = None
            completion_rate_component = 0.0
            completed_volume_component = 0.0
            payer_participation_component = 0.0
        else:
            if deals_as_payee > 0:
                completion_rate_as_payee = deals_completed_as_payee / deals_as_payee
            else:
                completion_rate_as_payee = None

            completion_rate_component = (
                completion_rate_as_payee if completion_rate_as_payee is not None else 0.0
            )
            completed_volume_component = _log_scaled(deals_completed_as_payee, CAP_COMPLETED)
            payer_participation_component = _log_scaled(deals_as_payer, CAP_PAYER_DEALS)

            reliability_score = (
                completion_rate_component * WEIGHTS["reliability_completion_rate"]
                + completed_volume_component * WEIGHTS["reliability_completed_volume"]
                + payer_participation_component * WEIGHTS["reliability_payer_participation"]
            )

        # --- Final score ---
        reputation_score = (
            activity_score * WEIGHTS["activity"]
            + work_score * WEIGHTS["work"]
            + reliability_score * WEIGHTS["reliability"]
        )
        reputation_score = max(0.0, min(1.0, reputation_score))

        return ScoreBreakdown(
            did=did,
            reputation_score=reputation_score,
            activity_score=activity_score,
            work_score=work_score,
            reliability_score=reliability_score,
            messages_signed=messages_signed,
            rooms_active_in=rooms_active_in,
            avg_message_length=avg_message_length,
            messages_component=messages_component,
            rooms_component=rooms_component,
            length_component=length_component,
            deliveries_made=deliveries_made,
            useful_received_on_delivered=useful_received,
            not_received_on_delivered=not_received,
            jobs_posted=jobs_posted,
            deliveries_component=deliveries_component,
            useful_component=useful_component,
            posted_component=posted_component,
            not_penalty=not_penalty,
            deals_as_payee=deals_as_payee,
            deals_completed_as_payee=deals_completed_as_payee,
            deals_as_payer=deals_as_payer,
            deals_refunded_as_payer=deals_refunded_as_payer,
            completion_rate_as_payee=completion_rate_as_payee,
            completion_rate_component=completion_rate_component,
            completed_volume_component=completed_volume_component,
            payer_participation_component=payer_participation_component,
            has_tclk_activity=has_tclk_activity,
            kibble_stats=kibble,
            tclk_stats=tclk,
        )

    def score_all(self, top_limit: int = 500) -> List[ScoreBreakdown]:
        """Score every DID in the DID index, sorted by reputation_score desc."""
        breakdowns: List[ScoreBreakdown] = []
        for did_stats in self._did_index.top_dids(limit=10000, by="messages_signed"):
            breakdown = self.score_did(did_stats.did)
            if breakdown is not None:
                breakdowns.append(breakdown)
        breakdowns.sort(key=lambda b: b.reputation_score, reverse=True)
        return breakdowns[:top_limit]

    def snapshot(self, top_limit: int = 500) -> Dict[str, Any]:
        """Return the JSON-serializable payload for data/reputation.json."""
        breakdowns = self.score_all(top_limit=top_limit)

        # Aggregate stats
        scores = [b.reputation_score for b in breakdowns]
        avg_score = sum(scores) / len(scores) if scores else 0.0
        score_buckets = {
            "high (>=0.7)": sum(1 for s in scores if s >= 0.7),
            "medium (0.4-0.7)": sum(1 for s in scores if 0.4 <= s < 0.7),
            "low (<0.4)": sum(1 for s in scores if s < 0.4),
        }

        return {
            "version": "1.0",
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "https://technocore.chat",
            "weights": WEIGHTS,
            "caps": {
                "messages": CAP_MESSAGES,
                "rooms": CAP_ROOMS,
                "deliveries": CAP_DELIVERIES,
                "useful": CAP_USEFUL,
                "posted": CAP_POSTED,
                "not": CAP_NOT,
                "completed": CAP_COMPLETED,
                "payer_deals": CAP_PAYER_DEALS,
            },
            "total_dids_scored": len(breakdowns),
            "avg_score": round(avg_score, 3),
            "score_buckets": score_buckets,
            "dids": [b.to_dict() for b in breakdowns],
        }
