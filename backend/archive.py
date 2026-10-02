"""Atlas archive tier — the durable tail of the DID ledger.

The free-tier durable store (Aiven free-1, ~30 MB) enforces caps by
evicting the lowest-recency fri:d:* tail. Before this module existed,
eviction was a pure DELETE: any DID that aged out of the caps became
unqueryable, even though /api/dids?q= still promised "every DID ever
observed stays queryable" — that promise was silently false, and old
low-volume DIDs (exactly the ones a reputation oracle exists to expose)
returned empty results. This module closes the hole:

  1. The prune loop archives evicted entries HERE (bulk upsert keyed by
     16-hex fingerprint) BEFORE deleting them from the store.
  2. /api/dids?q= falls back to this collection when the live index
     has no match, so evicted DIDs stay queryable again.
  3. A one-time git-history backfill (scripts/) seeds the archive with
     DIDs recovered from historical committed dids.json snapshots.

Design constraints (F1 + M0 reality):

- MONGODB_URI comes from the environment (App Service app settings).
  Unset / pymongo missing / Atlas unreachable -> every call degrades
  to a logged no-op or a hard "unavailable" answer. The archive is an
  ADDITIVE tier: nothing in the hot ingest path depends on it, so an
  Atlas outage can never wedge the collector (the Sep wedge lesson).
- pymongo is synchronous. Call sites wrap with asyncio.to_thread so
  the event loop is never blocked.
- Upserts are idempotent by fingerprint, so prune retries, re-hydration
  and the git backfill can all write the same DID safely.
- M0 free tier: 512 MB, ~100 connections. One cached client, server
  selection timeout 10 s, small batched writes, estimated counts.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Any

log = logging.getLogger("fri.archive")

_FP_RE = re.compile(r"^[0-9a-f]{1,16}$")
_FP_LEN = 16
_ARCHIVE_DB = "fri"
_ARCHIVE_COLL = "did_archive"
_COUNT_TTL_S = 300.0


class ArchiveUnavailable(Exception):
    """Raised by search when the archive cannot answer right now."""


class DidArchive:
    """Lazy, thread-safe pymongo wrapper around the archive collection."""

    def __init__(self) -> None:
        self._client: Any | None = None
        self._coll: Any | None = None
        self._init_error: str | None = None
        self._lock = threading.Lock()
        self._count: int | None = None
        self._count_at: float = 0.0

    # -- connection ----------------------------------------------------

    def _uri(self) -> str | None:
        uri = os.environ.get("MONGODB_URI", "").strip()
        if uri:
            return uri
        # Operator-dropped credential file: lets the archive tier be
        # activated with Kudu/SSH access alone (no ARM token needed for
        # an app-settings write). App Service env vars take precedence.
        # The file lives on the persistent /home/data share, outside the
        # read-only package mount, and is never committed anywhere.
        try:
            with open("/home/data/fri/mongodb_uri") as f:
                uri = f.read().strip()
            return uri or None
        except OSError:
            return None

    def configured(self) -> bool:
        return self._uri() is not None

    def _ensure(self) -> Any:
        """Return the archive collection, or raise ArchiveUnavailable.

        Initialization is one-time and lock-guarded; a failed attempt is
        remembered (with the reason) so the hot path never retries a
        dead endpoint more than once per process unless env changes.
        """
        with self._lock:
            if self._coll is not None:
                return self._coll
            if self._init_error is not None:
                raise ArchiveUnavailable(self._init_error)
            uri = self._uri()
            if not uri:
                self._init_error = "MONGODB_URI not set (archive tier disabled)"
                raise ArchiveUnavailable(self._init_error)
            try:
                from pymongo import MongoClient  # noqa: deferred import

                client: Any = MongoClient(
                    uri,
                    serverSelectionTimeoutMS=10_000,
                    connectTimeoutMS=10_000,
                    socketTimeoutMS=20_000,
                    maxPoolSize=4,
                    appName="fri-archive-tier",
                )
                coll = client[_ARCHIVE_DB][_ARCHIVE_COLL]
                # Idempotent index ensure (fast no-op once created):
                #   fp       unique — the upsert key
                #   did      sorted scan support for substring fallback
                #   did_lower  case-folded substring candidates
                coll.create_index("fp", unique=True, name="fp_unique")
                coll.create_index("did", name="did_idx")
                coll.create_index("did_lower", name="did_lower_idx")
                self._client = client
                self._coll = coll
                log.info("archive tier connected (db=%s coll=%s)", _ARCHIVE_DB, _ARCHIVE_COLL)
                return coll
            except ArchiveUnavailable:
                raise
            except Exception as e:  # pymongo errors, DNS, auth, timeouts
                self._init_error = f"archive init failed: {type(e).__name__}"
                log.warning("archive tier unavailable: %s", e)
                raise ArchiveUnavailable(self._init_error) from e

    def reset_for_tests(self) -> None:
        with self._lock:
            self._client = None
            self._coll = None
            self._init_error = None
            self._count = None
            self._count_at = 0.0

    # -- writes ----------------------------------------------------------

    def archive_entries(self, docs: list[dict[str, Any]]) -> int:
        """Bulk-upsert archive docs (each must carry its 'fp' key).

        Idempotent: re-archiving the same fingerprint merges nothing and
        simply replaces the stored payload with the newest view. Returns
        the number of docs processed; raises on hard failure so the
        caller (prune loop) can DEFER eviction instead of losing data.
        """
        if not docs:
            return 0
        coll = self._ensure()
        from pymongo import ReplaceOne

        ops: list[Any] = []
        for doc in docs:
            fp = doc.get("fp")
            if not fp or not isinstance(fp, str) or len(fp) > _FP_LEN:
                continue
            ops.append(ReplaceOne({"fp": fp}, doc, upsert=True))
            if len(ops) >= 500:
                coll.bulk_write(ops, ordered=False)
                ops = []
        if ops:
            coll.bulk_write(ops, ordered=False)
        self._count = None  # invalidate cached count
        return len(docs)

    # -- reads ------------------------------------------------------------

    def search(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        """Archive lookup for /api/dids?q= fallback.

        A 16-hex (or shorter hex) query hits the fp index as a prefix
        match (fast path); anything else is a case-insensitive substring
        match on the DID string. Returns public-view dicts shaped like
        DidStats.to_dict() plus 'archived': True, sorted by observed
        volume. Raises ArchiveUnavailable on connection trouble so the
        caller can report an honest error instead of a silent empty.
        """
        coll = self._ensure()
        q = (query or "").strip().lower()
        if not q:
            return []
        if _FP_RE.match(q):
            # fp prefix fast path (indexed) — also matches bare did keys
            # whose fingerprint happens to start with the same hex.
            mongo_filter: dict[str, Any] = {"fp": {"$regex": f"^{re.escape(q)}"}}
        else:
            mongo_filter = {"did_lower": {"$regex": re.escape(q)}}
        cursor = (
            coll.find(mongo_filter)
            .sort([("messages_signed", -1), ("did", 1)])
            .limit(max(1, min(int(limit), 200)))
        )
        return [_public_view(doc) for doc in cursor]

    def count(self, refresh: bool = False) -> int:
        """Cached estimated archive size (for /api/health honesty)."""
        now = time.time()
        if not refresh and self._count is not None and (now - self._count_at) < _COUNT_TTL_S:
            return self._count
        coll = self._ensure()
        self._count = int(coll.estimated_document_count())
        self._count_at = now
        return self._count


# ---------------------------------------------------------------------------
# Document shaping
# ---------------------------------------------------------------------------


def public_view_from_durable(fp: str, entry: dict[str, Any]) -> dict[str, Any]:
    """Normalize a durable fri:d:<fp> payload into an archive document.

    Accepts the compact _durable_entry shape (see collector.py) plus the
    fp; adds bookkeeping (archived_at, evict_source, did_lower). Safe on
    partial payloads — missing fields degrade to defaults, never raise.
    """
    did = entry.get("did")
    rooms = entry.get("rooms_breakdown") or {}
    if not isinstance(rooms, dict):
        rooms = {}
    doc = {
        "fp": fp,
        "did": did,
        "did_lower": (did or "").lower(),
        "messages_signed": int(entry.get("messages_signed") or 0),
        "first_seen": entry.get("first_seen"),
        "last_active": entry.get("last_active"),
        "rooms_breakdown": rooms,
        "total_text_chars": float(entry.get("total_text_chars") or 0.0),
        "phrase_msgs": int(entry.get("phrase_msgs") or 0),
        "template_msgs": int(entry.get("template_msgs") or 0),
        "campaign_msgs": int(entry.get("campaign_msgs") or 0),
        "profile_bio": entry.get("profile_bio"),
        "identity_note": bool(entry.get("identity_note")),
        "evict_source": entry.get("evict_source", "prune"),
        "archived_at": entry.get("archived_at"),
    }
    return doc


def _public_view(doc: dict[str, Any]) -> dict[str, Any]:
    """Archive document -> DidStats-compatible public view.

    Mirrors DidStats.to_dict() field-for-field so the UI can render
    archived identities without a special code path. Derived spam
    fields are recomputed with the same published classifier; the RAM
    rate window is not archived, so peak_msgs_per_min is reported as 0
    rather than invented.
    """
    from collector.did_index import did_note_fingerprint
    from collector.spam import compute_flags

    did = doc.get("did") or ""
    rooms: dict[str, int] = doc.get("rooms_breakdown") or {}
    signed = int(doc.get("messages_signed") or 0)
    chars = float(doc.get("total_text_chars") or 0.0)
    phrase = int(doc.get("phrase_msgs") or 0)
    template = int(doc.get("template_msgs") or 0)
    campaign = int(doc.get("campaign_msgs") or 0)
    low = phrase + template + campaign
    first_seen = doc.get("first_seen")
    last_active = doc.get("last_active")
    view: dict[str, Any] = {
        "did": did,
        "fingerprint": doc.get("fp") or did_note_fingerprint(did),
        "first_seen": first_seen,
        "last_active": last_active,
        "messages_signed": signed,
        "rooms_active_in": len(rooms),
        "rooms": sorted(rooms.keys()),
        "rooms_breakdown": dict(sorted(rooms.items(), key=lambda kv: -kv[1])),
        "avg_message_length": round(chars / signed, 1) if signed > 0 else 0.0,
        "phrase_msgs": phrase,
        "template_msgs": template,
        "campaign_msgs": campaign,
        "low_signal_msgs": low,
        "spam_ratio": round(low / signed, 3) if signed > 0 else 0.0,
        "peak_msgs_per_min": 0,
        "spam_flags": compute_flags(
            messages_signed=signed,
            phrase_msgs=phrase,
            template_msgs=template,
            campaign_msgs=campaign,
            peak_msgs_per_min=0,
            first_seen=first_seen,
            last_active=last_active,
        ),
        "archived": True,
    }
    if doc.get("identity_note"):
        view["identity_note"] = True
        view["profile_bio"] = doc.get("profile_bio")
    return view


# Process-wide singleton (the collector loop and the API handlers share it)
archive = DidArchive()
