"""DID Index — Phase 1 of FRI.

Extracts every signed `did:key:...` from sampled room messages and builds
per-DID statistics. The index is the foundation for the reputation score
in Phase 4 — it answers "who is on the network and what are they doing?"

Schema (data/dids.json):

    {
      "version": "1.0",
      "generated_at": "2026-09-08T...",
      "source": "https://technocore.chat",
      "protocol_versions": { ... },
      "total_dids": 412,
      "total_messages_sampled": 8421,
      "dids": [
        {
          "did": "did:key:z6Mk...",
          "fingerprint": "4f541151fd42c677",
          "first_seen": "2026-09-07T17:48:13Z",
          "last_active": "2026-09-08T19:20:00Z",
          "messages_signed": 1247,
          "rooms_active_in": 12,
          "rooms": ["tclk-offers", "kibble", ...],
          "avg_message_length": 187.4,
          "rooms_breakdown": {
            "tclk-offers": 412,
            "kibble": 89,
            ...
          }
        },
        ...
      ]
    }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .config import MACHINE_ROOMS
from .spam import (
    CATEGORY_CLEAN,
    CATEGORY_CAMPAIGN,
    CATEGORY_PHRASE,
    CATEGORY_TEMPLATE,
    DidSpamEvaluator,
    RATE_WINDOW_MIN,
    compute_flags,
)

try:
    from flopkit.technocore import did_note_fingerprint
except ImportError:
    # Fallback for environments without flopkit (e.g., FRI live backend).
    # Same algorithm: first 16 hex chars of SHA-256 of the DID string.
    import hashlib

    def did_note_fingerprint(did: str) -> str:
        return hashlib.sha256(did.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


def _ts_minute(ts: str) -> Optional[int]:
    """Epoch-minute of an ISO timestamp; None when unparseable."""
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return int(dt.timestamp() // 60)
    except (ValueError, TypeError, OSError):
        return None


@dataclass
class DidStats:
    """Accumulator for one DID's activity across all sampled rooms.

    Low-signal (spam) accounting: every message carries exactly one spam
    category (clean/phrase/template/campaign — see spam.py), so the three
    counters below sum to the total low-signal count without double
    subtraction. Rate buckets hold per-minute message counts from
    non-machine rooms only, pruned to a rolling 10-minute window.
    """

    did: str
    first_seen: Optional[str] = None
    last_active: Optional[str] = None
    messages_signed: int = 0
    rooms: Dict[str, int] = field(default_factory=dict)  # room_name -> msg count
    total_text_chars: int = 0  # for avg_message_length
    # Low-signal counters (serialized; hydrated from dids.json when present)
    phrase_msgs: int = 0      # farming phrases / emoji-only / no-signal text
    template_msgs: int = 0    # repeats this DID's own earlier template
    campaign_msgs: int = 0    # template currently shared by many DIDs
    # Identity registry (DID-note sync, 2026-09 durability response):
    # self-published profile loaded from the persistent /kv/did-* note
    # namespace. A registry-only DID has messages_signed == 0 until any
    # signed message is observed — it stays indexed and queryable either way.
    profile_bio: Optional[str] = None
    identity_note: bool = False
    # Rate window (not serialized — rebuilt organically after boot)
    _rate_buckets: Dict[int, int] = field(
        default_factory=dict, repr=False, compare=False
    )  # minute_epoch -> count

    def ingest(
        self, room: str, ts: str, text: str, spam_category: str = CATEGORY_CLEAN
    ) -> None:
        self.messages_signed += 1
        self.rooms[room] = self.rooms.get(room, 0) + 1
        self.total_text_chars += len(text or "")

        if spam_category == CATEGORY_PHRASE:
            self.phrase_msgs += 1
        elif spam_category == CATEGORY_TEMPLATE:
            self.template_msgs += 1
        elif spam_category == CATEGORY_CAMPAIGN:
            self.campaign_msgs += 1

        # Rate tracking: non-machine rooms only (busy-but-honest machine
        # feeds must not trip volume flags; content flags still apply).
        if room not in MACHINE_ROOMS and ts:
            minute = _ts_minute(ts)
            if minute is not None:
                self._rate_buckets[minute] = self._rate_buckets.get(minute, 0) + 1
                self._prune_rate_buckets()

        if ts:
            if self.first_seen is None or ts < self.first_seen:
                self.first_seen = ts
            if self.last_active is None or ts > self.last_active:
                self.last_active = ts

    def _prune_rate_buckets(self) -> None:
        """Keep only the most recent RATE_WINDOW_MIN minutes of buckets."""
        if not self._rate_buckets:
            return
        newest = max(self._rate_buckets)
        cutoff = newest - RATE_WINDOW_MIN + 1
        self._rate_buckets = {
            m: c for m, c in self._rate_buckets.items() if m >= cutoff
        }

    @property
    def low_signal_msgs(self) -> int:
        """Messages that carry no usable participation signal."""
        return self.phrase_msgs + self.template_msgs + self.campaign_msgs

    @property
    def peak_msgs_per_min(self) -> int:
        """Highest per-minute message count in the rolling rate window."""
        return max(self._rate_buckets.values(), default=0)

    @property
    def spam_flags(self) -> List[str]:
        """Published, auditable flags derived from the counters."""
        return compute_flags(
            messages_signed=self.messages_signed,
            phrase_msgs=self.phrase_msgs,
            template_msgs=self.template_msgs,
            campaign_msgs=self.campaign_msgs,
            peak_msgs_per_min=self.peak_msgs_per_min,
            first_seen=self.first_seen,
            last_active=self.last_active,
        )

    def to_dict(self) -> Dict[str, Any]:
        avg_len = (
            self.total_text_chars / self.messages_signed
            if self.messages_signed > 0
            else 0.0
        )
        low_signal = self.low_signal_msgs
        return {
            "did": self.did,
            "fingerprint": did_note_fingerprint(self.did),
            "first_seen": self.first_seen,
            "last_active": self.last_active,
            "messages_signed": self.messages_signed,
            "rooms_active_in": len(self.rooms),
            "rooms": sorted(self.rooms.keys()),
            "rooms_breakdown": dict(
                sorted(self.rooms.items(), key=lambda kv: -kv[1])
            ),
            "avg_message_length": round(avg_len, 1),
            # Spam integrity (v1.1) — published, never silently removed
            "phrase_msgs": self.phrase_msgs,
            "template_msgs": self.template_msgs,
            "campaign_msgs": self.campaign_msgs,
            "low_signal_msgs": low_signal,
            "spam_ratio": round(low_signal / self.messages_signed, 3)
            if self.messages_signed > 0
            else 0.0,
            "peak_msgs_per_min": self.peak_msgs_per_min,
            "spam_flags": self.spam_flags,
            # Identity registry (v1.2) — present when the DID published a
            # did-note; absent otherwise so legacy consumers see no change.
            **(
                {"profile_bio": self.profile_bio, "identity_note": True}
                if self.identity_note
                else {}
            ),
        }


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------


class DidIndex:
    """In-memory index of every signed DID we've seen.

    Call `ingest_message` for every message in every room we sample, then
    `snapshot()` to get the JSON-serializable payload.
    """

    def __init__(self) -> None:
        self._dids: Dict[str, DidStats] = {}
        self._total_messages_sampled: int = 0
        # Per-message low-signal classifier (template/campaign/phrase).
        # Owned by the index so both the live collector and the batch
        # pipeline share identical spam semantics.
        self._spam = DidSpamEvaluator()
        # Floor for total_dids: dids.json lists a TOP-500-truncated view while
        # publishing the true total — the ecosystem outgrew the cap (892 DIDs
        # as of 2026-09-14), so hydrate() must restore the published total
        # instead of deriving it from the truncated list.
        self._total_dids_floor: int = 0
        # DIDs whose stats changed since the last durable-persistence flush
        # (backend write-through to the fri:d:* store keys). The batch
        # pipeline never flushes, so the set simply grows there unused.
        self._dirty: set = set()

    def mark_dirty(self, did: str) -> None:
        self._dirty.add(did)

    def pop_dirty(self) -> set:
        """Return and clear the dirty set (persistence flush boundary)."""
        out = self._dirty
        self._dirty = set()
        return out

    def ingest_message(self, room: str, message: Dict[str, Any]) -> None:
        """Update the index with one message. Only signed messages count."""
        self._total_messages_sampled += 1
        frm = message.get("from") or ""
        if not isinstance(frm, str) or not frm.startswith("did:key:"):
            return
        ts = message.get("ts") or ""
        text = message.get("text") or ""
        verdict = self._spam.observe(room=room, did=frm, text=text)
        stats = self._dids.get(frm)
        if stats is None:
            stats = DidStats(did=frm)
            self._dids[frm] = stats
        stats.ingest(room=room, ts=ts, text=text, spam_category=verdict.category)
        self._dirty.add(frm)

    def register_identity(self, did: str, bio: str | None = None) -> bool:
        """Register a DID from the persistent did-note registry (no messages).

        The /kv/did-* namespace survives room-ring churn, so it is the
        network's durable identity ledger. A DID known only through its
        note gets a zero-activity entry carrying the self-published bio —
        findable via /api/dids?q= and /api/did/{did}/profile — and any
        later observed message upgrades the same entry in place.

        Idempotent: re-registering a known DID only refreshes the bio.
        Returns True when a new entry was created.
        """
        stats = self._dids.get(did)
        if stats is None:
            stats = DidStats(did=did, identity_note=True, profile_bio=bio)
            self._dids[did] = stats
            self._dirty.add(did)
            return True
        stats.identity_note = True
        if bio:
            stats.profile_bio = bio
        self._dirty.add(did)
        return False

    def ingest_messages(self, room: str, messages: List[Dict[str, Any]]) -> None:
        for m in messages:
            self.ingest_message(room, m)

    def get(self, did: str) -> Optional[DidStats]:
        return self._dids.get(did)

    def top_dids(self, limit: int = 100, *, by: str = "messages_signed") -> List[DidStats]:
        """Return the top-N DIDs sorted by `by` ('messages_signed' or 'rooms_active_in')."""
        items = list(self._dids.values())
        if by == "rooms_active_in":
            items.sort(key=lambda s: (-len(s.rooms), -s.messages_signed, s.did))
        else:
            items.sort(key=lambda s: (-s.messages_signed, -len(s.rooms), s.did))
        return items[:limit]

    def snapshot(self, top_limit: int = 500) -> Dict[str, Any]:
        """Return the JSON-serializable payload for data/dids.json.

        DIDs are sorted by messages_signed descending. The top_limit cap
        keeps the file size reasonable — full history can be queried via
        the per-DID endpoint (Phase 4).
        """
        top = self.top_dids(limit=top_limit, by="messages_signed")
        return {
            "version": "1.0",
            "generated_at": datetime.now(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "https://technocore.chat",
            "total_dids": len(self._dids),
            "total_messages_sampled": self._total_messages_sampled,
            "dids": [s.to_dict() for s in top],
        }

    def hydrate(self, payload: Dict[str, Any]) -> int:
        """Restore index state from a dids.json-shaped payload (boot-time).

        The live index used to start empty on every boot: counts collapsed
        to whatever the seeded rooms saw recently, daily_active/new_dids in
        health snapshots read ~total_dids (everything looked brand-new),
        and reputation lost all activity history until the firehose
        refilled it. Hydrating from the committed batch baseline fixes all
        three without any extra technocore load (no additional requests).

        Round-trips everything snapshot() publishes: messages_signed,
        rooms_breakdown (per-room counts), first_seen/last_active, and
        avg_message_length (re-encoded as total_text_chars so reputation
        scoring is unchanged). Entries already present are skipped, so
        hydrate() is idempotent and live ingest always wins for known DIDs.

        Returns the number of DIDs restored.
        """
        try:
            self._total_messages_sampled = max(
                self._total_messages_sampled,
                int(payload.get("total_messages_sampled") or 0),
            )
        except (TypeError, ValueError):
            pass
        try:
            self._total_dids_floor = max(
                self._total_dids_floor,
                int(payload.get("total_dids") or 0),
            )
        except (TypeError, ValueError):
            pass

        def _clamp_count(value: Any) -> int:
            try:
                return max(0, int(value or 0))
            except (TypeError, ValueError):
                return 0

        restored = 0
        for entry in payload.get("dids", []):
            if not isinstance(entry, dict):
                continue
            did = entry.get("did")
            if not did or did in self._dids:
                continue
            try:
                messages = int(entry.get("messages_signed") or 0)
            except (TypeError, ValueError):
                messages = 0
            rooms = dict(entry.get("rooms_breakdown") or {})
            if not rooms:
                # Legacy files without per-room counts: keep the room names
                # (zero counts) so rooms_active_in still round-trips.
                rooms = {
                    r: 0 for r in (entry.get("rooms") or []) if isinstance(r, str)
                }
            try:
                avg_len = float(entry.get("avg_message_length") or 0.0)
            except (TypeError, ValueError):
                avg_len = 0.0
            self._dids[did] = DidStats(
                did=did,
                first_seen=entry.get("first_seen"),
                last_active=entry.get("last_active"),
                messages_signed=messages,
                rooms=rooms,
                total_text_chars=int(round(avg_len * messages)),
                # Spam counters round-trip when present; legacy baselines
                # (pre-v1.1 files) hydrate with zeros — rate buckets and
                # flags rebuild organically from live traffic.
                phrase_msgs=_clamp_count(entry.get("phrase_msgs")),
                template_msgs=_clamp_count(entry.get("template_msgs")),
                campaign_msgs=_clamp_count(entry.get("campaign_msgs")),
                profile_bio=entry.get("profile_bio"),
                identity_note=bool(entry.get("identity_note")),
            )
            self._dirty.add(did)
            restored += 1
        return restored

    def hydrate_entry(self, entry: Dict[str, Any]) -> str | None:
        """Merge ONE durable per-DID entry (fri:d:* payload) into the index.

        Unlike hydrate() (baseline restore, skip-if-known), this MERGES:
        the durable entry and any already-live state each observe a
        partially overlapping message set, so every counter takes the MAX
        of the two views, first_seen the MIN and last_active the MAX.
        Adding counters instead would double-count the overlap.

        Returns the did when a merge/insert happened, else None.
        """
        did = entry.get("did")
        if not did or not isinstance(did, str):
            return None

        def _int(value: Any) -> int:
            try:
                return max(0, int(value or 0))
            except (TypeError, ValueError):
                return 0

        messages = _int(entry.get("messages_signed"))
        rooms_in = entry.get("rooms_breakdown") or {}
        if not isinstance(rooms_in, dict):
            rooms_in = {}
        existing = self._dids.get(did)
        if existing is None:
            self._dids[did] = DidStats(
                did=did,
                first_seen=entry.get("first_seen"),
                last_active=entry.get("last_active"),
                messages_signed=messages,
                rooms={str(k): _int(v) for k, v in rooms_in.items()},
                total_text_chars=_int(entry.get("total_text_chars")),
                phrase_msgs=_int(entry.get("phrase_msgs")),
                template_msgs=_int(entry.get("template_msgs")),
                campaign_msgs=_int(entry.get("campaign_msgs")),
                profile_bio=entry.get("profile_bio"),
                identity_note=bool(entry.get("identity_note")),
            )
            return did

        # Merge into existing live state — max per counter (both views are
        # cumulative observations of an overlapping window).
        if messages > existing.messages_signed:
            existing.messages_signed = messages
        for room, count in rooms_in.items():
            count = _int(count)
            if count > existing.rooms.get(room, 0):
                existing.rooms[str(room)] = count
        if _int(entry.get("total_text_chars")) > existing.total_text_chars:
            existing.total_text_chars = _int(entry.get("total_text_chars"))
        existing.phrase_msgs = max(existing.phrase_msgs, _int(entry.get("phrase_msgs")))
        existing.template_msgs = max(
            existing.template_msgs, _int(entry.get("template_msgs"))
        )
        existing.campaign_msgs = max(
            existing.campaign_msgs, _int(entry.get("campaign_msgs"))
        )
        fs, la = entry.get("first_seen"), entry.get("last_active")
        if fs and (existing.first_seen is None or fs < existing.first_seen):
            existing.first_seen = fs
        if la and (existing.last_active is None or la > existing.last_active):
            existing.last_active = la
        if entry.get("profile_bio") and not existing.profile_bio:
            existing.profile_bio = entry["profile_bio"]
        existing.identity_note = existing.identity_note or bool(
            entry.get("identity_note")
        )
        return did

    def search(self, query: str, limit: int = 500) -> List[DidStats]:
        """Substring search over the FULL index (did + fingerprint).

        The published snapshot caps at top-500 by volume, which makes any
        low-volume or registry-only DID unfindable through /api/dids —
        unacceptable for a reputation oracle ("every DID ever observed
        stays queryable"). This scans all tracked DIDs; case-insensitive
        on the did string, prefix-insensitive on the 16-hex fingerprint.
        """
        q = (query or "").strip().lower()
        if not q:
            return []
        out: List[DidStats] = []
        for stats in self._dids.values():
            if q in stats.did.lower() or q in did_note_fingerprint(stats.did):
                out.append(stats)
                if len(out) >= limit:
                    break
        out.sort(
            key=lambda s: (-s.messages_signed, -len(s.rooms), s.did),
        )
        return out

    # Convenience for the collector
    @property
    def total_dids(self) -> int:
        return max(len(self._dids), self._total_dids_floor)

    def observation_window(self) -> Dict[str, Any]:
        """Time range + volume the current index actually covers.

        Audit transparency requirement: cumulative counters (total_dids,
        total_messages_sampled) are meaningless to a consumer who cannot
        tell WHAT window they observe. This reports the observation range
        across every tracked DID — oldest first_seen to newest last_active
        — plus the raw observed volume, so a flood-inflated live number can
        be told apart from the stable committed batch baseline.

        first_seen/last_active are ISO-8601 "Z" strings written by one
        code path, so lexicographic min/max is order-correct; None values
        (legacy entries, ts parse failures) are simply excluded. An empty
        index yields None/0 rather than raising.
        """
        firsts = [s.first_seen for s in self._dids.values() if s.first_seen]
        lasts = [s.last_active for s in self._dids.values() if s.last_active]
        return {
            "window_start": min(firsts) if firsts else None,
            "window_end": max(lasts) if lasts else None,
            "messages_observed": self._total_messages_sampled,
            "unique_dids_observed": self.total_dids,
        }
