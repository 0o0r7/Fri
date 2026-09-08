"""
FRI collector entry point.

Phase 0: TQR room-quality scoring (unchanged from v1).
Phase 1+: DID index, kibble, TCLK modules will be added as siblings.

Usage:
  python -m collector.main --once
  python -m collector.main --once --top 20
  python -m collector.main --once --out /tmp/fri.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .config import (
    ALWAYS_POLL_ROOMS,
    MAX_IDLE_SECONDS,
    MIN_WINDOW,
    PROTOCOL_VERSIONS,
    ROOM_DENYLIST,
    ROOMS_LIMIT,
    ROOM_MESSAGE_LIMITS,
    SAMPLE_CANDIDATES,
    TOP_N,
)
from .did_index import DidIndex
from .fetch import fetch_room_messages, fetch_rooms
from .kibble import KibbleIndex
from .reputation import ReputationScorer
from .score import score_room
from .tclk import TclkIndex

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fri")


def filter_candidates(rooms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Cheap pre-filter before expensive message sampling."""
    out = []
    for r in rooms:
        name = r.get("room") or ""
        if name in ROOM_DENYLIST:
            continue
        if int(r.get("idle_seconds") or 999999) > MAX_IDLE_SECONDS:
            continue
        if int(r.get("window") or 0) < MIN_WINDOW:
            continue
        # Prefer rooms that have some activity signal
        out.append(r)
    # Sort by a crude activity proxy so we sample the most promising first
    out.sort(
        key=lambda x: (
            -float(x.get("nick_diversity") or 0),
            int(x.get("idle_seconds") or 999999),
        )
    )
    return out[:SAMPLE_CANDIDATES]


def _merge_always_poll(candidates: List[Dict[str, Any]], all_rooms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ensure protocol-level rooms are always sampled, even if they fall below
    the activity cutoff. These rooms carry signal that the room-quality score
    does not capture (TCLK offers, kibble jobs, etc.)."""
    by_name = {r.get("room"): r for r in all_rooms}
    merged: List[Dict[str, Any]] = []
    seen = set()
    for name in ALWAYS_POLL_ROOMS:
        meta = by_name.get(name)
        if meta and name not in seen:
            merged.append(meta)
            seen.add(name)
    for c in candidates:
        if c.get("room") not in seen:
            merged.append(c)
            seen.add(c.get("room"))
    return merged


def run_once(
    top_n: int = TOP_N,
    out_dir: Path | None = None,
) -> Dict[str, Any]:
    """Run a single collection pass.

    Produces four artifacts in out_dir (default: data/):
      - latest.json  — TQR room quality rankings (v1.1)
      - dids.json    — DID index with per-DID activity stats (v1.0)
      - kibble.json  — Kibble v1 job index + aggregate stats (v1.0)
      - tclk.json    — TCLK/1 contract index + deal-flow stats (v1.0)

    The DID, Kibble, and TCLK indices all ingest every message we sample,
    so they ride along for free on top of the TQR scoring loop — zero
    extra HTTP calls.
    """
    if out_dir is None:
        out_dir = Path(__file__).resolve().parent.parent / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    log.info("Fetching room list (limit=%s)…", ROOMS_LIMIT)
    rooms_payload = fetch_rooms(limit=ROOMS_LIMIT)
    all_rooms = rooms_payload.get("rooms") or []
    log.info("Received %d rooms (server total ≈ %s)", len(all_rooms), rooms_payload.get("total"))

    candidates = filter_candidates(all_rooms)
    candidates = _merge_always_poll(candidates, all_rooms)
    log.info("After filter + always-poll merge: %d candidates to sample", len(candidates))

    scored: List[Dict[str, Any]] = []
    did_index = DidIndex()
    kibble_index = KibbleIndex()
    tclk_index = TclkIndex()

    for i, meta in enumerate(candidates, 1):
        name = meta.get("room", "?")
        # Use a larger sample for high-signal protocol rooms
        limit = ROOM_MESSAGE_LIMITS.get(name, 40)
        log.info("[%d/%d] Sampling %s (limit=%d) …", i, len(candidates), name, limit)
        messages = fetch_room_messages(name, limit=limit)
        # TQR room-quality score
        result = score_room(meta, messages)
        scored.append(result)
        # DID index — every signed message we just read
        did_index.ingest_messages(name, messages)
        # Kibble index — only kibble v1 frames count, but ingest is cheap
        kibble_index.ingest_messages(name, messages)
        # TCLK index — only tclk1 frames count, but ingest is cheap
        tclk_index.ingest_messages(name, messages)

    scored.sort(key=lambda x: x["score"], reverse=True)
    ranked = scored[:top_n]
    for i, r in enumerate(ranked, 1):
        r["rank"] = i

    rooms_payload = {
        "version": "1.1",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "https://technocore.chat",
        "protocol_versions": PROTOCOL_VERSIONS,
        "total_rooms_considered": len(candidates),
        "rooms": ranked,
    }
    rooms_path = out_dir / "latest.json"
    rooms_path.write_text(
        json.dumps(rooms_payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log.info("Wrote %s (%d rooms)", rooms_path, len(ranked))

    # DID index
    dids_snapshot = did_index.snapshot(top_limit=500)
    dids_path = out_dir / "dids.json"
    dids_path.write_text(
        json.dumps(dids_snapshot, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log.info(
        "Wrote %s (%d DIDs from %d messages sampled)",
        dids_path,
        dids_snapshot["total_dids"],
        dids_snapshot["total_messages_sampled"],
    )

    # Kibble index
    kibble_snapshot = kibble_index.snapshot(top_limit=500)
    kibble_path = out_dir / "kibble.json"
    kibble_path.write_text(
        json.dumps(kibble_snapshot, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log.info(
        "Wrote %s (%d jobs, %d frames from %d messages sampled)",
        kibble_path,
        kibble_snapshot["total_jobs"],
        kibble_snapshot["total_frames"],
        kibble_snapshot["total_messages_sampled"],
    )

    # TCLK index
    tclk_snapshot = tclk_index.snapshot(top_limit=500)
    tclk_path = out_dir / "tclk.json"
    tclk_path.write_text(
        json.dumps(tclk_snapshot, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log.info(
        "Wrote %s (%d contracts, %d frames, %d parse failures)",
        tclk_path,
        tclk_snapshot["total_contracts"],
        tclk_snapshot["total_frames"],
        tclk_snapshot["parse_failures"],
    )

    # Reputation index — combines DID + kibble + TCLK signals
    scorer = ReputationScorer(did_index, kibble_index, tclk_index)
    reputation_snapshot = scorer.snapshot(top_limit=500)
    reputation_path = out_dir / "reputation.json"
    reputation_path.write_text(
        json.dumps(reputation_snapshot, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log.info(
        "Wrote %s (%d DIDs scored, avg score %.3f)",
        reputation_path,
        reputation_snapshot["total_dids_scored"],
        reputation_snapshot["avg_score"],
    )

    return {
        "rooms": rooms_payload,
        "dids": dids_snapshot,
        "kibble": kibble_snapshot,
        "tclk": tclk_snapshot,
        "reputation": reputation_snapshot,
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FRI collector")
    parser.add_argument("--once", action="store_true", help="Run a single collection pass")
    parser.add_argument("--top", type=int, default=TOP_N, help="How many rooms to keep")
    parser.add_argument(
        "--out-dir",
        type=str,
        default=None,
        help="Output directory (default: data/)",
    )
    args = parser.parse_args(argv)

    if not args.once:
        parser.print_help()
        return 1

    out_dir = Path(args.out_dir) if args.out_dir else None
    run_once(top_n=args.top, out_dir=out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
