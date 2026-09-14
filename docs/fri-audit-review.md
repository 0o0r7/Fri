# FRI Audit Review — Independent Verification of Bolt.new's Findings

**Reviewer:** Super Z (main FRI maintainer assistant)
**Date:** 2026-09-13
**Method:** Every claim was re-verified against the actual codebase (`github.com/0o0r7/Fri` @ main) with file:line evidence, a local reproduction of the suspected crash, live API probes against production (`fri-5s8s.onrender.com`), and a fresh clone of `flopkit-sdk@main` for the fingerprint comparison. Nothing below is guessed; each item is marked ✅ CONFIRMED / ❌ FALSE / ⚠️ PARTIAL, with the correction where needed.

**Live probe evidence (2026-09-13, ~18:28 UTC):**

```
GET /api/health                → {"status":"ok","stale":false,"technocore_ok":true,"timestamp":"2026-09-12T18:28:21Z"}  (fresh)
GET /api/health/snapshots?hours=168 → {"snapshots":[],"count":0}
GET /api/counts                → {"total_dids":266,"total_rooms":150,"total_jobs":47,"total_contracts":71,"total_dids_scored":266}
```

The empty snapshots array while the backend is healthy is the smoking gun for Critical Bug #1 (below).

---

## 1. Critical bug #1 — `.get()` on dataclasses in `_write_health_snapshot`

**Verdict: ✅ CONFIRMED (reproduced + proven live), with one mechanism correction.**

Evidence:
- `backend/collector.py:422` — `did_stats.get("last_active")` where values of `DidIndex._dids` are `DidStats` (`collector/did_index.py:59-60,115`: `@dataclass class DidStats`, `_dids: Dict[str, DidStats]`)
- `backend/collector.py:435` — `did_stats.get("first_seen")` — same type
- `backend/collector.py:448` — `c.get("state", "")` where values of `TclkIndex._contracts` are `TclkContract` (`collector/tclk.py:97-98,263`: `@dataclass`, state is a derived `@property`)
- `backend/collector.py:456` — `j.get("state")` where values of `KibbleIndex._jobs` are `KibbleJob` (`collector/kibble.py:185-186,286`: `@dataclass`, state is a derived `@property`)
- None of the three dataclasses defines a `.get()` method.
- Local reproduction: `DidStats(did=...).get("last_active")` → `AttributeError: 'DidStats' object has no attribute 'get'` (same for `TclkContract`, `KibbleJob`).
- Live proof: `/api/health/snapshots?hours=168` returns `count: 0` on a healthy backend → the 7-day ecosystem-health history has **never written a single snapshot in production**.

Mechanism correction: the backend does **not** crash every 5 minutes. `_health_snapshot_loop` (`backend/collector.py:404-411`) wraps the call in `try/except` and logs `Health snapshot failed: …` as a warning every 300s. So the real impact is: **feature silently dead + warning-log noise**, not a crash loop. Severity: HIGH (health-history feature completely broken) — but the fix urgency is "this release", not "production is burning".

~~Additional bug inside the same function that the audit missed:~~ **CORRECTION (self-review during the fix):** the audit reviewer (Super Z) initially claimed the terminal-state check `not in ("claimed", "refunded", "cancelled")` uses an invalid TCLK state. That was wrong: `collector/tclk.py:56` defines `KNOWN_OUTCOMES = frozenset({"claimed", "refunded", "cancelled"})` (TCLK SPEC §3.5 receipt outcomes) and `TclkContract.state` returns those outcome values verbatim when receipts exist. The original terminal check is semantically correct — the ONLY real defect is `.get()` vs attribute/property access. (Edge nuance: a receipt with an unknown outcome yields state `"receipted"`, which the check counts as active — negligible and left unchanged.)

**Correct fix sketch:**

```python
last = did_stats.last_active          # DidStats attribute
first = did_stats.first_seen          # DidStats attribute
state = c.state                       # TclkContract.state property
if state not in ("claimed", "refunded", "cancelled"):   # == KNOWN_OUTCOMES (SPEC §3.5)
    active_contracts += 1
if j.state in ("accepted", "attested"):                   # KibbleJob.state property
    accepted_jobs += 1
```

## 2. Dead code `useLiveFeed.ts`

**Verdict: ⚠️ PARTIAL — dead code confirmed; the "no proxy in production" claim is false.**

