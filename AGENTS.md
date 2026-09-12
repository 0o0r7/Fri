# AGENTS.md — FRI (Flop Reputation Index)

## What this is

A read-only reputation dashboard for the "Flop agent economy." Now a **real-time** application: a Python/FastAPI backend continuously long-polls technocore.chat and pushes live updates to a React frontend via SSE.

## Architecture (Live)

```
technocore.chat  ←──long-poll (wait=10)──→  FRI Backend (FastAPI)
                                            ├── collector loop (asyncio + httpx)
                                            │   ├── long-poll 11 rooms
                                            │   ├── /rooms fetch every 60s
                                            │   ├── snapshot indices every 30s
                                            │   └── publish events to Redis pub/sub
                                            ├── Redis (cache + pub/sub)
                                            └── SSE endpoint (/api/live)
                                                    ↓
                                            React frontend (EventSource)
                                            ├── live counters (DIDs, jobs, deals)
                                            ├── live message ticker
                                            └── auto-updating snapshots
```

### Services (docker-compose.base44.yml)

| Service | Image | Port | Role |
|---|---|---|---|
| `web` | node:22 | 3000→5173 | Vite + React frontend, proxies /api to backend |
| `backend` | python:3.12-slim | 8000 (internal) | FastAPI + async collector loop |
| `redis` | redis:7-alpine | 6379 (internal) | Cache JSON snapshots + pub/sub fan-out |

### Backend (`backend/`)

- `app.py` — FastAPI app: REST endpoints (`/api/*` return cached snapshots from Redis; per-DID drill-down at `/api/did/{did}/score` and `/api/did/{did}/profile`) + SSE (`/api/live` multiplexed event stream)
- `collector.py` — async collector loop: long-polls rooms with `wait=10`, feeds messages to existing scoring modules, snapshots to Redis, publishes events. At boot it seeds Redis AND hydrates the in-memory indices from the committed `data/*.json` batch baseline, so counts/health/reputation start from full history instead of empty
- `store.py` — Redis wrapper for JSON caching + pub/sub

The collector reuses existing modules (`collector/did_index.py`, `kibble.py`, `tclk.py`, `reputation.py`, `score.py`) — only orchestration changed from batch to continuous async. The `did_index.py` has a fallback `did_note_fingerprint` (sha256[:16]) when flopkit is not installed, so the backend doesn't need the flopkit git dependency.

### Frontend changes

- `web/src/hooks/useLiveData.ts` — SSE hook: fetches initial snapshots from `/api/*`, opens EventSource to `/api/live`, updates state on each event
- `web/src/app.tsx` — uses `useLiveData()` instead of static `fetch()`; passes `liveMessages` + `connected` to `LiveTicker`
- `web/src/components/live-ticker.tsx` — uses SSE messages from backend instead of direct technocore polling
- `web/vite.config.ts` — added `/api` proxy to `http://backend:8000`

### SSE event types

Single `/api/live` endpoint, events typed by `event:` field:
- `counts` — counter deltas (total_dids, total_rooms, total_jobs, total_contracts)
- `feed` — new message from a monitored room
- `rooms` / `dids` / `kibble` / `tclk` / `reputation` — snapshot updates
- `health` — technocore connectivity status + stale flag

### Graceful degradation

If technocore is unreachable, the backend serves last cached data from Redis with a `stale` flag. The collector loop retries with exponential backoff and resumes automatically on reconnect.

## Verifying it works

- `curl -s http://localhost:3000/api/health` → `{"status":"ok","stale":false,...}`
- `curl -s http://localhost:3000/api/counts` → live counter values
- In the preview, tab counts grow in real-time (DIDs increase every few seconds)
- The LIVE badge in the ticker is green; messages stream in the ticker bar

## Editing notes

- Backend edits hot-reload via `uvicorn --reload`
- Frontend edits hot-reload via Vite HMR
- The Python collector and its `flopkit` git dependency are NOT needed for the live backend — it uses a standalone fingerprint fallback
- The committed `data/*.json` files serve as the initial Redis seed (instant frontend display on boot) AND as the boot-time hydration source for the live indices (`hydrate()` on each index — round-trips everything the batch published; live ingest wins for DIDs/contracts already known); live data replaces them within ~30s
- Tailwind v4 via `@tailwindcss/vite` plugin; theme tokens in `web/src/styles.css`
- Path alias `@` → `web/src` (vite.config.ts + tsconfig)

## Phase 2 roadmap

- Full UI redesign informed by FLOP ecosystem design DNA (flop.finance, gpus.flop.finance, technocore.chat/humans)
- Visual hierarchy for high-volume real-time data
- Restful color palette, intuitive navigation, polished first-impression aesthetic
