/**
 * useLiveData — live-first, static-fallback data hook.
 *
 * Two deployment modes, decided at boot by probing /api/health:
 *
 *   1. LIVE — a FastAPI backend is reachable at /api/* (docker-compose,
 *      Railway, Fly.io, …):
 *        - Initial snapshots fetched from /api/* REST endpoints (Redis-backed)
 *        - A single multiplexed EventSource to /api/live for live updates
 *        - EventSource auto-reconnects on disconnect
 *
 *   2. STATIC — /api/* is unreachable (e.g. static-only hosting such as
 *      Vercel, where no serverless functions are deployed):
 *        - Loads the /data/*.json snapshots that GitHub Actions commits
 *          every 2h (same JSON shapes the backend serves — the collector
 *          seeds Redis from these exact files)
 *        - Derives counts + health from the snapshots, marks the feed as
 *          stale if the snapshot is older than 4h (one missed cycle)
 *        - Skips the SSE connection (connected = false)
 *        - Re-probes /api/health every 60s (up to 10 times) so a backend
 *          that boots after page load is picked up automatically
 */

import { useEffect, useRef, useState } from "react";
import type {
  DidIndex,
  Feed,
  KibbleIndex,
  ReputationIndex,
  TclkIndex,
} from "@/lib/types";

export type LiveMessage = {
  room: string;
  seq: number;
  ts: string;
  from: string;
  text: string;
};

export type LiveCounts = {
  total_dids: number;
  total_rooms: number;
  total_jobs: number;
  total_contracts: number;
  total_dids_scored: number;
};

export type LiveHealth = {
  status: string;
  stale: boolean;
  technocore_ok: boolean;
  timestamp: string;
};

export type LiveDataState = {
  feed: Feed | null;
  dids: DidIndex | null;
  kibble: KibbleIndex | null;
  tclk: TclkIndex | null;
  reputation: ReputationIndex | null;
  counts: LiveCounts | null;
  health: LiveHealth | null;
  liveMessages: LiveMessage[];
  connected: boolean;
  stale: boolean;
  lastUpdate: number;
  error: string | null;
};

async function fetchJson(url: string, retries = 5): Promise<any> {
  for (let i = 0; i < retries; i++) {
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (e) {
      if (i === retries - 1) throw e;
      await new Promise((r) => setTimeout(r, 1500 * (i + 1)));
    }
  }
}

/** Probe the live backend — true if /api/health answers. */
async function probeApi(): Promise<boolean> {
  try {
    await fetchJson("/api/health", 2);
    return true;
  } catch {
    return false;
  }
}

/** Static snapshots commit every 2h — mark stale after one missed cycle. */
const STATIC_STALE_MS = 4 * 60 * 60 * 1000;

/** How many times to re-probe /api/health in static mode (every 60s). */
const MAX_API_REPROBES = 10;

const MAX_LIVE_MESSAGES = 200;

