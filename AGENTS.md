# AGENTS.md — FRI (Flop Reputation Index)

## What this is

A read-only reputation dashboard for the "Flop agent economy." Frontend-only Vite + React 19 + TS + Tailwind v4 app. There is **no runtime backend** — all data is committed JSON served as static files.

## Architecture

- `web/` — Vite dev server (port 5173). The entire user-facing app.
- `web/public/data/*.json` — committed collector output served at `/data/*`. The frontend `fetch()`es these on mount (`latest.json`, `dids.json`, `kibble.json`, `tclk.json`, `reputation.json`).
- `data/` — the canonical collector output at repo root. `scripts/sync_data.sh` copies it into `web/public/data/` so Vite serves it. The repo ships with both already in sync.
- `collector/` — Python scoring engine that fetches from technocore.chat and writes `data/*.json`. **Not needed to run the dashboard**; it's a cron job (`/.github/workflows/update.yml`), not a runtime dependency.
- Live ticker (`web/src/hooks/useLiveFeed.ts`) polls `technocore.chat` via the Vite `/tc` proxy (configured in `vite.config.ts`). This is a public API with **no credentials**. If it fails (network/proxy), the ticker shows an error but the rest of the dashboard works fine.

## Running here (docker-compose.base44.yml)

Single `web` service: `node:22` image, repo bind-mounted at `/app`, runs `npm install && npm run dev` in `web/`. Host port 3000 → container 5173.

No secrets, no env vars beyond `__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS` (platform-provided, for Vite allowed-hosts).

## Verifying it works

- `curl -s -o /dev/null -w '%{http_code}' http://localhost:3000/` → 200
- `curl -s -o /dev/null -w '%{http_code}' http://localhost:3000/data/latest.json` → 200
- `/src/main.tsx` returns 200 (confirms live source, not a prebuilt bundle).
- In the preview, `#root` has children and `nav` renders 5 tabs with counts.

## Editing notes

- Frontend edits hot-reload via Vite HMR — no restart needed.
- Tailwind v4 via `@tailwindcss/vite` plugin; theme tokens defined in `web/src/styles.css` (`@theme` block).
- Path alias `@` → `web/src` (vite.config.ts + tsconfig).
- The Python collector and its `flopkit` git dependency are NOT installed in the compose setup; if a change requires running the collector, do it ad-hoc in a throwaway container.
