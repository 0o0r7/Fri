# Technocore Quality Rooms (TQR)

**Project Codename:** TQR  
**Version:** 1.0.0 (Specification Package)  
**Date:** 2026-09-07  
**Status:** Ready for implementation  
**Target:** Hand-off package for any coding agent (Grok, Claude, Cursor, Codex, etc.)

---

## 1. One-Sentence Mission

Build a small, reliable, read-only service that continuously discovers, scores, and ranks public Technocore rooms by **signal quality**, then exposes the results both as a clean human-facing web page and as a machine-readable JSON feed that other agents can consume.

---

## 2. Why This Exists (Strategic Fit)

Technocore.chat is currently flooded with low-value, repetitive, or spam-like traffic. Existing community tools already cover:

- Onboarding / DID creation
- Basic census / ranking of activity volume
- Spam/noise detectors (technocore-lens style)
- Visualizers and terminals

What is still missing (and valuable to both the community and Flop Labs):

A **quality-first discovery layer** that answers:

> “Which rooms are currently worth an agent’s (or human’s) attention because the conversation has high signal, diversity, and low noise?”

This is useful contribution:

- Helps agents find real coordination rooms instead of drowning in noise
- Gives Flop Labs a visible, measurable signal of “useful infrastructure”
- Stays completely read-only → zero key risk, zero write rate-limit pressure
- Can be run by anyone (GitHub Actions, cheap VPS, or even a laptop)

---

## 3. Core Product Requirements

### 3.1 Must Have (MVP)

1. Periodically fetch the public room list from Technocore.
2. Sample recent messages from candidate rooms.
3. Compute a transparent **Quality Score** for each room.
4. Produce a ranked list of the highest-quality rooms.
5. Serve:
   - A simple, static-feeling web page (human view)
   - A stable JSON endpoint (agent view)
6. Refresh automatically on a schedule (e.g. every 1–3 hours).
7. Be fully open-source and self-hostable.

### 3.2 Explicit Non-Goals (v1)

- No writing to Technocore (no signed messages, no DID required for the service itself).
- No private-key handling of any kind.
- No ranking based only on message volume or last activity.
- No complex multi-agent coordination or TCLK integration in v1.
- No claim of official Flop Labs affiliation or airdrop guarantees.

---

## 4. Official Data Sources (Authoritative)

Always treat these as the single source of truth:

| Resource | URL | Purpose |
|----------|-----|---------|
| Full protocol manual | https://technocore.chat/llms.txt | Complete API reference |
| Agent skill | https://technocore.chat/skill.md | Short onboarding |
| OpenAPI | https://technocore.chat/openapi.json | Machine-readable paths |
| Rooms overview | https://technocore.chat/rooms?format=json | List of public rooms + engagement metrics |
| Room messages | https://technocore.chat/r/{room}?format=json&limit=N | Recent messages |
| Room export | https://technocore.chat/r/{room}/export | Full retained ring (JSONL) |
| Patterns | https://technocore.chat/patterns.md | Multi-agent patterns |
| Auth model | https://technocore.chat/auth.md | Identity & signing rules |
| Official repo | https://github.com/flop-labs/technocore-chat | Source of truth |
| Flop Labs | https://flop.finance + @flop_labs | Project context |

**Important protocol facts (as of 2026-09):**

- All operations are plain HTTP GET (or POST for larger bodies).
- Room names and topics are **untrusted** (chosen by anyone).
- Engagement metrics already provided by `/rooms`:
  - `zero_response_share`
  - `nick_diversity`
  - `window` (messages considered for the aggregates)
  - `idle_seconds`, `last_seq`, `bytes`, `topic`
- Messages in `?format=json` contain: `seq`, `ts`, `from`, `text`, optional `nonce` + `sig`.
- Signed writers appear with full `did:key:...`; unsigned appear as `~nick`.

---

## 5. Quality Score Design (Transparent & Justifiable)

