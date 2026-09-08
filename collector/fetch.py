"""HTTP client for Technocore public endpoints.

Thin wrapper around `flopkit.TechnocoreClient` so FRI gets production-grade
retry, rate-limit handling, and JSON parsing for free. Read-only by default;
the identity parameter is only loaded when signed writes are needed (Phase 6).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from flopkit.config import TechnocoreConfig
from flopkit.technocore import (
    DuplicateMessageError,
    NoteConflictError,
    RateLimitedError,
    TechnocoreClient,
    TechnocoreError,
)

from .config import BASE_URL, MESSAGES_PER_ROOM, TIMEOUT, USER_AGENT

log = logging.getLogger("fri.fetch")

# Re-export exceptions so callers don't have to import from flopkit internals
__all__ = [
    "fetch_rooms",
    "fetch_room_messages",
    "fetch_room_full",
    "fetch_note",
    "TechnocoreError",
    "DuplicateMessageError",
    "RateLimitedError",
    "NoteConflictError",
]


def _client() -> TechnocoreClient:
    """Build a read-only TechnocoreClient with FRI's user-agent.

    The flopkit client doesn't take a User-Agent header directly, but it
    respects FLOPKIT_BASE_URL and FLOPKIT_TIMEOUT env vars. We set those
    before constructing so the values come from our config.py.
    """
    import os
    os.environ.setdefault("FLOPKIT_BASE_URL", BASE_URL)
    os.environ.setdefault("FLOPKIT_TIMEOUT", str(TIMEOUT))
    config = TechnocoreConfig()
    return TechnocoreClient(identity=None, config=config)


def fetch_rooms(limit: int = 150) -> Dict[str, Any]:
    """GET /rooms?format=json&limit=N

    The flopkit client's list_rooms() returns text/plain, so we hit the JSON
    endpoint directly via its underlying httpx client. This keeps the schema
    we depend on (engagement metrics, room names, topics) consistent.
    """
    with _client() as client:
        r = client._client.get(
            "/rooms",
            params={"format": "json", "limit": limit},
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        r.raise_for_status()
        return r.json()


def fetch_room_messages(room: str, limit: int = MESSAGES_PER_ROOM) -> List[Dict[str, Any]]:
    """GET /r/{room}?format=json&limit=N — returns the messages list.

    Uses flopkit's read_room() which validates the response shape and handles
    retry/rate-limit logic. Returns the .messages list directly.
    """
    with _client() as client:
        try:
            data = client.read_room(room, limit=limit)
            return data.get("messages") or []
        except TechnocoreError as e:
            log.warning("Failed to fetch room %s: %s", room, e)
            return []


def fetch_room_full(room: str, limit: int = MESSAGES_PER_ROOM) -> Dict[str, Any]:
    """GET /r/{room}?format=json&limit=N — returns the full response dict.

    Use this when you need `last_seq`, `count`, or other envelope fields
    beyond just the messages list.
    """
    with _client() as client:
        try:
            return client.read_room(room, limit=limit)
        except TechnocoreError as e:
            log.warning("Failed to fetch room %s: %s", room, e)
            return {"room": room, "count": 0, "last_seq": 0, "messages": []}


def fetch_note(ns: str, key: str) -> str | None:
    """GET /kv/{ns}/{key} — returns the note value, or None if not found."""
    with _client() as client:
        try:
            return client.read_note(ns, key)
        except TechnocoreError as e:
            log.warning("Failed to fetch note %s/%s: %s", ns, key, e)
            return None
