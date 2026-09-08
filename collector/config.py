"""Configuration and thresholds for FRI collector."""

from dataclasses import dataclass
from typing import List

BASE_URL = "https://technocore.chat"

# ---------------------------------------------------------------------------
# Room sampling (TQR v1 — unchanged)
# ---------------------------------------------------------------------------

# How many rooms to pull from /rooms
ROOMS_LIMIT = 150

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
