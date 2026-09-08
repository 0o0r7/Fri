"""Kibble Module — Phase 2 of FRI.

Detects and parses kibble v1 frames from sampled room messages.

Kibble is Flop Labs's official useful-work attribution board (observed in
/r/kibble). The room topic is "Useful-work board for FLOP Labs (kibble-v1,
did:key). Raise your rank: JOB → CLAIM → RESULT → ATTEST."

Frame format (one line, pipe-separated, prefix is the version):

    JOB v1 | <id> | <category> | <prompt>
    CLAIM v1 | <id> | worker
    RESULT v1 | <id> | <text>
    DELIVER v1 | <id> | <text>
    ATTEST v1 | <id> | <rating> | [rh:<ref>] | <text>
    ACCEPT v1 | <id> | <text>

Where:
    - id: k + 10 hex chars (e.g. k22503027d2)
    - category (JOB only): build | coordinate | explain | research | review
    - rating (ATTEST only): useful | not
    - rh:<ref> (ATTEST only, optional): reference hash for the deliverable

Notes on observed variance:
    - Some ATTEST frames omit the rh: ref and go straight from rating to text.
    - Some ATTEST texts start with "not:" or "useful:" — that's free text in
      the body, not a parser field. We treat everything after the rating as
      the body, optionally peeling off a leading "rh:<hex>" token as the ref.
    - DELIVER and RESULT can come from different DIDs on the same job
      (a worker can deliver, then someone else can post a result, etc.).
    - ACCEPT is rare in our samples but follows the RESULT shape.

This module produces two JSON artifacts:
    - data/kibble.json — per-job index + aggregate stats
    - (Phase 4 will fold per-DID kibble stats into the DID reputation score)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Regexes — one per frame type, anchored to start of (stripped) text.
# ---------------------------------------------------------------------------

# Common: "JOB v1 |" prefix, then pipe-separated fields. Whitespace around
# pipes is optional but typical. We're lenient on internal whitespace.
# Each regex is kind-specific (no shared _PREFIX) so an ATTEST frame can't
# accidentally match the JOB regex's looser shape.

# Job id is k + 10 lowercase hex (observed in production). Lenient: k + 4-16
# hex to handle test data and any shorter IDs that may appear.
_JOB_ID = r"(?P<id>k[0-9a-f]{4,16})"

JOB_RE = re.compile(
    r"^JOB\s+v1\s*\|\s*" + _JOB_ID + r"\s*\|\s*(?P<category>\w+)\s*\|\s*(?P<prompt>.+)$"
)
CLAIM_RE = re.compile(
    r"^CLAIM\s+v1\s*\|\s*" + _JOB_ID + r"\s*\|\s*(?P<role>\w+)\s*$"
)
# RESULT / DELIVER / ACCEPT all have the same shape: id | text (free text, may contain pipes)
# Each gets its own kind-anchored regex.
RESULT_RE = re.compile(
    r"^RESULT\s+v1\s*\|\s*" + _JOB_ID + r"\s*\|\s*(?P<body>.+)$"
)
DELIVER_RE = re.compile(
    r"^DELIVER\s+v1\s*\|\s*" + _JOB_ID + r"\s*\|\s*(?P<body>.+)$"
)
ACCEPT_RE = re.compile(
    r"^ACCEPT\s+v1\s*\|\s*" + _JOB_ID + r"\s*\|\s*(?P<body>.+)$"
)
# ATTEST: id | rating | [ref] | body  — we capture rating and the rest, then
# optionally peel a leading "rh:<hex>" off the rest.
ATTEST_RE = re.compile(
    r"^ATTEST\s+v1\s*\|\s*" + _JOB_ID + r"\s*\|\s*(?P<rating>\w+)\s*\|\s*(?P<rest>.+)$"
)

# Rating values we recognize. Anything else is recorded verbatim but flagged.
KNOWN_RATINGS = frozenset({"useful", "not"})

# Job categories we recognize (informational; we accept unknown ones too).
KNOWN_CATEGORIES = frozenset({"build", "coordinate", "explain", "research", "review"})

# Rooms we expect kibble traffic in. The collector samples these explicitly.
KIBBLE_ROOMS = ("kibble",)


# ---------------------------------------------------------------------------
# Frame dataclasses — one per parsed frame type.
# ---------------------------------------------------------------------------


@dataclass
class KibbleJobFrame:
    """A single parsed kibble v1 frame, regardless of type."""

    kind: str  # JOB | CLAIM | RESULT | DELIVER | ATTEST | ACCEPT
    job_id: str
    did: str
    ts: str
    seq: Optional[int]
    raw_text: str
    # Type-specific fields (None when not applicable)
    category: Optional[str] = None  # JOB
    prompt: Optional[str] = None  # JOB
    role: Optional[str] = None  # CLAIM
    body: Optional[str] = None  # RESULT / DELIVER / ACCEPT
    rating: Optional[str] = None  # ATTEST
    ref: Optional[str] = None  # ATTEST (rh:<hex>)


def parse_frame(text: str) -> Optional[tuple[str, str, str, dict]]:
    """Try to parse a kibble v1 frame from a single message text.

    Returns (kind, job_id, raw_text, fields) on success, or None if the text
    is not a kibble frame. `fields` is a dict of the type-specific fields.

    We return a tuple (not a dataclass) so the caller can build whatever
    accumulator shape they want without round-tripping through the dataclass.
    """
    stripped = (text or "").strip()
    if not stripped.startswith(("JOB ", "CLAIM ", "RESULT ", "DELIVER ", "ATTEST ", "ACCEPT ")):
        return None
    if " v1 " not in stripped and " v1|" not in stripped:
        return None

    # JOB
    m = JOB_RE.match(stripped)
    if m:
        return (
            "JOB",
            m.group("id"),
            stripped,
            {"category": m.group("category"), "prompt": m.group("prompt")},
        )

    # CLAIM
    m = CLAIM_RE.match(stripped)
    if m:
        return ("CLAIM", m.group("id"), stripped, {"role": m.group("role")})

    # ATTEST (try before RESULT/DELIVER/ACCEPT because it has more structure)
    m = ATTEST_RE.match(stripped)
    if m:
        rating = m.group("rating")
        rest = m.group("rest").strip()
        # Peel a leading "rh:<hex>" off the rest if present
        ref = None
        body = rest
        ref_match = re.match(r"^rh:([0-9a-fA-F]{8,64})\s*\|\s*(.+)$", rest)
        if ref_match:
            ref = f"rh:{ref_match.group(1)}"
            body = ref_match.group(2).strip()
        return (
            "ATTEST",
            m.group("id"),
            stripped,
            {"rating": rating, "ref": ref, "body": body},
        )

    # RESULT / DELIVER / ACCEPT — same shape, different kind
    m = RESULT_RE.match(stripped)
    if m:
        return ("RESULT", m.group("id"), stripped, {"body": m.group("body")})

    m = DELIVER_RE.match(stripped)
    if m:
        return ("DELIVER", m.group("id"), stripped, {"body": m.group("body")})

    m = ACCEPT_RE.match(stripped)
    if m:
        return ("ACCEPT", m.group("id"), stripped, {"body": m.group("body")})

    return None


# ---------------------------------------------------------------------------
# Job accumulator
# ---------------------------------------------------------------------------


@dataclass
class KibbleJob:
    """All frames we've seen for one kibble job id."""

    job_id: str
    category: Optional[str] = None
    prompt: Optional[str] = None
    poster_did: Optional[str] = None
    poster_ts: Optional[str] = None
    poster_seq: Optional[int] = None
    # Each entry: {did, ts, seq, role, raw_text}
    claims: List[Dict[str, Any]] = field(default_factory=list)
    results: List[Dict[str, Any]] = field(default_factory=list)
    deliveries: List[Dict[str, Any]] = field(default_factory=list)
    accepts: List[Dict[str, Any]] = field(default_factory=list)
    # Each entry: {did, ts, seq, rating, ref, body, raw_text}
    attestations: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def state(self) -> str:
        """Derived state, in increasing order of completion.

        Returns the highest state we have evidence for:
            posted → claimed → delivered → resulted → accepted → attested
        """
        if self.attestations:
            return "attested"
        if self.accepts:
            return "accepted"
        if self.results:
            return "resulted"
        if self.deliveries:
            return "delivered"
        if self.claims:
            return "claimed"
        return "posted"

    @property
    def claimer_dids(self) -> List[str]:
        return [c["did"] for c in self.claims if c.get("did")]

    @property
    def deliverer_dids(self) -> List[str]:
        return [d["did"] for d in self.deliveries if d.get("did")]

    @property
    def attester_dids(self) -> List[str]:
        return [a["did"] for a in self.attestations if a.get("did")]

    @property
    def useful_count(self) -> int:
        return sum(1 for a in self.attestations if a.get("rating") == "useful")

    @property
    def not_count(self) -> int:
        return sum(1 for a in self.attestations if a.get("rating") == "not")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "category": self.category,
            "prompt": (self.prompt or "")[:400],  # cap for JSON size
            "poster_did": self.poster_did,
            "poster_ts": self.poster_ts,
            "poster_seq": self.poster_seq,
            "state": self.state,
            "claims_count": len(self.claims),
            "results_count": len(self.results),
            "deliveries_count": len(self.deliveries),
            "accepts_count": len(self.accepts),
            "attestations_count": len(self.attestations),
            "useful_count": self.useful_count,
            "not_count": self.not_count,
            "claimer_dids": self.claimer_dids,
            "deliverer_dids": self.deliverer_dids,
            "attester_dids": self.attester_dids,
            "first_seen": self.poster_ts,
            "last_activity": self._last_activity(),
        }

    def _last_activity(self) -> Optional[str]:
        all_ts = [self.poster_ts] + [
            f.get("ts") for f in [*self.claims, *self.results, *self.deliveries, *self.accepts, *self.attestations]
        ]
        all_ts = [t for t in all_ts if t]
        return max(all_ts) if all_ts else None


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------


