import { useEffect, useRef, useState, useCallback } from "react";

export type TcMessage = {
  seq?: number;
  ts?: string;
  from?: string;
  text?: string;
};

export type LiveFeedState = {
  messages: TcMessage[];
  lastSeq: number | null;
  connected: boolean;
  error: string | null;
  messagesPerMin: number;
};

const MAX_MESSAGES = 200;
const POLL_WAIT = 10;

export function useLiveFeed(room: string | null): LiveFeedState {
  const [messages, setMessages] = useState<TcMessage[]>([]);
  const [lastSeq, setLastSeq] = useState<number | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [messagesPerMin, setMessagesPerMin] = useState(0);

  const sinceRef = useRef<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const stoppedRef = useRef(false);
  const recentTimestampsRef = useRef<number[]>([]);

  const poll = useCallback(async () => {
    if (stoppedRef.current || !room) return;

    if (sinceRef.current === null) {
      try {
        setConnected(true);
        setError(null);
        const url = `/tc/r/${encodeURIComponent(room)}?format=json&limit=5`;
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const msgs: TcMessage[] = data.messages ?? [];
        const maxSeq = msgs.reduce((m, x) => Math.max(m, x.seq ?? 0), 0);
        sinceRef.current = maxSeq;
        setLastSeq(maxSeq);
        setMessages(msgs.slice(-MAX_MESSAGES));
      } catch (e: unknown) {
        if (stoppedRef.current) return;
        setError(e instanceof Error ? e.message : String(e));
        setConnected(false);
        setTimeout(() => { if (!stoppedRef.current) poll(); }, 5000);
        return;
      }
    }

    while (!stoppedRef.current) {
      const ac = new AbortController();
      abortRef.current = ac;
      try {
        setConnected(true);
        const since = sinceRef.current ?? 0;
        const url = `/tc/r/${encodeURIComponent(room)}?format=json&since=${since}&wait=${POLL_WAIT}`;
        const res = await fetch(url, { signal: ac.signal });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const msgs: TcMessage[] = data.messages ?? [];
        if (msgs.length > 0) {
          const maxSeq = msgs.reduce((m, x) => Math.max(m, x.seq ?? 0), 0);
          sinceRef.current = Math.max(sinceRef.current ?? 0, maxSeq);
          setLastSeq(sinceRef.current);
          setMessages((prev) => {
            const next = [...prev, ...msgs];
            return next.slice(-MAX_MESSAGES);
          });
          const now = Date.now();
          for (const _m of msgs) {
            recentTimestampsRef.current.push(now);
          }
        }
        const cutoff = Date.now() - 60000;
        recentTimestampsRef.current = recentTimestampsRef.current.filter(
          (t) => t > cutoff,
        );
        setMessagesPerMin(recentTimestampsRef.current.length);
        setError(null);
      } catch (e: unknown) {
        if (stoppedRef.current) return;
        if (e instanceof Error && e.name === "AbortError") return;
        setError(e instanceof Error ? e.message : String(e));
        setConnected(false);
        await new Promise((r) => setTimeout(r, 3000));
      }
    }
  }, [room]);

  useEffect(() => {
    stoppedRef.current = false;
    sinceRef.current = null;
    setMessages([]);
    setLastSeq(null);
    setError(null);
    setMessagesPerMin(0);
    recentTimestampsRef.current = [];

    if (room) {
      poll();
    }

    return () => {
      stoppedRef.current = true;
      if (abortRef.current) abortRef.current.abort();
    };
  }, [room, poll]);

  return { messages, lastSeq, connected, error, messagesPerMin };
}
