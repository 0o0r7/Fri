# FRI Deployment Guide

This guide covers deploying FRI to production using free-tier services. The architecture has three runtime components plus a data pipeline.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Vercel (Frontend — free tier)                            │
│  Vite/React SPA, static build                             │
│  vercel.json rewrites /api/* → Render backend             │
│  Serves /data/*.json snapshots as static fallback        │
└──────────────┬───────────────────────────┬───────────────┘
               │ /api/* (REST + SSE)        │ /data/*.json (fallback)
               ▼                            ▼
┌──────────────────────────┐   ┌────────────────────────────┐
│  Render (Backend — free)  │   │  Committed JSON in repo    │
│  FastAPI + uvicorn        │   │  web/public/data/*.json     │
│  collector.py long-poll   │   │  Updated by GitHub Actions │
│  SSE fan-out via EventBus │   │  every 2h                  │
└────────────┬─────────────┘   └────────────────────────────┘
             │
             ▼
┌──────────────────────────┐
│  Managed Redis (free)     │
│  Aiven Valkey / Upstash   │
│  TLS (rediss://)          │
└──────────────────────────┘
```

> **Event bus:** SSE events fan out through an **in-process bus** by default
> (`FRI_EVENT_BUS=memory`) — zero Redis pub/sub commands. Set
> `FRI_EVENT_BUS=redis` only for multi-process deployments (it restores
> pub/sub fan-out unchanged).

---

## Step 1: Managed Redis (free)

Any managed Redis/Valkey with a `rediss://` (TLS) connection string works.
Recommended: **Aiven for Valkey** — free forever, no credit card, and **no
per-command billing at all** (Upstash's free tier caps at 500K commands/month
and hard-stops the database when the cap is reached — FRI outgrew it).

**Option A — Aiven Valkey (recommended):**

1. Create a free account at [aiven.io](https://aiven.io/free-valkey-database)
2. Create a **Valkey** service on the **Free** plan (1 CPU / 1 GB RAM)
3. Wait for the status to become `Running`, open **Overview → Connection information**
4. Copy the **Service URI** (click to reveal the password first):
   ```
   rediss://default:PASSWORD@HOST.aivencloud.com:PORT
   ```

**Option B — Upstash Redis (free):**

1. Create a free account at [upstash.com](https://upstash.com)
2. Create a **Regional Database** (free tier: 256MB, 500K commands/month)
3. Copy the connection string — it should look like:
   ```
   rediss://default:PASSWORD@HOST.upstash.io:6379
   ```

> **Important:** The scheme must be `rediss://` (two s's) for TLS. Using `redis://` will cause `Connection closed by server` errors. Paste the full URI the provider's console generates — never type the password by hand (special characters break the URL).

---

## Step 2: Render Backend (free)

1. Create a free account at [render.com](https://render.com)
2. Create a new **Web Service** (free tier)
3. Connect your GitHub repo
4. Configure:
   - **Root Directory:** (repo root)
   - **Runtime:** Python 3
   - **Build Command:**
     ```bash
     pip install --upgrade pip && pip install -r backend/requirements.txt
     ```
   - **Start Command:**
     ```bash
     uvicorn backend.app:app --host 0.0.0.0 --port $PORT
     ```
   - **Health Check Path:** `/api/health`
5. Set environment variables:

   | Variable | Value | Notes |
   |----------|-------|-------|
   | `REDIS_URL` | `rediss://default:PASSWORD@HOST...` | Must use `rediss://` for TLS |
   | `FRI_EVENT_BUS` | `memory` | `memory` (default) = in-process SSE fan-out, zero pub/sub commands; `redis` = legacy pub/sub for multi-process deploys |
   | `FRI_COUNTS_INTERVAL` | `120` | Seconds between count updates (Redis budget) |
   | `FRI_HEALTH_INTERVAL` | `120` | Seconds between health checks |
   | `FRI_SNAPSHOT_INTERVAL` | `300` | Seconds between full snapshots |
   | `FRI_ROOMS_INTERVAL` | `300` | Seconds between room updates |
   | `FRI_COLLECTOR_RETRY_S` | `30` | Seconds between collector retries while Redis is down |
   | `FRI_SSE_PER_IP_LIMIT` | `5` | Max concurrent `/api/live` SSE streams per client IP |

6. Deploy and verify:
   - `https://YOUR-SERVICE.onrender.com/api/health` should return `{"status": "ok"}`
   - Logs should show `technocore.chat` HTTP 200 responses

### Render URL

On the free tier, your service URL is `https://<service-name>.onrender.com`. The service name is set when creating the service. Choose a professional name like `flop-reputation-index` or `fri-oracle`.

> **Custom domains** (e.g., `api.fri.example.com`) require a Render paid plan ($7/month). The free tier `*.onrender.com` subdomain is sufficient for FRI.

### Free-tier caveats

- Render free spins down after ~15 min idle; wake-up takes ~50s
- The frontend's 60s re-probe automatically upgrades from static to live when the backend wakes
- An open SSE stream with 15s heartbeats counts as traffic and keeps the instance warm

---

## Step 3: Vercel Frontend (free)

1. Create a free account at [vercel.com](https://vercel.com)
2. Import your GitHub repo
3. Configure:
   - **Root Directory:** `web`
   - **Build Command:** `npm run build` (auto-detected)
   - **Output Directory:** `dist` (auto-detected)
4. Update `web/vercel.json` — set the Render backend URL:
   ```json
   {
     "source": "/api/:path*",
     "destination": "https://YOUR-SERVICE.onrender.com/api/:path*"
   }
   ```
5. Deploy

### Verification

After deployment:

- [ ] `https://your-vercel-url/` loads the FRI dashboard
- [ ] Dashboard shows **LIVE** badge (backend connected)
- [ ] Network tab shows EventSource connected to `/api/live`
- [ ] `https://your-vercel-url/data/latest.json` returns valid JSON
- [ ] With backend stopped: dashboard shows **OFFLINE** badge, renders from snapshots (no error screen)
- [ ] All tabs work (Rooms, DIDs, Kibble, TCLK, Reputation)

---

## Step 4: GitHub Actions (automated data pipeline)

The workflow at `.github/workflows/update.yml` runs every 2 hours:

1. **Collector:** `python -m collector.main --once` — fetches from technocore.chat, produces 5 JSON files
2. **Sync:** `bash scripts/sync_data.sh` — copies `data/*.json` → `web/public/data/`
3. **Tests:** `pytest -q`
4. **Commit:** If JSON changed, commits to `main` with message `chore(data): update FRI ...`
5. The commit triggers Vercel to redeploy with fresh fallback data

### Manual trigger

Go to repo → Actions → "Update FRI" → Run workflow.

### Adjusting the schedule

Edit `.github/workflows/update.yml`:
```yaml
on:
  schedule:
    - cron: "0 */2 * * *"  # every 2 hours (default)
    # - cron: "0 * * * *"   # every hour (more frequent)
