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

from flopkit.technocore import did_note_fingerprint


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class DidStats:
    """Accumulator for one DID's activity across all sampled rooms."""

    did: str
    first_seen: Optional[str] = None
    last_active: Optional[str] = None
    messages_signed: int = 0
    rooms: Dict[str, int] = field(default_factory=dict)  # room_name -> msg count
    total_text_chars: int = 0  # for avg_message_length

    def ingest(self, room: str, ts: str, text: str) -> None:
        self.messages_signed += 1
        self.rooms[room] = self.rooms.get(room, 0) + 1
        self.total_text_chars += len(text or "")

        if ts:
            if self.first_seen is None or ts < self.first_seen:
                self.first_seen = ts
            if self.last_active is None or ts > self.last_active:
                self.last_active = ts

    def to_dict(self) -> Dict[str, Any]:
        avg_len = (
            self.total_text_chars / self.messages_signed
            if self.messages_signed > 0
            else 0.0
        )
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

    def ingest_message(self, room: str, message: Dict[str, Any]) -> None:
        """Update the index with one message. Only signed messages count."""
        self._total_messages_sampled += 1
        frm = message.get("from") or ""
        if not isinstance(frm, str) or not frm.startswith("did:key:"):
            return
        ts = message.get("ts") or ""
        text = message.get("text") or ""
        stats = self._dids.get(frm)
        if stats is None:
            stats = DidStats(did=frm)
            self._dids[frm] = stats
        stats.ingest(room=room, ts=ts, text=text)

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

    # Convenience for the collector
    @property
    def total_dids(self) -> int:
        return len(self._dids)
