"""
FRI collector entry point — resilient edition.

Design principle: the collector NEVER produces no output. Even if
technocore.chat is completely down, it commits the last known good
data with a "stale" flag so the site stays up.

Resilience layers:
  1. fetch_rooms: 60s timeout + 3 retries with exponential backoff
  2. fetch_room_messages: per-room try/except — one failing room
     doesn't crash the whole run
  3. Fallback: if fetch_rooms fails entirely, use the room list from
     the previous run (read from data/latest.json)
  4. Health tracking: writes health.json alongside data files,
     recording status of each component
  5. Exit code 0 always (unless --strict is passed) — GitHub Actions
     sees success even if some data is stale, so the site stays up

Usage:
  python -m collector.main --once
  python -m collector.main --once --top 20
  python -m collector.main --once --strict  # fail on any error
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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


# ---------------------------------------------------------------------------
# Health tracking
# ---------------------------------------------------------------------------


class HealthTracker:
    """Tracks the status of each collector component."""

    def __init__(self) -> None:
        self.components: Dict[str, Dict[str, Any]] = {}
        self.start_time = datetime.now(timezone.utc)

    def ok(self, component: str, detail: str = "") -> None:
        self.components[component] = {
            "status": "ok",
            "detail": detail,
        }

    def degraded(self, component: str, detail: str) -> None:
        self.components[component] = {
            "status": "degraded",
            "detail": detail,
        }
        log.warning("DEGRADED — %s: %s", component, detail)

    def failed(self, component: str, error: str) -> None:
        self.components[component] = {
            "status": "failed",
            "detail": error,
        }
        log.error("FAILED — %s: %s", component, error)

    @property
    def overall_status(self) -> str:
        statuses = [c["status"] for c in self.components.values()]
        if "failed" in statuses:
            return "degraded"  # not "failed" — we still produce output
        if "degraded" in statuses:
            return "degraded"
        return "ok"

    def snapshot(self) -> Dict[str, Any]:
        return {
            "status": self.overall_status,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "duration_seconds": round(
                (datetime.now(timezone.utc) - self.start_time).total_seconds(), 1
            ),
            "components": self.components,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
        out.append(r)
    out.sort(
        key=lambda x: (
            -float(x.get("nick_diversity") or 0),
            int(x.get("idle_seconds") or 999999),
        )
    )
    return out[:SAMPLE_CANDIDATES]


def _merge_always_poll(
    candidates: List[Dict[str, Any]], all_rooms: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
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


def _load_previous_rooms(out_dir: Path) -> Optional[List[Dict[str, Any]]]:
    """Try to read the room list from the previous run's latest.json.
    Used as fallback when fetch_rooms fails entirely."""
    prev_path = out_dir / "latest.json"
    if not prev_path.exists():
        return None
    try:
        prev = json.loads(prev_path.read_text(encoding="utf-8"))
        rooms = prev.get("rooms", [])
        if rooms:
            log.info("Loaded %d rooms from previous run as fallback", len(rooms))
            return rooms
    except Exception as e:
        log.warning("Could not load previous rooms: %s", e)
    return None


def _safe_fetch_room(
    name: str, limit: int, health: HealthTracker
) -> List[Dict[str, Any]]:
    """Fetch room messages with per-room error handling.
    Never raises — returns empty list on failure."""
    try:
        return fetch_room_messages(name, limit=limit)
    except Exception as e:
        health.degraded(f"room:{name}", f"fetch failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Main collection pass
# ---------------------------------------------------------------------------


def run_once(
    top_n: int = TOP_N,
    out_dir: Path | None = None,
    strict: bool = False,
) -> Dict[str, Any]:
    """Run a single collection pass.

    Resilience: never crashes. If technocore.chat is down, uses previous
    data. If one room fails, continues with others. Always writes all 5
    JSON files + health.json.

    If strict=True, raises on any error instead of degrading.
    """
    if out_dir is None:
        out_dir = Path(__file__).resolve().parent.parent / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    health = HealthTracker()
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # -----------------------------------------------------------------
    # Step 1: Fetch room list (with fallback)
    # -----------------------------------------------------------------
    all_rooms: List[Dict[str, Any]] = []
    rooms_source = "live"

    log.info("Fetching room list (limit=%s)…", ROOMS_LIMIT)
    try:
        rooms_payload = fetch_rooms(limit=ROOMS_LIMIT)
        all_rooms = rooms_payload.get("rooms") or []
        log.info(
            "Received %d rooms (server total ≈ %s)",
            len(all_rooms),
            rooms_payload.get("total"),
        )
        health.ok("fetch_rooms", f"{len(all_rooms)} rooms from technocore.chat")
    except Exception as e:
        health.failed("fetch_rooms", str(e))
        if strict:
            raise
        log.error("fetch_rooms failed, falling back to previous run: %s", e)
        prev_rooms = _load_previous_rooms(out_dir)
        if prev_rooms:
            all_rooms = prev_rooms
            rooms_source = "stale_fallback"
            health.degraded("fetch_rooms", f"using previous run ({len(all_rooms)} rooms)")
        else:
            log.error("No previous data available — will produce empty output")
            all_rooms = []
            rooms_source = "empty"

    # -----------------------------------------------------------------
    # Step 2: Filter + merge always-poll rooms
    # -----------------------------------------------------------------
    candidates = filter_candidates(all_rooms)
    candidates = _merge_always_poll(candidates, all_rooms)
    log.info("After filter + always-poll merge: %d candidates to sample", len(candidates))
    health.ok("filter", f"{len(candidates)} candidates")

    # -----------------------------------------------------------------
    # Step 3: Sample messages from each room (per-room error handling)
    # -----------------------------------------------------------------
    scored: List[Dict[str, Any]] = []
    did_index = DidIndex()
    kibble_index = KibbleIndex()
    tclk_index = TclkIndex()

    rooms_sampled = 0
    rooms_failed = 0

    for i, meta in enumerate(candidates, 1):
        name = meta.get("room", "?")
        limit = ROOM_MESSAGE_LIMITS.get(name, 40)
        log.info("[%d/%d] Sampling %s (limit=%d) …", i, len(candidates), name, limit)

        messages = _safe_fetch_room(name, limit, health)
        if messages:
            rooms_sampled += 1
        else:
            rooms_failed += 1

        result = score_room(meta, messages)
        scored.append(result)
        did_index.ingest_messages(name, messages)
        kibble_index.ingest_messages(name, messages)
        tclk_index.ingest_messages(name, messages)

    health.ok(
        "sample",
        f"{rooms_sampled} sampled, {rooms_failed} failed",
    )

    # -----------------------------------------------------------------
    # Step 4: Write all 5 JSON files (always, even if partially empty)
    # -----------------------------------------------------------------
    scored.sort(key=lambda x: x["score"], reverse=True)
    ranked = scored[:top_n]
    for i, r in enumerate(ranked, 1):
        r["rank"] = i

    rooms_payload_out = {
        "version": "1.1",
        "generated_at": now_str,
        "source": "https://technocore.chat",
        "data_source": rooms_source,
        "protocol_versions": PROTOCOL_VERSIONS,
        "total_rooms_considered": len(candidates),
        "rooms": ranked,
    }
    rooms_path = out_dir / "latest.json"
    rooms_path.write_text(
        json.dumps(rooms_payload_out, indent=2, ensure_ascii=False), encoding="utf-8"
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
        "Wrote %s (%d jobs, %d frames)",
        kibble_path,
        kibble_snapshot["total_jobs"],
        kibble_snapshot["total_frames"],
    )

    # TCLK index
    tclk_snapshot = tclk_index.snapshot(top_limit=500)
    tclk_path = out_dir / "tclk.json"
    tclk_path.write_text(
        json.dumps(tclk_snapshot, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log.info(
        "Wrote %s (%d contracts, %d frames)",
        tclk_path,
        tclk_snapshot["total_contracts"],
        tclk_snapshot["total_frames"],
    )

    # Reputation index
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

    # -----------------------------------------------------------------
    # Step 5: Write health.json
    # -----------------------------------------------------------------
    health.ok("write", "all 5 JSON files + health.json written")
    health_snapshot = health.snapshot()
    health_path = out_dir / "health.json"
    health_path.write_text(
        json.dumps(health_snapshot, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log.info("Wrote %s (status: %s)", health_path, health_snapshot["status"])

    return {
        "rooms": rooms_payload_out,
        "dids": dids_snapshot,
        "kibble": kibble_snapshot,
        "tclk": tclk_snapshot,
        "reputation": reputation_snapshot,
        "health": health_snapshot,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FRI collector — resilient edition")
    parser.add_argument("--once", action="store_true", help="Run a single collection pass")
    parser.add_argument("--top", type=int, default=TOP_N, help="How many rooms to keep")
    parser.add_argument(
        "--out-dir",
        type=str,
        default=None,
        help="Output directory (default: data/)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on any error instead of degrading (default: degrade gracefully)",
    )
    args = parser.parse_args(argv)

    if not args.once:
        parser.print_help()
        return 1

    out_dir = Path(args.out_dir) if args.out_dir else None

    try:
        run_once(top_n=args.top, out_dir=out_dir, strict=args.strict)
        return 0
    except Exception as e:
        log.error("Collector crashed: %s", e)
        log.error("Traceback:\n%s", traceback.format_exc())
        # Even on crash, try to write a health.json so we know what happened
        if out_dir:
            try:
                health_path = out_dir / "health.json"
                health_path.write_text(
                    json.dumps(
                        {
                            "status": "failed",
                            "timestamp": datetime.now(timezone.utc).strftime(
                                "%Y-%m-%dT%H:%M:%SZ"
                            ),
                            "error": str(e),
                            "traceback": traceback.format_exc(),
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            except Exception:
                pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