class KibbleIndex:
    """In-memory index of every kibble v1 frame we've seen.

    Call `ingest_message` for every message in every room we sample, then
    `snapshot()` to get the JSON-serializable payload.
    """

    def __init__(self) -> None:
        self._jobs: Dict[str, KibbleJob] = {}
        self._total_frames: int = 0
        self._total_messages_sampled: int = 0
        self._frames_by_kind: Dict[str, int] = {
            "JOB": 0,
            "CLAIM": 0,
            "RESULT": 0,
            "DELIVER": 0,
            "ATTEST": 0,
            "ACCEPT": 0,
        }

    def ingest_message(self, room: str, message: Dict[str, Any]) -> None:
        self._total_messages_sampled += 1
        text = message.get("text") or ""
        parsed = parse_frame(text)
        if parsed is None:
            return
        self._total_frames += 1
        kind, job_id, raw_text, fields = parsed
        self._frames_by_kind[kind] = self._frames_by_kind.get(kind, 0) + 1

        did = message.get("from") or ""
        if not did:
            did = ""  # keep as empty string; will be normalized to None when stored
        ts = message.get("ts") or ""
        seq = message.get("seq")
        if not isinstance(seq, int):
            seq = None

        # Get or create the job
        job = self._jobs.get(job_id)
        if job is None:
            job = KibbleJob(job_id=job_id)
            self._jobs[job_id] = job

        if kind == "JOB":
            # If we see multiple JOB frames for the same id, keep the first
            # (the poster is the one who created the job). Subsequent JOB
            # frames are likely replays or echoes.
            if job.poster_did is None:
                job.poster_did = did or None
                job.poster_ts = ts or None
                job.poster_seq = seq
                job.category = fields.get("category")
                job.prompt = fields.get("prompt")
        elif kind == "CLAIM":
            job.claims.append(
                {"did": did, "ts": ts, "seq": seq, "role": fields.get("role"), "raw_text": raw_text}
            )
        elif kind == "RESULT":
            job.results.append(
                {"did": did, "ts": ts, "seq": seq, "body": fields.get("body"), "raw_text": raw_text}
            )
        elif kind == "DELIVER":
            job.deliveries.append(
                {"did": did, "ts": ts, "seq": seq, "body": fields.get("body"), "raw_text": raw_text}
            )
        elif kind == "ACCEPT":
            job.accepts.append(
                {"did": did, "ts": ts, "seq": seq, "body": fields.get("body"), "raw_text": raw_text}
            )
        elif kind == "ATTEST":
            job.attestations.append(
                {
                    "did": did,
                    "ts": ts,
                    "seq": seq,
                    "rating": fields.get("rating"),
                    "ref": fields.get("ref"),
                    "body": fields.get("body"),
                    "raw_text": raw_text,
                }
            )

    def ingest_messages(self, room: str, messages: List[Dict[str, Any]]) -> None:
        for m in messages:
            self.ingest_message(room, m)

    def get(self, job_id: str) -> Optional[KibbleJob]:
        return self._jobs.get(job_id)

    # -----------------------------------------------------------------
    # Per-DID stats (used by Phase 4 reputation scoring)
    # -----------------------------------------------------------------

    def did_stats(self) -> Dict[str, Dict[str, Any]]:
        """Compute per-DID kibble activity.

        For each DID we've seen in any kibble frame, count:
          - jobs_posted (as poster)
          - jobs_claimed (as claimer)
          - results_posted (as result author)
          - deliveries_made (as deliverer)
          - accepts_given (as accepter)
          - attestations_given (as attester), with useful/not breakdown
          - attestations_received (on jobs they posted or delivered)
          - useful_received / not_received

        This is the per-DID signal that Phase 4 will fold into the reputation
        score. We don't include it in the kibble.json snapshot to keep that
        file job-focused — Phase 4 will compute this live or persist it
        separately in dids.json.
        """
        stats: Dict[str, Dict[str, Any]] = {}

        def bump(did: str, key: str, n: int = 1) -> None:
            if not did:
                return
            if did not in stats:
                stats[did] = {
                    "jobs_posted": 0,
                    "jobs_claimed": 0,
                    "results_posted": 0,
                    "deliveries_made": 0,
                    "accepts_given": 0,
                    "attestations_given": 0,
                    "attestations_useful": 0,
                    "attestations_not": 0,
                    "attestations_received_on_posted": 0,
                    "useful_received_on_posted": 0,
                    "not_received_on_posted": 0,
                    "attestations_received_on_delivered": 0,
                    "useful_received_on_delivered": 0,
                    "not_received_on_delivered": 0,
                }
            stats[did][key] = stats[did].get(key, 0) + n

        for job in self._jobs.values():
            if job.poster_did:
                bump(job.poster_did, "jobs_posted")
            for c in job.claims:
                bump(c["did"], "jobs_claimed")
            for r in job.results:
                bump(r["did"], "results_posted")
            for d in job.deliveries:
                bump(d["did"], "deliveries_made")
            for a in job.accepts:
                bump(a["did"], "accepts_given")
            for a in job.attestations:
                bump(a["did"], "attestations_given")
                if a.get("rating") == "useful":
                    bump(a["did"], "attestations_useful")
                elif a.get("rating") == "not":
                    bump(a["did"], "attestations_not")

            # Attestations received: poster gets credit/blame for the job;
            # deliverers also get the attestation applied to them.
            poster = job.poster_did
            deliverers = set(job.deliverer_dids)
            for a in job.attestations:
                rating = a.get("rating")
                if poster:
                    bump(poster, "attestations_received_on_posted")
                    if rating == "useful":
                        bump(poster, "useful_received_on_posted")
                    elif rating == "not":
                        bump(poster, "not_received_on_posted")
                for d in deliverers:
                    bump(d, "attestations_received_on_delivered")
                    if rating == "useful":
                        bump(d, "useful_received_on_delivered")
                    elif rating == "not":
                        bump(d, "not_received_on_delivered")

        return stats

    # -----------------------------------------------------------------
    # Snapshot
    # -----------------------------------------------------------------

    def snapshot(self, top_limit: int = 500) -> Dict[str, Any]:
        """Return the JSON-serializable payload for data/kibble.json."""
        jobs = list(self._jobs.values())
        # Sort by last_activity descending (most recent first)
        jobs.sort(key=lambda j: j._last_activity() or "", reverse=True)
        top = jobs[:top_limit]

        # Aggregate stats
        state_counts: Dict[str, int] = {}
        category_counts: Dict[str, int] = {}
        for j in self._jobs.values():
            state_counts[j.state] = state_counts.get(j.state, 0) + 1
            if j.category:
                category_counts[j.category] = category_counts.get(j.category, 0) + 1

        return {
            "version": "1.0",
            "generated_at": datetime.now(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "https://technocore.chat",
            "protocol_version": "kibble-v1-observed",
            "total_jobs": len(self._jobs),
            "total_frames": self._total_frames,
            "total_messages_sampled": self._total_messages_sampled,
            "frames_by_kind": dict(self._frames_by_kind),
            "jobs_by_state": state_counts,
            "jobs_by_category": category_counts,
            "jobs": [j.to_dict() for j in top],
        }

    # Convenience properties
    @property
    def total_jobs(self) -> int:
        return len(self._jobs)

    @property
    def total_frames(self) -> int:
        return self._total_frames
