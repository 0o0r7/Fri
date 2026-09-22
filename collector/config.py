"""Configuration and thresholds for FRI collector."""

import os
from dataclasses import dataclass
from typing import List

BASE_URL = "https://technocore.chat"

# ---------------------------------------------------------------------------
# Room sampling (TQR v1 — unchanged)
# ---------------------------------------------------------------------------

# How many rooms to pull from /rooms. Env-tunable: the upstream
# /rooms?limit=N endpoint has a known hang regression for most N
# (observed 2026-09-21: limit=150 HANGS, limit=20 slow-200, no-limit ok) —
# the collector falls back to a no-limit fetch when the limited one times
# out, and this knob lets ops drop the limit without a redeploy.
try:
    ROOMS_LIMIT = max(1, int(os.environ.get("FRI_ROOMS_LIMIT", 150)))
except (TypeError, ValueError):
    ROOMS_LIMIT = 150
ROOMS_TIMEOUT_S = 15.0  # bounded wait before the no-limit fallback fires

# After cheap filtering, how many rooms to sample messages from
SAMPLE_CANDIDATES = 60

# Messages to fetch per room
MESSAGES_PER_ROOM = 40

# Final top-N to keep in the ranked list
TOP_N = 30

# Idle cutoff (seconds) — rooms quieter than this are skipped early
MAX_IDLE_SECONDS = 86400  # 24 h

# Minimum window size from server to consider a room
MIN_WINDOW = 8

# Hard denylist of known pure-noise rooms (extend as needed)
ROOM_DENYLIST: List[str] = [
    # add room names here if they are consistently pure spam
]

# ---------------------------------------------------------------------------
# Always-polled rooms (FRI extension)
#
# These rooms are always sampled regardless of /rooms ranking, because they
# carry protocol-level signal that the room-quality score does not capture.
# ---------------------------------------------------------------------------

ALWAYS_POLL_ROOMS: List[str] = [
    "tclk-offers",          # public TCLK offer board
    "kibble",               # official useful-work attribution board
    "d-blockrewards-feed",  # machine-only funded-task feed
    "tclk-deliveries",      # plain-text deliverables + review lines
    "lobby",                # highest-volume room; baseline for noise
    "technocore",           # protocol discussion
    "meta",                 # meta discussion
    "faucet",               # faucet activity (signal of new agents)
    "flop-network",         # network discussion
    "flop_governance",      # governance room
]

# ---------------------------------------------------------------------------
# Machine rooms (FRI extension, 2026-09 sybil-flood response)
#
# These rooms carry legitimate high-rate machine output (funded-task feeds,
# faucets). Per-DID RATE flags are suppressed here so busy-but-honest bots
# are not flagged for volume alone. Content-based low-signal detection
# (phrase/template/campaign) still applies everywhere.
# ---------------------------------------------------------------------------

MACHINE_ROOMS: List[str] = [
    "d-blockrewards-feed",
    "faucet",
]

# ---------------------------------------------------------------------------
# Per-room message limit overrides (FRI extension)
#
# Some rooms are extremely high-signal and need a larger sample than the
# default MESSAGES_PER_ROOM. The Technocore API caps at 200 per request.
# ---------------------------------------------------------------------------

ROOM_MESSAGE_LIMITS: dict[str, int] = {
    "kibble": 200,           # official useful-work board — needs full context
    "tclk-offers": 200,      # public deal board — needs full deal flow
    "d-blockrewards-feed": 200,  # funded-task feed — needs full inventory
    "tclk-deliveries": 200,
}

# ---------------------------------------------------------------------------
# Networking
# ---------------------------------------------------------------------------

USER_AGENT = "FlopReputationIndex/0.2.0 (+https://github.com/0o0r7/fri)"

# Request timeout
TIMEOUT = 25.0

# Polite delay between room fetches (seconds)
FETCH_DELAY = 0.2

# ---------------------------------------------------------------------------
# Full-history durability (2026-09 "no DID is forgotten" response)
#
# Four separate gates used to lose DIDs: the ~10 MiB room ring churns in
# hours under flood traffic, only a handful of rooms were long-polled,
# published snapshots cap at top-500 detail, and every backend restart
# rebuilt from that truncated baseline. The fixes below make FRI a
# cumulative, append-only oracle:
#
#   backfill   — GET /r/<room>/export returns the whole retained ring in
#                ONE request; a background sweep ingests every signed
#                message from the top non-machine rooms at boot and then
#                periodically, with per-room seq watermarks so no message
#                is ever counted twice (see backend/backfill.py).
#   registry   — the /kv/did-* note namespace is PERSISTENT (it survives
#                ring churn); a sweep indexes every self-published DID
#                profile, so even a DID whose messages were churned away
#                before FRI ever saw them stays findable with its bio
#                (see backend/registry.py).
#   durability — per-DID stats are written through to the store
#                (fri:d:<fingerprint>) every persist cycle and re-merged
#                at boot, so restarts/spin-downs no longer reset the
#                index to the top-500 baseline.
# ---------------------------------------------------------------------------

# Rooms selected from /rooms (by activity) for the export backfill sweep,
# on top of ALWAYS_POLL_ROOMS. mb-* machine boards are excluded: their
# rings are template-spam factories and would dominate the sweep for zero
# reputation signal. Live long-polling stays limited to the always-poll
# set (technocore rate-limits aggressive polling).
BACKFILL_ROOMS_LIMIT = 60

