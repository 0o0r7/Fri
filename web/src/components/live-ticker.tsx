import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { tinyDid } from "@/lib/format";
import type { LiveMessage } from "@/hooks/useLiveData";

type Source = "events" | "tclk" | "kibble" | "other";

type TickerItem = {
  id: string;
  source: Source;
  room: string;
  seq: number;
  ts: string;
  from: string;
  text: string;
  label: string;
  color: string;
};

const SOURCE_CONFIG: Record<
  Source,
  { label: string; color: string; tag: string }
> = {
  events: { label: "ROOM", color: "text-accent", tag: "ROOM" },
  tclk: { label: "TCLK", color: "text-good", tag: "TCLK" },
  kibble: { label: "WORK", color: "text-mid", tag: "WORK" },
  other: { label: "MSG", color: "text-muted", tag: "MSG" },
};

function classifySource(room: string): Source {
  if (room === "events") return "events";
  if (room.includes("tclk")) return "tclk";
  if (room === "kibble") return "kibble";
  return "other";
}

function classifyText(source: Source, text: string): { label: string; color: string } {
  if (source === "events") {
    if (text.startsWith("created ")) {
      const name = text.slice(8).trim();
      return { label: `room: ${name}`, color: "text-accent" };
    }
    return { label: text.slice(0, 60), color: "text-accent" };
  }
  if (source === "tclk") {
    if (text.startsWith("tclk1 ")) {
      try {
        const json = JSON.parse(text.slice(6));
        const t = json.type ?? "?";
        const amount = json.amount ?? "";
        const asset = json.asset ?? "";
        const outcome = json.outcome ?? "";
        if (t === "offer") return { label: `OFFER ${amount} ${asset}`, color: "text-accent-2" };
        if (t === "accept") return { label: "ACCEPT", color: "text-accent" };
        if (t === "lock") return { label: "LOCK", color: "text-mid" };
        if (t === "reveal") return { label: "REVEAL", color: "text-good" };
        if (t === "refund") return { label: "REFUND", color: "text-low" };
        if (t === "receipt") return { label: `RECEIPT ${outcome}`, color: "text-good" };
        return { label: t.toUpperCase(), color: "text-muted" };
      } catch {
        return { label: "tclk frame", color: "text-muted" };
      }
    }
    return { label: text.slice(0, 60), color: "text-muted" };
  }
  if (source === "kibble") {
    if (text.startsWith("JOB v1")) return { label: "JOB posted", color: "text-accent" };
    if (text.startsWith("CLAIM v1")) return { label: "CLAIM", color: "text-mid" };
    if (text.startsWith("DELIVER v1")) return { label: "DELIVER", color: "text-accent-2" };
    if (text.startsWith("RESULT v1")) return { label: "RESULT", color: "text-accent-2" };
    if (text.startsWith("ATTEST v1")) {
      const useful = text.includes("| useful |");
      return {
        label: useful ? "ATTEST useful" : "ATTEST not",
        color: useful ? "text-good" : "text-low",
      };
    }
    if (text.startsWith("ACCEPT v1")) return { label: "ACCEPT", color: "text-good" };
    return { label: text.slice(0, 40), color: "text-muted" };
  }
  return { label: text.slice(0, 40), color: "text-muted" };
}

function toTickerItem(msg: LiveMessage): TickerItem | null {
  if (!msg.seq || !msg.text) return null;
  const source = classifySource(msg.room);
  const { label, color } = classifyText(source, msg.text);
  return {
    id: `${msg.room}-${msg.seq}`,
    source,
    room: msg.room,
    seq: msg.seq,
    ts: msg.ts,
    from: msg.from,
    text: msg.text,
    label,
    color,
  };
}

const MAX_ITEMS = 50;

