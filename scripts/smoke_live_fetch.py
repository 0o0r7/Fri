"""Quick smoke test: fetch a small slice from live technocore.chat
and verify the flopkit-backed fetch path returns the expected shape.

Not part of the unit test suite — run manually:
    python scripts/smoke_live_fetch.py
"""

from __future__ import annotations

import json
import sys

# Allow running from repo root without install
sys.path.insert(0, ".")

from collector.fetch import fetch_room_messages, fetch_rooms  # noqa: E402

print("=== /rooms?format=json&limit=3 ===")
rooms = fetch_rooms(limit=3)
print(f"total rooms reported: {rooms.get('total')}")
for r in (rooms.get("rooms") or [])[:3]:
    print(f"  - {r.get('room'):30s} seq={r.get('last_seq'):>10} idle={r.get('idle_seconds')}s")

print()
print("=== /r/tclk-offers?format=json&limit=3 ===")
msgs = fetch_room_messages("tclk-offers", limit=3)
for m in msgs[:3]:
    text = (m.get("text") or "")[:80]
    frm = (m.get("from") or "")[:24]
    print(f"  [#{m.get('seq')}] {frm}: {text}")

print()
print("=== /r/kibble?format=json&limit=3 ===")
msgs = fetch_room_messages("kibble", limit=3)
for m in msgs[:3]:
    text = (m.get("text") or "")[:80]
    frm = (m.get("from") or "")[:24]
    print(f"  [#{m.get('seq')}] {frm}: {text}")

print()
print("Smoke test OK.")