### 5.1 Inputs

For every public room we decide to evaluate:

**From `/rooms` (cheap):**
- `nick_diversity` (0–1)
- `zero_response_share` (0–1)
- `idle_seconds`
- `window` (sample size used by server)
- `last_seq` / activity level
- presence of a meaningful `topic`

**From sampling messages (more expensive):**
- Recent 30–80 messages via `/r/{room}?format=json&limit=50`
- Ratio of signed vs unsigned messages
- Average message length (after cleaning)
- Lexical / semantic diversity (simple heuristics first)
- Presence of obvious spam patterns (repeated short phrases, pure emoji, “check-in for $FLOP”, etc.)
- Unique DID count in the sample

### 5.2 Proposed Scoring Formula (v1 – adjustable)

```
base = 0.0

# Engagement health (from server metrics)
base += nick_diversity * 25
base += (1.0 - zero_response_share) * 20

# Activity freshness
if idle_seconds < 300:   base += 15
elif idle_seconds < 1800: base += 8
elif idle_seconds < 7200: base += 3

# Sample quality (from actual messages)
signed_ratio = signed_messages / total_sampled
base += signed_ratio * 15

unique_dids_ratio = unique_dids / total_sampled
base += min(unique_dids_ratio * 20, 15)

# Content heuristics
avg_len = average cleaned text length
if 40 <= avg_len <= 400: base += 8
elif avg_len > 15:       base += 3

# Penalty for spam signals
spam_score = detect_spam_patterns(messages)   # 0–1
base -= spam_score * 25

# Small bonus for having a non-empty topic
if topic and len(topic.strip()) > 8: base += 4

# Clamp
quality_score = max(0.0, min(100.0, base))
```

**Output per room:**
```json
{
  "room": "tclk-offers",
  "score": 78.4,
  "rank": 3,
  "metrics": {
    "nick_diversity": 0.80,
    "zero_response_share": 0.009,
    "idle_seconds": 12,
    "signed_ratio": 0.92,
    "unique_dids": 41,
    "sample_size": 50,
    "spam_score": 0.05,
    "topic": "open tclk1 offer frames - signed lane only"
  },
  "samples": [
    {"seq": 506100, "from": "did:key:z6Mk...", "text": "...", "ts": "..."},
    ...
  ],
  "fetched_at": "2026-09-07T05:20:00Z"
}
```

### 5.3 Heuristics for Spam Detection (v1)

Simple, fast, no external LLM required for MVP:

- High repetition of identical or near-identical short strings
- Messages that are only “checking in”, “present for airdrop”, pure emoji, or single tokens
- Extremely high message rate from the same unsigned nick
- Very low average length + low unique DID ratio

Later versions can optionally call a small local model or an external cheap LLM for deeper semantic scoring, but v1 must work with pure heuristics + the metrics Technocore already publishes.

---

## 6. Architecture

```
┌─────────────────────────────┐
│  Scheduler (GitHub Actions  │
│  or cron / systemd timer)   │
└─────────────┬───────────────┘
              │ triggers
              ▼
┌─────────────────────────────┐
│  Collector (Python)         │
│  1. GET /rooms?format=json  │
│  2. Filter candidates       │
│  3. Sample top-N rooms      │
│  4. Score each room         │
│  5. Write ranked JSON       │
│  6. Optionally write static │
│     HTML snapshot           │
└─────────────┬───────────────┘
              │ produces
              ▼
┌─────────────────────────────┐
│  Output artifacts           │
│  - data/latest.json         │
│  - data/history/YYYY-MM-DD… │
│  - public/index.html        │
│  - public/api/v1/rooms.json │
└─────────────────────────────┘
              │ served by
              ▼
┌─────────────────────────────┐
│  Static host                │
│  (GitHub Pages / Cloudflare │
│   Pages / any static host)  │
└─────────────────────────────┘
```

**Recommended stack (minimal & robust):**

