import { ArrowUpRight, Copy, Check } from "lucide-react";
import { useState } from "react";
import {
  absoluteTime,
  didNoteUrl,
  liveRoomUrl,
  relativeTime,
  shortDid,
  shardedFingerprint,
} from "@/lib/format";
import { didToHash } from "@/lib/did-profile";
import type { DidStats } from "@/lib/types";

export function DidDetail({ did }: { did: DidStats }) {
  const [copied, setCopied] = useState<"did" | "fp" | null>(null);
  const { shard, key } = shardedFingerprint(did.fingerprint);

  async function copy(text: string, which: "did" | "fp") {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(which);
      window.setTimeout(() => setCopied(null), 1400);
    } catch {
      /* ignore */
    }
  }

  const roomEntries = Object.entries(did.rooms_breakdown);
  const maxRoomCount = roomEntries.length > 0 ? roomEntries[0][1] : 1;

  return (
    <article className="flex flex-col gap-6">
      <header className="flex flex-col gap-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="font-mono text-xs tabular-nums text-faint">
              Fingerprint {shard} / {key}
            </p>
            <h2 className="mt-1 break-all text-base font-mono font-medium tracking-tight text-balance">
              {shortDid(did.did)}
            </h2>
          </div>
          <span className="inline-flex shrink-0 min-w-16 items-center justify-end rounded-full bg-good-dim px-2.5 py-1 font-mono text-sm text-good tabular-nums">
            {did.messages_signed}
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          <a
            href={didNoteUrl(did.fingerprint)}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-9 items-center gap-1.5 rounded-md bg-accent px-3 text-sm font-medium text-white transition-colors hover:bg-accent/90"
          >
            DID note
            <ArrowUpRight className="size-3.5" />
          </a>
          <button
            type="button"
            onClick={() => copy(did.did, "did")}
            className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border bg-elevated px-3 text-sm text-fg transition-colors hover:bg-elevated/70"
          >
            {copied === "did" ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
            Copy DID
          </button>
          <button
            type="button"
            onClick={() => copy(did.fingerprint, "fp")}
            className="inline-flex h-9 items-center gap-1.5 rounded-md px-3 text-sm text-muted transition-colors hover:bg-elevated hover:text-fg"
          >
            {copied === "fp" ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
            Fingerprint
          </button>
          <a
            href={didToHash(did.did)}
            className="inline-flex h-9 items-center gap-1.5 rounded-md bg-accent px-3 text-sm font-medium text-white transition-colors hover:bg-accent/90"
          >
            Full profile
            <ArrowUpRight className="size-3.5" />
          </a>
        </div>
        <p className="text-xs text-faint">
          DID note is world-writable — anyone can overwrite the value at <code className="font-mono text-muted">/kv/did-{shard}/{key}</code>. Trust the signed messages, not the note.
        </p>
      </header>

      <section>
        <h3 className="mb-3 font-mono text-xs tracking-wider text-faint uppercase">
          Activity
        </h3>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Metric
            label="Messages"
            value={String(did.messages_signed)}
            hint="Signed messages observed in the sample window."
          />
          <Metric
            label="Rooms"
            value={String(did.rooms_active_in)}
            hint="Distinct rooms this DID has signed into."
          />
          <Metric
            label="Avg len"
            value={String(Math.round(did.avg_message_length))}
            hint="Average signed message length in characters."
          />
          <Metric
            label="Last seen"
            value={did.last_active ? relativeTime(did.last_active) : "—"}
            hint={did.last_active ? absoluteTime(did.last_active) : "No timestamp"}
          />
        </div>
        {(did.first_seen || did.last_active) && (
          <p className="mt-3 text-xs text-faint">
            First seen {did.first_seen ? absoluteTime(did.first_seen) : "—"}
            {did.last_active ? ` · last active ${absoluteTime(did.last_active)}` : ""}
          </p>
        )}
      </section>

      <section>
        <h3 className="mb-3 font-mono text-xs tracking-wider text-faint uppercase">
          Rooms breakdown
        </h3>
        {roomEntries.length === 0 ? (
          <p className="text-sm text-muted">No rooms recorded.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {roomEntries.map(([room, count]) => (
              <li key={room} className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1">
                <a
                  href={liveRoomUrl(room)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="truncate text-sm text-fg hover:text-accent"
                >
                  {room}
                </a>
                <span className="font-mono text-xs tabular-nums text-fg">
                  {count}
                  <span className="text-faint"> / {did.messages_signed}</span>
                </span>
                <div className="col-span-2 h-1 w-full overflow-hidden rounded-full bg-elevated">
                  <div
                    className="h-full rounded-full bg-accent transition-[width] duration-500"
                    style={{ width: `${(count / maxRoomCount) * 100}%` }}
                  />
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </article>
  );
}

export function DidEmptyDetail() {
  return (
    <div className="flex h-full min-h-64 flex-col items-center justify-center gap-2 px-6 text-center">
      <p className="text-sm font-medium text-fg">Select a DID</p>
      <p className="max-w-xs text-sm text-pretty text-muted">
        Every signed <code className="font-mono text-muted">did:key</code> we've
        observed across sampled rooms. Open one to inspect its activity, room
        breakdown, and DID note link.
      </p>
    </div>
  );
}

function Metric({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div
      className="rounded-lg bg-elevated px-3 py-2.5 shadow-[var(--shadow-border)]"
      title={hint}
    >
      <p className="text-xs text-faint">{label}</p>
      <p className="mt-0.5 font-mono text-sm tabular-nums text-fg">{value}</p>
    </div>
  );
}
