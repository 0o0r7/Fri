/**
 * useLiveData — SSE-based real-time data hook.
 *
 * Replaces the old static fetch() + useLiveFeed polling with a single
 * EventSource connection to the backend's /api/live SSE endpoint.
 *
 * On mount:
 *   1. Fetches initial snapshots from /api/* REST endpoints (instant, from Redis)
 *   2. Opens an EventSource to /api/live for live updates
 *   3. Updates state on each SSE event (counts, feed, rooms, dids, etc.)
 *   4. EventSource auto-reconnects on disconnect
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

  useEffect(() => {
    let cancelled = false;

    // 1. Fetch initial snapshots from REST endpoints
    Promise.all([
      fetchJson("/api/rooms"),
      fetchJson("/api/dids"),
      fetchJson("/api/kibble"),
      fetchJson("/api/tclk"),
      fetchJson("/api/reputation"),
      fetchJson("/api/counts"),
      fetchJson("/api/health"),
    ])
      .then(([f, d, k, t, r, c, h]) => {
        if (cancelled) return;
        setFeed(f);
        setDids(d);
        setKibble(k);
        setTclk(t);
        setReputation(r);
        setCounts(c);
        setHealth(h);
        setStale(h?.stale ?? false);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });

    // 2. Open SSE connection
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
            setLiveMessages((prev) => [...prev, parsed].slice(-MAX_LIVE_MESSAGES));
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
      es.addEventListener(type, (e: MessageEvent) => handleEvent(type, e.data));
    });

    return () => {
      cancelled = true;
      es.close();
      esRef.current = null;
    };
  }, []);

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