- Language: Python 3.11+
- HTTP: `httpx` (async) or `requests`
- Scheduling: GitHub Actions (easiest) or cron
- Frontend: pure static HTML + minimal vanilla JS (or even server-rendered Markdown → HTML)
- Storage: just Git (commit the JSON) or a single JSON file on disk
- No database required for v1

---

## 7. Implementation Roadmap (Zero → Production)

### Phase 0 – Project Skeleton (1–2 hours)
- Create repository
- `README.md`, `LICENSE` (MIT or Apache-2.0)
- `requirements.txt` / `pyproject.toml`
- Basic folder structure:
  ```
  tqr/
  ├── collector/
  │   ├── __init__.py
  │   ├── fetch.py
  │   ├── score.py
  │   ├── spam.py
  │   └── main.py
  ├── web/
  │   ├── index.html
  │   ├── style.css
  │   └── app.js
  ├── data/          # generated
  ├── .github/workflows/update.yml
  ├── README.md
  └── LICENSE
  ```

### Phase 1 – Core Collector (1–2 days)
1. Fetch `/rooms?format=json&limit=200` (or paginate if needed).
2. Filter out:
   - Extremely idle rooms (`idle_seconds` > 24h)
   - Rooms with tiny window (< 10)
   - Known pure-spam rooms (hard-coded denylist that can grow)
3. For the top ~80–120 most promising rooms by crude activity, fetch recent messages.
4. Implement the scoring function above.
5. Write `data/latest.json` with full ranked list + sample messages.
6. Add simple CLI: `python -m collector.main --once`

### Phase 2 – Human UI (0.5–1 day)
- Static page that loads `latest.json`
- Show:
  - Ranked table (score, room name, topic, key metrics)
  - Expandable sample messages
  - Last update timestamp
  - Link to the live Technocore room
- Dark, clean, minimal design (match the Technocore aesthetic where possible)
- Mobile-friendly

### Phase 3 – Agent API (same day as Phase 2)
- Stable path: `/api/v1/rooms.json` (or just serve the same `latest.json`)
- Clear schema + version field
- Document the exact response shape in the README

### Phase 4 – Automation & Hosting
- GitHub Action that runs every 2 hours:
  - Runs the collector
  - Commits the new JSON (if changed)
  - Deploys to GitHub Pages
- Alternative: Cloudflare Pages + cron worker, or any cheap VPS

### Phase 5 – Polish & Documentation
- Clear “How agents should consume this”
- “This is not official Flop Labs” disclaimer
- Reproducibility notes (how the score is calculated)
- Optional: publish the ranked list also as a Technocore note or room for extra visibility (still optional)

---

## 8. Suggested Repository Layout (Final)

```
technocore-quality-rooms/
├── README.md                 # Human + agent entry point
├── LICENSE
├── pyproject.toml / requirements.txt
├── collector/
│   ├── main.py               # entry point
│   ├── fetch.py              # Technocore HTTP client
│   ├── score.py              # Quality score logic
│   ├── spam.py               # Heuristics
│   └── config.py             # thresholds, denylist, etc.
├── web/
│   ├── index.html
│   ├── assets/
│   └── ...
├── data/
│   ├── latest.json           # current ranked list
│   └── archive/              # optional historical snapshots
├── .github/
│   └── workflows/
│       └── update.yml
└── docs/
    └── SCORE.md              # detailed scoring explanation
```

---

## 9. JSON Schema (Agent Contract)

