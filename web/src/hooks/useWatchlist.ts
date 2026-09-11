/**
 * useWatchlist — client-side watchlist for tracking agents.
 * Persists to localStorage under 'fri-watchlist'.
 * Max 100 agents.
 */

import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "fri-watchlist";
const MAX_WATCHLIST = 100;

function readStorage(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

function writeStorage(dids: string[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(dids));
  } catch {
    /* ignore */
  }
}

export function useWatchlist() {
  const [watchlist, setWatchlist] = useState<string[]>(() => readStorage());

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) setWatchlist(readStorage());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const toggle = useCallback((did: string) => {
    setWatchlist((prev) => {
      if (prev.includes(did)) {
        const next = prev.filter((d) => d !== did);
        writeStorage(next);
        return next;
      }
      const next = [...prev, did].slice(0, MAX_WATCHLIST);
      writeStorage(next);
      return next;
    });
  }, []);

  const remove = useCallback((did: string) => {
    setWatchlist((prev) => {
      const next = prev.filter((d) => d !== did);
      writeStorage(next);
      return next;
    });
  }, []);

  const has = useCallback((did: string) => watchlist.includes(did), [watchlist]);

  return { watchlist, toggle, remove, has, count: watchlist.length };
}