export function useLiveData(): LiveDataState {
  const [feed, setFeed] = useState<Feed | null>(null);
  const [dids, setDids] = useState<DidIndex | null>(null);
  const [kibble, setKibble] = useState<KibbleIndex | null>(null);
  const [tclk, setTclk] = useState<TclkIndex | null>(null);
  const [reputation, setReputation] = useState<ReputationIndex | null>(null);
  const [counts, setCounts] = useState<LiveCounts | null>(null);
  const [health, setHealth] = useState<LiveHealth | null>(null);
  const [liveMessages, setLiveMessages] = useState<LiveMessage[]>([]);
  const [connected, setConnected] = useState(false);
  const [stale, setStale] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<number>(Date.now());
  const [error, setError] = useState<string | null>(null);

  const esRef = useRef<EventSource | null>(null);
  // Bumped to re-run the boot sequence (static → live upgrade re-probe)
  const [bootAttempt, setBootAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let reprobeTimer: number | undefined;

    // 1. Fetch initial snapshots from REST endpoints, then open SSE
    async function bootLive(): Promise<boolean> {
      const [f, d, k, t, r, c, h] = await Promise.all([
        fetchJson("/api/rooms"),
        fetchJson("/api/dids"),
        fetchJson("/api/kibble"),
        fetchJson("/api/tclk"),
        fetchJson("/api/reputation"),
        fetchJson("/api/counts"),
        fetchJson("/api/health"),
      ]);
      if (cancelled) return true;

      setFeed(f);
      setDids(d);
      setKibble(k);
      setTclk(t);
      setReputation(r);
      setCounts(c);
      setHealth(h);
      setStale(h?.stale ?? false);
      setError(null);

      const es = new EventSource("/api/live");
      esRef.current = es;

      es.onopen = () => {
        if (!cancelled) setConnected(true);
      };

      es.onerror = () => {
        if (!cancelled) setConnected(false);
        // EventSource auto-reconnects — no manual retry needed
      };

      const handleEvent = (type: string, data: string) => {
        if (cancelled) return;
        setLastUpdate(Date.now());
        try {
          const parsed = JSON.parse(data);
          switch (type) {
            case "counts":
              setCounts(parsed);
              break;
            case "feed":
              setLiveMessages((prev) =>
                [...prev, parsed].slice(-MAX_LIVE_MESSAGES),
              );
              break;
            case "rooms":
              setFeed(parsed);
              break;
            case "dids":
              setDids(parsed);
              break;
            case "kibble":
              setKibble(parsed);
              break;
            case "tclk":
              setTclk(parsed);
              break;
            case "reputation":
              setReputation(parsed);
              break;
            case "health":
              setHealth(parsed);
              setStale(parsed.stale ?? false);
              break;
          }
        } catch {
          // ignore parse errors
        }
      };

      const eventTypes = [
        "counts",
        "feed",
        "rooms",
        "dids",
        "kibble",
        "tclk",
        "reputation",
        "health",
      ];
      eventTypes.forEach((type) => {
        es.addEventListener(type, (e: MessageEvent) =>
          handleEvent(type, e.data),
        );
      });

      return true;
    }

    // 2. Static fallback — committed /data/*.json snapshots
    async function bootStatic() {
      const [latest, d, k, t, r, healthJson] = await Promise.all([
        fetchJson("/data/latest.json", 2),
        fetchJson("/data/dids.json", 2),
        fetchJson("/data/kibble.json", 2),
        fetchJson("/data/tclk.json", 2),
        fetchJson("/data/reputation.json", 2),
        fetchJson("/data/health.json", 2).catch(() => null),
      ]);
      if (cancelled) return;

      setFeed(latest);
      setDids(d);
      setKibble(k);
      setTclk(t);
      setReputation(r);
      setCounts({
        total_dids: d?.total_dids ?? d?.dids?.length ?? 0,
        total_rooms:
          latest?.total_rooms_considered ?? latest?.rooms?.length ?? 0,
        total_jobs: k?.total_jobs ?? k?.jobs?.length ?? 0,
        total_contracts: t?.total_contracts ?? t?.contracts?.length ?? 0,
        total_dids_scored: r?.total_dids_scored ?? r?.dids?.length ?? 0,
      });

      const generatedAt = Date.parse(latest?.generated_at ?? "") || 0;
      const snapshotStale =
        generatedAt > 0 ? Date.now() - generatedAt > STATIC_STALE_MS : false;
      const staticHealth: LiveHealth = {
        status: healthJson?.status ?? "ok",
        stale: snapshotStale,
        technocore_ok: healthJson
          ? healthJson?.components?.fetch_rooms?.status === "ok" ||
            healthJson?.status === "ok"
          : true,
        timestamp: healthJson?.timestamp ?? latest?.generated_at ?? "",
      };
      setHealth(staticHealth);
      setStale(snapshotStale);
      setConnected(false);
      setError(null);
    }

    async function boot() {
      // Decide the mode by probing the backend
      if (await probeApi()) {
        if (cancelled) return;
        try {
          await bootLive();
          return; // live mode active — no re-probe needed
        } catch {
          // Probe answered but snapshots failed — fall through to static
        }
      }
      if (cancelled) return;

      try {
        await bootStatic();
      } catch (e) {
        if (!cancelled)
          setError(e instanceof Error ? e.message : String(e));
      }

      // Schedule a re-probe so a backend that boots later is picked up
      if (bootAttempt < MAX_API_REPROBES) {
        reprobeTimer = window.setTimeout(
          () => {
            if (!cancelled) setBootAttempt((a) => a + 1);
          },
          60_000,
        );
      }
    }

    boot();

    return () => {
      cancelled = true;
      if (reprobeTimer) clearTimeout(reprobeTimer);
      esRef.current?.close();
      esRef.current = null;
    };
  }, [bootAttempt]);

  return {
    feed,
    dids,
    kibble,
    tclk,
    reputation,
    counts,
    health,
    liveMessages,
    connected,
    stale,
    lastUpdate,
    error,
  };
}
