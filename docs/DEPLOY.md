# FRI Deployment Guide

This guide covers deploying FRI to production. The frontend is a static Vite build; the collector runs on GitHub Actions every 2 hours and commits fresh JSON to the repo.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  GitHub Actions (every 2h)                          │
│  1. Run collector (python -m collector.main --once) │
│  2. Sync data/ → web/public/data/                   │
│  3. Run tests (pytest)                              │
│  4. Commit JSON if changed                          │
│  5. Build frontend (npm run build)                  │
└──────────────────────┬──────────────────────────────┘
                       │ commits JSON
                       ▼
┌─────────────────────────────────────────────────────┐
│  GitHub repo (your-handle/fri)                      │
│  - data/*.json (committed, 5 files)                 │
│  - web/public/data/*.json (committed, synced copy)  │
│  - web/dist/ (built by CI, not committed)           │
└──────────────────────┬──────────────────────────────┘
                       │ auto-deploy on push
                       ▼
┌─────────────────────────────────────────────────────┐
│  Static host (Vercel or Cloudflare Pages)           │
│  - Serves web/dist/ as the site root                │
│  - /data/*.json served with 2h cache + CORS *       │
│  - /assets/* served with 1y immutable cache         │
└─────────────────────────────────────────────────────┘
```

---

## Option A: Vercel (recommended — simplest)

### Prerequisites
- GitHub account
- Vercel account (free tier is enough)

### Steps

1. **Push the repo to GitHub:**
   ```bash
   cd /path/to/fri
   git init
   git add .
   git commit -m "FRI — Flop Reputation Index"
   git remote add origin https://github.com/YOUR_HANDLE/fri.git
   git push -u origin main
   ```

2. **Import to Vercel:**
   - Go to [vercel.com/new](https://vercel.com/new)
   - Import your `fri` repo
   - Set **Root Directory** to `web`
   - Build command: `npm run build` (auto-detected)
   - Output directory: `dist` (auto-detected)
   - Click **Deploy**

3. **Done.** Vercel auto-deploys on every push to `main`.

4. **Custom domain (optional):**
   - Go to Project Settings → Domains
   - Add your domain (e.g., `fri.yourdomain.com`)
   - Vercel handles SSL automatically

### Why Vercel
- Zero config for Vite projects
- Free tier covers FRI easily (static site, no server functions)
- Edge cache for JSON files
- Auto-deploy on push

---

## Option B: Cloudflare Pages

### Prerequisites
- GitHub account
- Cloudflare account (free tier is enough)

### Steps

1. **Push the repo to GitHub** (same as Vercel step 1)

2. **Create a Cloudflare Pages project:**
   - Go to [pages.cloudflare.com](https://pages.cloudflare.com)
   - Click **Create a project** → **Connect to Git**
   - Select your `fri` repo
   - Set **Root directory** to `web`
   - Build command: `npm run build`
   - Build output directory: `dist`
   - Click **Save and Deploy**

3. **Done.** Cloudflare auto-deploys on every push to `main`.

4. **Custom domain (optional):**
   - Go to Project → Custom domains
   - Add your domain
   - Cloudflare handles SSL automatically

### Why Cloudflare Pages
- Unlimited requests on free tier
- Global CDN with 300+ locations
- `_headers` file already in `web/` for cache + CORS config

---

## GitHub Actions (automated collector)

The workflow at `.github/workflows/update.yml` runs every 2 hours:

1. **Collector:** `python -m collector.main --once` — fetches from technocore.chat, produces 5 JSON files
2. **Sync:** `bash scripts/sync_data.sh` — copies `data/*.json` → `web/public/data/`
3. **Tests:** `pytest -q` — verifies scoring logic
4. **Commit:** If JSON changed, commits to `main` with message `chore(data): update FRI rankings`
5. **Build:** `npm run build` — verifies the frontend compiles

The commit triggers Vercel/Cloudflare to redeploy with fresh data.

### Manual trigger
You can also trigger the workflow manually from GitHub:
- Go to repo → Actions → "Update FRI" → Run workflow

### Adjusting the schedule
Edit `.github/workflows/update.yml`:
```yaml
on:
  schedule:
    - cron: "0 */2 * * *"  # every 2 hours (default)
    # - cron: "0 * * * *"   # every hour (more frequent)
    # - cron: "0 */6 * * *" # every 6 hours (less frequent)
```

---

## Custom domain (GitHub Education credits)

If you have GitHub Student Developer Pack:
1. Register a domain through Namecheap/other registrar (free with Education Pack)
2. Point DNS to your hosting provider:
   - **Vercel:** Add CNAME `fri → cname.vercel-dns.com`
   - **Cloudflare:** Add CNAME `fri → your-project.pages.dev`
3. Add the domain in your hosting provider's dashboard

---

## Local development

```bash
# Collector
cd fri
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m collector.main --once

# Frontend
cd web
npm install
npm run dev    # → http://localhost:5173
```

---

## Verification checklist

After deployment, verify:

- [ ] `https://your-domain/` loads the FRI dashboard
- [ ] `https://your-domain/data/latest.json` returns valid JSON
- [ ] `https://your-domain/data/dids.json` returns valid JSON
- [ ] `https://your-domain/data/kibble.json` returns valid JSON
- [ ] `https://your-domain/data/tclk.json` returns valid JSON
- [ ] `https://your-domain/data/reputation.json` returns valid JSON
- [ ] All 5 tabs work (Rooms, DIDs, Kibble, TCLK, Reputation)
- [ ] DID lookup works (paste a `did:key:...` in the nav search bar)
- [ ] GitHub Actions runs successfully every 2 hours
- [ ] JSON data refreshes after each Actions run

---

## Troubleshooting

### Build fails on Vercel/Cloudflare
- Check that **Root Directory** is set to `web` (not the repo root)
- Check that Node version is 22+ (set in `web/package.json` engines if needed)

### JSON data is stale
- Check GitHub Actions tab — did the last run succeed?
- Check that `data/*.json` was committed (look at recent commits)
- Manually trigger the workflow: Actions → "Update FRI" → Run workflow

### CORS errors
- The `vercel.json` and `_headers` files set `Access-Control-Allow-Origin: *` on `/data/*`
- If you're on a different host, add this header manually for `/data/*.json`

### Collector fails
- Check that `flopkit` is installed (it's in `requirements.txt` as a git dependency)
- Check that technocore.chat is reachable (it's been up since Aug 2026)
- Run locally: `python -m collector.main --once` and check the logs