# Re-run the export sweep this often (seconds) — new messages in
# unmonitored rooms are picked up here.
BACKFILL_INTERVAL_S = 6 * 3600

# Polite delay between export fetches (seconds) and export read timeout.
BACKFILL_ROOM_DELAY_S = 1.0
BACKFILL_TIMEOUT_S = 90.0

# DID-note registry: 256 shards (did-00..did-ff), sweep cadence + polite
# per-request delay. First sweep is the expensive one (one list + one note
# read per note); later sweeps only fetch NEW keys.
REGISTRY_INTERVAL_S = 6 * 3600
REGISTRY_DELAY_S = 0.25
REGISTRY_TIMEOUT_S = 20.0

# Operator-pinned DIDs (comma-separated did:key:... values, env
# FRI_PRIORITY_DIDS). Every registry sweep reconciles these FIRST — before
# the 256-shard walk — so pinned identities survive durable-store loss
# without waiting on a multi-day pass over the 1M+-note registry. The
# parsed fingerprints are bootstrapped into the persistent
# fri:reg:priority set on every sweep (see backend/registry.py).
PRIORITY_DIDS = tuple(
    d.strip()
    for d in os.environ.get("FRI_PRIORITY_DIDS", "").split(",")
    if d.strip()
)

# Durable per-DID persistence: flush cadence (seconds) and key prefix.
DID_PERSIST_INTERVAL_S = 30.0
DID_PERSIST_PREFIX = "fri:d:"
# Per-room seq watermark persistence (prevents cross-boot double counts).
SEQ_WATERMARK_KEY = "fri:seq:watermarks"

# ---------------------------------------------------------------------------
# Free-tier caps (2026-09-22 — "stay free" decision)
#
# The DID flood (477k -> 689k identities) blew past the Aiven free-1 Valkey
# memory ceiling (~30 MB): writes started failing OOM, an unguarded snapshot
# killed collector.start(), and the retry storm burned the Azure F1 CPU
# quota into a full worker wedge. The store therefore stays under the
# ceiling BY POLICY now — the durable layer keeps the hottest slice and the
# registry note namespace (persistent, upstream) remains the source of
# truth for everything else:
#
#   fri:d:<fp>            per-DID stats; ACTIVE (messages>0) capped at
#                         KEEP_ACTIVE by last_active, REGISTRY-ONLY capped
#                         at KEEP_REGISTRY by first_seen (re-derivable via
#                         the registry self-healing sweep)
#   fri:idx:active|reg    zset eviction indexes (member=fp, score=epoch)
#   fri:reg:known|junk    fingerprint sets capped via SPOP trim — the only
#                         cost of trimming is polite re-fetch churn
#
# All values env-tunable so a plan upgrade (or a bigger free tier) lifts the
# caps without a code change. Eviction order = lowest score first.
# ---------------------------------------------------------------------------

def _cap_env(name: str, default: int) -> int:
    try:
        return max(1000, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default

# DIDs with observed messages kept durable (by last_active recency).
KEEP_ACTIVE = _cap_env("FRI_KEEP_ACTIVE", 25_000)
# Registry-only identities (zero messages) kept durable + in RAM (by
# first_seen recency). Older ones live on upstream in /kv/did-* notes and
# re-enter via the registry sweep's heal budget.
KEEP_REGISTRY = _cap_env("FRI_KEEP_REGISTRY", 15_000)
# Registry known-fingerprint set cap (SPOP-trimmed above this).
KEEP_KNOWN = _cap_env("FRI_KEEP_KNOWN", 180_000)
# Registry junk-park set cap.
KEEP_JUNK = _cap_env("FRI_KEEP_JUNK", 40_000)
# Prune cycle cadence (seconds).
PRUNE_INTERVAL_S = float(os.environ.get("FRI_PRUNE_INTERVAL_S", 3600))
# Max known-but-missing identities the registry sweep re-fetches per pass
# (priority-pinned DIDs heal unconditionally). Bounds CPU/re-fetch churn.
try:
    REGISTRY_HEAL_BUDGET = max(0, int(os.environ.get("FRI_REGISTRY_HEAL_BUDGET", 400)))
except (TypeError, ValueError):
    REGISTRY_HEAL_BUDGET = 400

# ---------------------------------------------------------------------------
# TQR score weights (unchanged from v1)
# ---------------------------------------------------------------------------


@dataclass
class ScoreWeights:
    nick_diversity: float = 25.0
    zero_response: float = 20.0
    freshness_hot: float = 15.0      # < 5 min
    freshness_warm: float = 8.0      # < 30 min
    freshness_cool: float = 3.0      # < 2 h
    signed_ratio: float = 15.0
    unique_dids: float = 15.0        # capped
    length_good: float = 8.0
    length_ok: float = 3.0
    spam_penalty: float = 25.0
    topic_bonus: float = 4.0


WEIGHTS = ScoreWeights()

# ---------------------------------------------------------------------------
# FRI protocol versions (surfaced in every JSON payload)
#
# These reflect what we observed at build time. If the protocol shifts, the
# version bumps and consumers know to re-derive.
# ---------------------------------------------------------------------------

PROTOCOL_VERSIONS = {
    "technocore": "0.13.0",
    "tclk": "tclk1",
    "kibble": "v1-observed",  # no public spec yet; observed in /r/kibble
    "fri": "0.2.0-dev",
}