```

---

## Redis Command Budget

With the in-process event bus (default), pub/sub costs **zero** commands.
Only periodic snapshots and REST reads touch Redis:

| Loop | Interval | Commands/day | Commands/month |
|------|----------|-------------|----------------|
| Counts | 120s | ~720 | ~21.6K |
| Health | 120s | ~720 | ~21.6K |
| Snapshot | 300s | ~288 | ~8.6K |
| Rooms | 300s | ~288 | ~8.6K |
| Health snapshot | 300s | ~288 | ~8.6K |
| **Total** | | **~2.3K** | **~70K** |

Comfortably within Upstash's 500K free cap — and a non-metered provider
(Aiven Valkey) makes the budget moot. Historical note: before the event
bus, the collector PUBLISHed every ingested message (including full
backlog replays at each boot) to Redis 24/7 regardless of viewership —
that alone exhausted 500K commands in under a month. If you set
`FRI_EVENT_BUS=redis`, budget for that traffic on a metered provider.

---

## Local Development

### Docker (recommended)

```bash
docker compose -f docker-compose.base44.yml up -d
```

Frontend on `http://localhost:3000`, backend on `http://localhost:8000`, Redis included.

### Manual

```bash
# Terminal 1 — Redis
redis-server

# Terminal 2 — Backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app:app --host 0.0.0.0 --port 8000

# Terminal 3 — Frontend
cd web
npm install
npm run dev    # → http://localhost:5173
```

---

## Troubleshooting

### `Connection closed by server` (Render)

The `REDIS_URL` uses `redis://` instead of `rediss://`. Upstash requires TLS. Change the scheme to `rediss://` in Render environment variables.

### Frontend shows OFFLINE but backend is running

Check `web/vercel.json` — the `destination` URL must match your actual Render service URL. The rewrite must repeat `/api/`:
```json
"destination": "https://YOUR-SERVICE.onrender.com/api/:path*"
```

### JSON data is stale

Check GitHub Actions tab — did the last run succeed? Manually trigger: Actions → "Update FRI" → Run workflow.

### CORS errors

The `vercel.json` and `_headers` files set `Access-Control-Allow-Origin: *` on `/data/*`. If using a different host, add this header manually.

### Build fails on Vercel

Ensure **Root Directory** is set to `web` (not the repo root). Check Node version is 22+.