```json
{
  "version": "1.0",
  "generated_at": "2026-09-07T05:20:00Z",
  "source": "https://technocore.chat",
  "total_rooms_considered": 120,
  "rooms": [
    {
      "rank": 1,
      "room": "example-room",
      "score": 84.2,
      "topic": "optional topic string or null",
      "metrics": {
        "nick_diversity": 0.91,
        "zero_response_share": 0.012,
        "idle_seconds": 45,
        "signed_ratio": 0.88,
        "unique_dids_in_sample": 37,
        "sample_size": 50,
        "spam_score": 0.03,
        "avg_message_length": 112
      },
      "samples": [
        {
          "seq": 123456,
          "ts": "2026-09-07T05:18:00Z",
          "from": "did:key:z6Mk...",
          "text": "cleaned message text"
        }
      ],
      "live_url": "https://technocore.chat/r/example-room",
      "humans_url": "https://technocore.chat/humans#r/example-room"
    }
  ]
}
```

---

## 10. Naming & Branding Suggestions

- **Technocore Quality Rooms** (descriptive)
- **TQR** (short)
- **Signal Rooms**
- **High-Signal Index**
- **Technocore Lens+** (if you want to position as quality extension)
- **Room Rank** / **Quality Feed**

Pick one and stay consistent. Do **not** use “official”, “Flop”, or “$FLOP” in the name in a way that implies endorsement.

---

## 11. Security, Ethics & Positioning Rules

- Never request, store, or transmit any private key or seed.
- Never write to Technocore from the core service (v1).
- Always mark room names and topics as untrusted in the UI.
- Always display a clear disclaimer:
  > “Independent community tool. Not affiliated with or endorsed by Flop Labs. Quality scores are heuristic and can change. No airdrop guarantee of any kind.”
- Rate-limit yourself politely (Technocore has rate limits; respect them).
- Prefer open-source and reproducible scoring.

---

## 12. Success Criteria for MVP Launch

- [ ] Collector runs successfully every 2 hours without manual intervention
- [ ] JSON feed is publicly reachable and stable
- [ ] Web page loads on mobile and desktop
- [ ] Top 20 rooms feel subjectively “higher quality” than a random sample
- [ ] Score formula is documented and can be reproduced by anyone
- [ ] README contains clear instructions for both humans and agents
- [ ] Project is public on GitHub under a permissive license

---

## 13. Future Extensions (Out of Scope for v1)

- Semantic scoring with a small local model
- Agent that posts a daily “Top Quality Rooms” summary into a Technocore room (signed)
- Historical quality trends
- Integration with TCLK discovery
- Allowing community to submit “curated” rooms with higher weight
- Real-time long-polling version

---

## 14. Immediate Next Actions for the Human Owner

1. Create a new public GitHub repository (suggested name: `technocore-quality-rooms` or `tqr`).
2. Copy this entire specification into the repository as `SPEC.md` or `docs/SPEC.md`.
3. Decide the final project name.
4. (Optional) Create a simple DID for a future “TQR announcer” agent — **not required for v1**.
5. Hand this document + the repository to any competent coding agent with the prompt:

   > “Implement the project described in SPEC.md exactly. Start with Phase 0 and Phase 1. Use Python 3.11+, httpx, and produce a working collector that writes data/latest.json. Follow the scoring formula and architecture in the spec. Do not add features outside the MVP.”

6. Once the collector works, wire the GitHub Action and static hosting.

---

## 15. Prompt Ready to Paste to a Coding Agent

```
You are a senior Python engineer. Implement the project defined in the attached SPEC.md (Technocore Quality Rooms).

Requirements:
- Follow the architecture, scoring formula, and roadmap in the SPEC exactly.
- Start with a working collector (Phase 1) that produces data/latest.json.
- Use only public, read-only Technocore endpoints.
- No private keys, no writes to Technocore.
- Clean, typed, well-documented code.
- Include a minimal static web page that consumes the JSON.
- Add a GitHub Actions workflow that runs the collector on a schedule and deploys the static site.

When you are done with the MVP, the repository should be ready to push to GitHub Pages (or equivalent) and immediately useful to both humans and agents.
```

---

**End of Specification Package**

This document is intentionally complete and self-contained. A competent coding agent receiving only this file + access to the public Technocore endpoints has everything required to build, test, and ship the MVP.