export function LiveTicker({
  messages,
  connected,
}: {
  messages: LiveMessage[];
  connected: boolean;
}) {
  const [items, setItems] = useState<TickerItem[]>([]);
  const seenIds = useRef<Set<string>>(new Set());

  useEffect(() => {
    const allNew: TickerItem[] = [];
    for (const m of messages) {
      const item = toTickerItem(m);
      if (item && !seenIds.current.has(item.id)) {
        seenIds.current.add(item.id);
        allNew.push(item);
      }
    }
    if (allNew.length > 0) {
      allNew.sort((a, b) => {
        if (a.ts && b.ts) return a.ts.localeCompare(b.ts);
        return a.seq - b.seq;
      });
      setItems((prev) => [...allNew.reverse(), ...prev].slice(0, MAX_ITEMS));
    }
  }, [messages]);

  useEffect(() => {
    if (seenIds.current.size > 500) {
      const keep = new Set(items.map((i) => i.id));
      seenIds.current = keep;
    }
  }, [items]);

  // Counters from recent items
  const counters = useMemo(() => {
    const now = Date.now();
    const recent = items.filter((i) => {
      try {
        return now - new Date(i.ts).getTime() < 60000;
      } catch {
        return false;
      }
    });
    return {
      rooms: recent.filter((i) => i.source === "events").length,
      deals: recent.filter((i) => i.source === "tclk").length,
      jobs: recent.filter((i) => i.source === "kibble").length,
    };
  }, [items]);

  return (
    <div className="relative z-20 border-b border-border bg-surface/85 backdrop-blur">
      <div className="mx-auto flex max-w-screen-2xl items-stretch gap-3 px-4 py-1.5 sm:px-6">
        {/* Live indicator */}
        <div className="flex shrink-0 items-center gap-2 border-r border-border pr-3">
          <span
            className={cn(
              "relative flex size-2",
              connected ? "text-good" : "text-low",
            )}
            title={connected ? "Live" : "Disconnected"}
          >
            <span
              className={cn(
                "absolute inline-flex size-full animate-ping rounded-full opacity-75",
                connected ? "bg-good" : "bg-low",
              )}
            />
            <span
              className={cn(
                "relative inline-flex size-2 rounded-full",
                connected ? "bg-good" : "bg-low",
              )}
            />
          </span>
          <span
            className={cn(
              "font-mono text-[10px] tracking-[0.18em] uppercase",
              connected ? "text-good" : "text-low",
            )}
          >
            {connected ? "LIVE" : "OFFLINE"}
          </span>
        </div>

        {/* Per-source counters */}
        <div className="flex shrink-0 items-center gap-3 border-r border-border pr-3">
          <Counter label="rooms/min" value={counters.rooms} color="text-accent" />
          <Counter label="deals/min" value={counters.deals} color="text-good" />
          <Counter label="jobs/min" value={counters.jobs} color="text-mid" />
        </div>

        {/* Scrolling feed */}
        <div className="relative min-w-0 flex-1 overflow-hidden">
          {items.length === 0 ? (
            <div className="flex h-full items-center font-mono text-[11px] text-faint">
              {connected
                ? "Listening for activity…"
                : "Connecting to live feed…"}
            </div>
          ) : (
            <div className="flex h-full items-center gap-2 overflow-x-auto pb-0.5">
              {items.slice(0, 12).map((item) => {
                const cfg = SOURCE_CONFIG[item.source];
                return (
                  <div
                    key={item.id}
                    className="flex shrink-0 items-center gap-1.5 rounded border border-border bg-bg/60 px-2 py-0.5"
                    title={`${item.ts}\n${item.from}\n${item.text.slice(0, 200)}`}
                  >
                    <span
                      className={cn(
                        "inline-flex items-center rounded px-1 font-mono text-[9px] font-bold tracking-wider uppercase",
                        cfg.color,
                      )}
                    >
                      {cfg.tag}
                    </span>
                    <span className={cn("font-mono text-[11px]", item.color)}>
                      {item.label}
                    </span>
                    {item.from && item.from.startsWith("did:key:") ? (
                      <span className="font-mono text-[10px] text-faint">
                        {tinyDid(item.from)}
                      </span>
                    ) : null}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Counter({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color: string;
}) {
  return (
    <div className="flex items-baseline gap-1">
      <span className={cn("font-mono text-sm font-bold tabular-nums", color)}>
        {value}
      </span>
      <span className="font-mono text-[10px] tracking-wider text-faint uppercase">
        {label}
      </span>
    </div>
  );
}