- ✅ Unused: the only repo-wide match for `useLiveFeed` is its own definition (`web/src/hooks/useLiveFeed.ts:21`). Safe and correct to delete.
- ❌ FALSE: "in production (Vercel) this proxy does not exist." `web/vercel.json:8-10` contains an active rewrite: `/tc/:path* → https://technocore.chat/:path*`. The path it calls therefore works in production too. The dev-only claim applies only to `web/vite.config.ts:25-29`.
- ⚠️ The "security issue" framing is overstated — it is a read-only pass-through to a public JSON API. The real (minor) reason to remove the `/tc/*` rewrite alongside the hook: it makes the FRI domain an open relay to technocore, aggregating all visitors behind Vercel egress IPs against technocore's per-IP limiter (600 reads/min/IP). Unused surface should not exist.

**Action:** delete `web/src/hooks/useLiveFeed.ts` AND remove the `/tc/:path*` rewrite from `web/vercel.json`.

## 3. `vercel.json` → Render + SSE

**Verdict: ⚠️ PARTIAL — SSE works in production (empirically proven); the spin-down concern is real.**

- ❌ "SSE is not supported": false. Verified end-to-end in production earlier: `/api/live` streams SSE through the Vercel rewrite to `fri-5s8s.onrender.com` (events + heartbeats observed). Vercel external rewrites pass streaming responses through.
- ✅ Render free tier spins a service down after ~15 min without **inbound** HTTP traffic (the collector's outbound polling does not count). Next visitor then hits a cold boot (~30–60s for Python + Redis seed). The frontend already mitigates: probe `/api/health`, fall back to committed static snapshots, re-probe every 60s up to 10 times (`web/src/hooks/useLiveData.ts:97-98,282-289`), and auto-upgrade to LIVE.
- Residual impact: first visitor after a long quiet period sees STATIC data for a while and a delayed LIVE upgrade. Medium UX issue, not critical. (Optional mitigations: external pinger on /api/health, or Render paid instance — cost/benefit is the maintainer's call.)

## 4. AGENTS.md says "long-poll 24 rooms" vs 11 in code

**Verdict: ✅ CONFIRMED.**

- `AGENTS.md:12` — "long-poll 24 rooms"
- `backend/collector.py:65` — `MONITORED_ROOMS = list(dict.fromkeys([*ALWAYS_POLL_ROOMS, "events"]))`
- `collector/config.py:42-53` — `ALWAYS_POLL_ROOMS` has exactly 10 entries → monitored = **11**.

**Action:** fix the doc to 11 (docs should never lead code), unless room expansion (item 5) changes the number first.

## 5. Live coverage (11 rooms) ≪ batch coverage (60 candidates)

**Verdict: ✅ CONFIRMED — and empirically quantified; but the audit missed why the code is conservative.**

- Batch: `collector/config.py:16` `SAMPLE_CANDIDATES = 60`, used by `collector/main.py:246-248`.
- Live: 11 rooms long-polled.
- Live probe today: `/api/counts` → `total_dids: 266, total_jobs: 47, total_contracts: 71` — the live in-memory index is a small fraction of the committed batch snapshot (`web/public/data/reputation.json` carries `total_dids_scored: 500` at the top-500 cap alone).
- What the audit missed: `backend/collector.py:117-119` documents that adding more concurrent long-polls **triggered technocore's rate limiter (429)** — the 11-room set is a deliberate trade-off, not an oversight. Naively "raise 11 → 24" will regress into 429s.

**Recommended fix (better than naive expansion):** hydrate the live indices at boot from the committed batch JSON (the backend already seeds Redis keys from `data/*.json` — `_seed_from_committed`, `backend/collector.py:149-166` — but starts `did_index/kibble_index/tclk_index` empty). Feed the committed snapshots **into the in-memory indices** at startup so live mode inherits full batch coverage, then keep long-polling the 11 high-signal rooms for real-time deltas. Optionally add a periodic "re-hydrate from latest batch commit" step. This closes the coverage gap without adding a single long-poll. (`did_index.py` already exposes `ingest_message(s)`; batch JSON is the same schema as `snapshot()` output, so a small loader is enough.)

## 6. `fetch.py` (flopkit, 3 retries) vs backend (`httpx`, no retry)

**Verdict: ✅ CONFIRMED (with nuance).**

- `collector/fetch.py:15-22` imports flopkit's `TechnocoreClient`; `ROOMS_MAX_RETRIES = 3` with 2/4/8s exponential backoff (`fetch.py:43-45,70-74`).
- `backend/collector.py` uses raw `httpx`: `_fetch_rooms` and `_seed_room` are single-shot per cycle; only `_poll_room` has backoff (1→30s). Failures of the single-shot paths self-heal on the next interval cycle (120–300s in the deployed config), so impact is modest, but unifying retry policy is good hygiene.

## 7. Fingerprint divergence (flopkit vs fallback)

**Verdict: ❌ FALSE — algorithms are byte-identical.**

- `flopkit-sdk@main`, `sdk/src/flopkit/technocore.py:133-135`: `did_note_fingerprint(did) = hashlib.sha256(did.encode()).hexdigest()[:16]`
- `collector/did_index.py:50-51` fallback: identical expression.
- It is true that `backend/requirements.txt` does not include flopkit (batch `requirements.txt:16` does), but there is **no behavioral divergence**. No action needed beyond keeping the fallback comment accurate (it already claims "Same algorithm" — verified correct).

## 8. No tests for the backend

**Verdict: ✅ CONFIRMED.**

`tests/` contains only collector-module tests (test_tclk/kibble/spam/score/did_index/reputation); `conftest.py` is path setup only. `backend/app.py`, `backend/collector.py`, `backend/store.py` have zero committed tests. Minimum viable set: (a) `_write_health_snapshot` unit test with populated fake indices (would have caught Bug #1 immediately), (b) REST smoke tests with fakeredis (store.py already proven compatible with fakeredis), (c) SSE endpoint smoke test.

## 9. Security items

| Claim | Verdict | Evidence / Note |
|---|---|---|
| CORS `allow_origins=["*"]` | ✅ CONFIRMED | `backend/app.py:112-117`. Acceptable for a strictly read-only public API. Revisit only if server-side write endpoints ever appear (Phase 6 DID publishing is designed client-side with the user's key, so the server stays read-only). |
| No rate limit on `/api/live` | ✅ CONFIRMED | `backend/app.py:204-241`. Each SSE client holds 1 Redis pubsub connection + ~1 cmd/s `get_message`. Dozens of concurrent viewers would strain Upstash free-tier connection/command limits. Add a per-IP concurrent-connection cap (e.g. 5–10) when traffic grows. |
| `/api/health/snapshots` `hours` unbounded | ✅ CONFIRMED | `backend/app.py:149` (`hours: int = 24`, no clamp). Practical blast radius is bounded by the 7-day Redis retention, but the handler also fetches ALL members with `zrange(0,-1)` then filters in Python (`app.py:153-165`) — clamp `hours ≤ 168` and use `zrangebyscore`. |

## 10. Performance / stability items

| Claim | Verdict | Note |
|---|---|---|
| Redis pub/sub can exhaust Upstash 500K cmds/mo | ⚠️ PARTIAL | True at docker defaults (5/10/30/60s ≈ 3.1M cmds/mo — this is exactly why env overrides were added). At the deployed intervals (DEPLOY.md: 120/120/300/300) writes ≈ 230K cmds/mo — under budget. Unquantified variable: Upstash billing of per-client `get_message` polling (1/s per SSE tab). Action: monitor the Upstash console; do not lower intervals. |
| `_snapshot_loop` every 30s recomputes everything | ⚠️ PARTIAL | 30s is the docker default (`backend/collector.py:61`); deployed = 300s via env. O(n) over hundreds of entries per cycle is negligible at current scale. |
| No cleanup for did/kibble/tclk indices (memory leak) | ✅ CONFIRMED (slow) | No pruning exists (only `room_messages` has a 200-window). Growth is bounded in practice by technocore's 7-day server retention, since only post-boot messages are ingested. The sharper issue is **staleness, not memory**: old jobs/contracts never age out of live scoring — this is the time-decay item already planned for Reputation v2. |
| `_seed_from_committed` only at startup | ✅ CONFIRMED (low impact) | `backend/collector.py:112`. Self-heals: snapshot loops rewrite all keys every SNAPSHOT_INTERVAL (≤300s deployed). |
| "No persistence for historical data" | ❌ MOSTLY FALSE | (a) Git-committed snapshots every 2h ARE the historical record (`.github/workflows/update.yml` cron `0 */2 * * *`); (b) `fri:health:snapshots` retains 7 days — currently empty **only** because of Bug #1. |

## 11. Frontend items

| Claim | Verdict | Note |
|---|---|---|
| Static `total_dids_scored` may be wrong if field missing | ⚠️ THEORETICAL | `useLiveData.ts:240` has a fallback chain; the committed `reputation.json` **does** contain the field (verified: `500`). No current defect. |
| LiveTicker counters spike after reconnect | ❌ MECHANISM BACKWARDS | `live-ticker.tsx:139-147` filters by message `ts` (`now - ts < 60000`). Delayed messages carry OLD timestamps → they are **excluded**, so counters under-count after reconnect; they do not spike. Real (cosmetic) issues: server/client clock-skew sensitivity and the `MAX_ITEMS=50` cap under-counting busy periods. |
| No handling for SSE parse errors | ✅ CONFIRMED (trivial) | `useLiveData.ts:193-195` silently ignores malformed events. Near-impossible today (backend self-serializes via `json.dumps`); a `console.warn` would suffice. |
| No per-DID lookup API | ✅ CONFIRMED | Routes are only health, health/snapshots, counts, rooms, dids, kibble, tclk, reputation, live. The per-DID page is client-side over the top-500 snapshot → DIDs outside the cap cannot be inspected. Real product gap; matches the roadmap (`/api/did/{did}/score` + `/profile`). |

---

## 12. Review of the strategic plan (Part 2, post-brief)

The plan's reading of `docs/fri-flop-ecosystem-knowledge-brief.md` is faithful. Checked specifics:

- "YP never mentions technocore" — matches brief (CONFIRMED there against the Yellow Paper text).
- "TCLK receipt frame is what a reputation layer would consume" — matches TCLK SPEC + brief.
- "97%+ of TCLK sample on the paper rail" — matches FRI's own observed sample; keep the "in our sample" qualifier when publishing.
- "800M FLOP ecosystem/growth bucket" — matches the Yellow Paper reserve line cited in the brief.
- Testnet Q4 2026 (~90d) — matches the teaser as documented in the brief.

Two tagging corrections for anything we publish:

1. **"Mainnet Q1 2027"** — the published source (teaser) states testnet Q4 2026 lasting ~90 days; a Q1 2027 mainnet is an **inference from that duration**, not a published date. Label it as such everywhere.
2. **"Main airdrop condition = following @flop_labs on X"** — this predates the brief and was never verified against a primary source. The brief explicitly lists airdrop mechanics/snapshot criteria as UNKNOWN. Treat as unverified rumor; do not present it as fact.

## 13. Corrected priority order (replaces the audit's week plan)

**P0 — do now (hours, all frontend/doc or one-function fixes):**
1. Fix `_write_health_snapshot`: attribute/property access (the terminal-state vocabulary was already correct — see §1 correction).
2. Delete `useLiveFeed.ts` + remove the `/tc/:path*` rewrite from `web/vercel.json`.
3. AGENTS.md: "24 rooms" → 11.
4. Add the minimal backend tests (health-snapshot unit test first — it is the regression guard for #1).

**P1 — this week:**
5. Close the live-coverage gap via boot-time hydration of indices from committed batch JSON (not naive room expansion — rate-limiter). Optionally a periodic re-hydrate.
6. Clamp `hours ≤ 168` + `zrangebyscore` on the snapshots endpoint.
7. Add `/api/did/{did}/score` + `/api/did/{did}/profile` (per-DID lookup; unlocks agent-facing SKILL.md).

**P2 — next:**
8. Reputation v2 signals (receipt-integrity, rail-tiering, time-decay, counterparty concentration, sybil flags) as specified in the knowledge brief.
9. SSE per-IP connection cap; index retention/decay policy; Upstash budget monitoring.
10. Phase 6 visibility steps exactly as in the brief (signed intro post, daily signed report, contribution proofs) — after P0/P1 so the first public impression is of a healthy product.

---

**Bottom line:** of the audit's three "critical bugs," one is fully real and now **proven live** (health snapshots never written — silent feature death, not a crash loop), one is half-real (dead hook, but its production proxy does exist), and one is empirically false (SSE works). The coverage-gap and missing-backend-tests findings are the two most valuable structural catches. The fingerprint-divergence concern is disproven by source. The strategic plan built on the knowledge brief is sound, with the two source-tagging corrections above.

## 14. Implementation status (updated after the fix session)

All P0 + P1 items and the SSE-cap item from P2 are now implemented, tested, and verified against the production deployment:

| # | Item | Status | Evidence |
|---|------|--------|----------|
| 1 | `_write_health_snapshot` fix | ✅ shipped | commit `74161dc`; first production snapshots written 19:05:37Z, recurring every 5 min |
| 2 | Dead `/tc` surface removal (hook + rewrite) | ✅ shipped | commit `12d1615`; `/tc/r/lobby` → 404, `/api` rewrite untouched |
| 3 | AGENTS.md room count | ✅ shipped | commit `12d1615` |
| 4 | Backend tests | ✅ shipped | commit `bb8dbc8`; suite grew 93 → 120 tests, all green |
| 5 | Boot-time index hydration | ✅ shipped | commits `56fcbdb`/`8eabcfa`; first counts read after boot: 699 DIDs / 268 jobs / 559 contracts (vs. climbing from ~0 before); first health snapshot after boot: `daily_active (3668) ≠ total_dids (3701)` — the boot artifact is gone |
| 6 | `hours` clamp + `zrangebyscore` | ✅ shipped | commit `de2fd9c`; `hours=999999` → 200 clamped, scan bounded server-side |
| 7 | `/api/did/{did}/score` + `/profile` | ✅ shipped | commit `de2fd9c`; live: 200 with full breakdown, 404 `did_not_found` for unknown DIDs, live-fallback covers DIDs newer than the last snapshot |
| 8 | SSE per-IP cap | ✅ shipped | commit `304f230`; live: 6 concurrent streams held → 7th got 429; single streams unaffected (frontend falls back to REST polling) |
| 9 | Reputation v2 signals | ⏳ gated | formula change alters every published score — needs FLOP-team sign-off on weights/caps before shipping (schema version bump) |
| 10 | Phase 6 visibility | ⏳ gated | requires FLOP team channels/identity (signed intro post, daily reports, contribution proofs) |

Notable engineering details worth carrying into the team review:

- Hydration is a lossless round-trip for everything the batch publishes (states, counts, payer/payee attribution, per-room counts) and deliberately drifts only where the snapshot publishes nothing (frame timestamps, result/accept authors) — asserted property-wise in `tests/test_hydration.py`, including a real-data schema-drift canary.
- Offer-keyed/contract-keyed pairs in `tclk.json` (13 in the current batch) are restored `offer_linked_elsewhere=True`, so `did_stats()` never double-counts deals across restarts.
- Receipt frames are synthesized only when the derived state actually comes from one, keeping `deals_refunded_as_payer` semantics identical between hydrated and live-observed contracts.
- The boot-sequence overlap (committed baseline + live seed window) can double-count at most one seed window per boot; replay guards (`first offer/poster wins`) prevent duplicate entities. Documented tradeoff, boots are rare.

---

## §15 — Event-bus refactor + counter-floor fix (2026-09-14, post-migration)

Follow-up engineering after the Upstash free-tier exhaustion incident (500K
commands/month cap hit in production, 2026-09-12; database migrated to Aiven
Valkey free — no per-command billing — on 2026-09-14).

| # | Action | Status | Evidence |
|---|--------|--------|----------|
| 1 | In-process EventBus replaces Redis pub/sub by default (`FRI_EVENT_BUS=memory`; `redis` = legacy mode) | ✅ shipped | commit c395aee; per-message PUBLISH (collector.py:282 in the old code) removed; 5 unit tests + SSE route test |
| 2 | Poll-sequencing decoupled from Redis health | ✅ shipped | emit can no longer raise mid-poll; the re-fetch/re-ingest coupling found during the incident is structurally gone |
| 3 | Hydrate counters floored at published totals | ✅ shipped | commit d384740; canary caught it live: tclk.json total_contracts=892 vs top-500 list (dids: 2510 vs 500); boot now reports 892/2510, not 500/500 |
| 4 | Docs: DEPLOY.md provider guide (Aiven recommended), command-budget post-mortem, README/AGENTS architecture | ✅ shipped | commit b745be9 (all English) |
| 5 | GitHub hygiene | ✅ | 3 stale fully-merged branches deleted (`project-debug`, `update-repo-docs`, `base44/setup-6781513e`); only `main` remains |

Live verification (2026-09-14T04:57Z): /api/counts `total_jobs=196` (old-code
boot signature was 54 — floor 154 proves new code), contracts 928 ≥ 892 floor,
health 200 ok, SSE streaming real feed events through the new deploy.
Suite: 135 tests passing.
