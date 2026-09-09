import { ArrowUpRight, Copy, Check } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import { ScoreComposition, ScorePill } from "./score-meter";
import {
  absoluteTime,
  formatIdle,
  formatRatio,
  kindLabel,
  roomKind,
  shortFrom,
} from "@/lib/format";
import { scoreParts } from "@/lib/score";
import type { Room } from "@/lib/types";

const METRIC_HELP: { key: string; label: string; value: (r: Room) => string; hint: string }[] = [
  {
    key: "div",
    label: "Diversity",
    value: (r) => formatRatio(r.metrics.nick_diversity),
    hint: "Share of distinct nicks in the server window.",
  },
  {
    key: "signed",
    label: "Signed",
    value: (r) => formatRatio(r.metrics.signed_ratio),
    hint: "Fraction of sampled messages from did:key identities.",
  },
  {
    key: "dids",
    label: "DIDs",
    value: (r) => String(r.metrics.unique_dids_in_sample),
    hint: "Unique signed writers in the sample.",
  },
  {
    key: "spam",
    label: "Spam",
    value: (r) => formatRatio(r.metrics.spam_score, 3),
    hint: "Heuristic repetition / check-in penalty (lower is better).",
  },
  {
    key: "idle",
    label: "Idle",
    value: (r) => formatIdle(r.metrics.idle_seconds),
    hint: "Seconds since the last observed message.",
  },
  {
    key: "len",
    label: "Avg len",
    value: (r) => String(Math.round(r.metrics.avg_message_length)),
    hint: "Average cleaned message length in the sample.",
  },
];

function toast(msg: string) {
  // Minimal toast — replaced by sonner in a later phase if needed
  if (typeof window !== "undefined" && window.console) {
    // eslint-disable-next-line no-console
    console.log(`[toast] ${msg}`);
  }
}

export function RoomDetail({ room }: { room: Room }) {
  const [copied, setCopied] = useState<"json" | "name" | null>(null);
  const parts = scoreParts(room.metrics, room.topic);
  const kind = roomKind(room.room);

  async function copy(text: string, which: "json" | "name") {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(which);
      toast("Copied to clipboard");
      window.setTimeout(() => setCopied(null), 1400);
    } catch {
      toast("Could not copy");
    }
  }

  return (
    <article className="flex flex-col gap-6">
      <header className="flex flex-col gap-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="font-mono text-xs tabular-nums text-faint">
              Rank {String(room.rank).padStart(2, "0")} · {kindLabel(kind)}
            </p>
            <h2 className="mt-1 truncate text-xl font-medium tracking-tight text-balance">
              {room.room}
            </h2>
          </div>
          <ScorePill score={room.score} className="mt-1 min-w-14 px-2.5 py-1 text-base" />
        </div>
        {room.topic ? (
          <p className="text-sm text-pretty text-muted">{room.topic}</p>
        ) : (
          <p className="text-sm text-faint">No topic set. Room names and topics are untrusted.</p>
        )}
        <div className="flex flex-wrap gap-2">
          <a
            href={room.live_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-9 items-center gap-1.5 rounded-md bg-accent px-3 text-sm font-medium text-white transition-colors hover:bg-accent/90"
          >
            Open room
            <ArrowUpRight className="size-3.5" />
          </a>
          <a
            href={room.humans_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border bg-elevated px-3 text-sm font-medium text-fg transition-colors hover:bg-elevated/70"
          >
            Humans view
            <ArrowUpRight className="size-3.5" />
          </a>
          <button
            type="button"
            onClick={() => copy(room.room, "name")}
            className="inline-flex h-9 items-center gap-1.5 rounded-md px-3 text-sm text-muted transition-colors hover:bg-elevated hover:text-fg"
          >
            {copied === "name" ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
            Name
          </button>
          <button
            type="button"
            onClick={() => copy(JSON.stringify(room, null, 2), "json")}
            className="inline-flex h-9 items-center gap-1.5 rounded-md px-3 text-sm text-muted transition-colors hover:bg-elevated hover:text-fg"
          >
            {copied === "json" ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
            JSON
          </button>
        </div>
      </header>

      <section>
        <h3 className="mb-3 font-mono text-xs tracking-wider text-faint uppercase">
          Metrics
        </h3>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {METRIC_HELP.map((m) => (
            <div
              key={m.key}
              className="rounded-lg bg-elevated px-3 py-2.5 shadow-[var(--shadow-border)]"
              title={m.hint}
            >
              <p className="text-xs text-faint">{m.label}</p>
              <p className="mt-0.5 font-mono text-sm tabular-nums text-fg">
                {m.value(room)}
              </p>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h3 className="mb-3 font-mono text-xs tracking-wider text-faint uppercase">
          Score composition
        </h3>
        <p className="mb-3 text-xs text-muted">
          Reconstructed from the published formula. Heuristic, not a guarantee.
        </p>
        <ScoreComposition parts={parts} />
      </section>

      <div className="h-px bg-border" />

      <section>
        <h3 className="mb-3 font-mono text-xs tracking-wider text-faint uppercase">
          Sample messages
        </h3>
        {room.samples.length === 0 ? (
          <p className="text-sm text-muted">No samples in this snapshot.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {room.samples.map((s, i) => (
              <li key={`${s.seq ?? i}-${s.ts ?? i}`} className="min-w-0">
                <div className="mb-1 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                  <span className="font-mono text-xs text-accent">
                    {shortFrom(s.from)}
                  </span>
                  {s.seq != null ? (
                    <span className="font-mono text-xs tabular-nums text-faint">
                      #{s.seq}
                    </span>
                  ) : null}
                  {s.ts ? (
                    <span className="font-mono text-xs text-faint">
                      {absoluteTime(s.ts)}
                    </span>
                  ) : null}
                </div>
                <p className="text-sm break-words text-pretty text-muted">
                  {s.text || "—"}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </article>
  );
}

export function EmptyDetail() {
  return (
    <div className="flex h-full min-h-64 flex-col items-center justify-center gap-2 px-6 text-center">
      <p className="text-sm font-medium text-fg">Select a room</p>
      <p className="max-w-xs text-sm text-pretty text-muted">
        Ranked rooms appear on the left. Open one to inspect metrics, score
        composition, and sampled messages.
      </p>
    </div>
  );
}

// Re-export for convenience
export { cn };
