import { Copy, Check, ArrowUpRight } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import { tinyDid } from "@/lib/format";
import { reputationBand } from "@/lib/reputation-filter";
import { didToHash } from "@/lib/did-profile";
import type { ReputationEntry } from "@/lib/types";

const BAND_COLORS = {
  high: "bg-good-dim text-good",
  medium: "bg-mid-dim text-mid",
  low: "bg-low-dim text-low",
};

export function ReputationDetail({ entry }: { entry: ReputationEntry }) {
  const [copied, setCopied] = useState(false);
  const band = reputationBand(entry.reputation_score);

  async function copyDid() {
    try {
      await navigator.clipboard.writeText(entry.did);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      /* ignore */
    }
  }

  return (
    <article className="flex flex-col gap-6">
      <header className="flex flex-col gap-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="font-mono text-xs tabular-nums text-faint">
              {entry.schema_version}
            </p>
            <h2 className="mt-1 break-all text-sm font-mono font-medium tracking-tight text-balance">
              {tinyDid(entry.did)}
            </h2>
          </div>
          <span
            className={cn(
              "inline-flex shrink-0 min-w-20 items-center justify-center rounded-full px-3 py-1.5 font-mono text-lg font-bold tabular-nums",
              BAND_COLORS[band],
            )}
          >
            {entry.reputation_score.toFixed(3)}
          </span>
        </div>
        <button
          type="button"
          onClick={copyDid}
          className="inline-flex h-9 w-fit items-center gap-1.5 rounded-md border border-border bg-elevated px-3 text-sm text-fg transition-colors hover:bg-elevated/70"
        >
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
          Copy DID
        </button>
        <a
          href={didToHash(entry.did)}
          className="inline-flex h-9 w-fit items-center gap-1.5 rounded-md bg-accent px-3 text-sm font-medium text-white transition-colors hover:bg-accent/90"
        >
          View full profile
          <ArrowUpRight className="size-3.5" />
        </a>
      </header>

      <section>
        <h3 className="mb-3 font-mono text-xs tracking-wider text-faint uppercase">
          Score breakdown
        </h3>
        <div className="flex flex-col gap-4">
          <ScoreBar
            label="Activity (30%)"
            score={entry.activity_score}
            detail={`messages: ${entry.components.activity.messages_signed} · rooms: ${entry.components.activity.rooms_active_in} · avg len: ${Math.round(entry.components.activity.avg_message_length)}`}
            tone="accent"
          />
          <ScoreBar
            label="Work (40%)"
            score={entry.work_score}
            detail={`deliveries: ${entry.components.work.deliveries_made} · useful: ${entry.components.work.useful_received_on_delivered} · not: ${entry.components.work.not_received_on_delivered} · posted: ${entry.components.work.jobs_posted}`}
            tone="good"
          />
          <ScoreBar
            label="Reliability (30%)"
            score={entry.reliability_score}
            detail={
              entry.components.reliability.has_tclk_activity
                ? `payee deals: ${entry.components.reliability.deals_as_payee} · completed: ${entry.components.reliability.deals_completed_as_payee} · completion rate: ${entry.components.reliability.completion_rate_as_payee != null ? (entry.components.reliability.completion_rate_as_payee * 100).toFixed(0) + "%" : "—"}`
                : "no TCLK activity (neutral 0.5)"
            }
            tone="accent"
          />
        </div>
      </section>

      <section>
        <h3 className="mb-3 font-mono text-xs tracking-wider text-faint uppercase">
          Activity components
        </h3>
        <div className="grid grid-cols-3 gap-2">
          <Component label="Messages" value={entry.components.activity.messages_component} raw={String(entry.components.activity.messages_signed)} />
          <Component label="Rooms" value={entry.components.activity.rooms_component} raw={String(entry.components.activity.rooms_active_in)} />
          <Component label="Length" value={entry.components.activity.length_component} raw={String(Math.round(entry.components.activity.avg_message_length))} />
        </div>
      </section>

      <section>
        <h3 className="mb-3 font-mono text-xs tracking-wider text-faint uppercase">
          Work components
        </h3>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Component label="Deliveries" value={entry.components.work.deliveries_component} raw={String(entry.components.work.deliveries_made)} />
          <Component label="Useful" value={entry.components.work.useful_component} raw={String(entry.components.work.useful_received_on_delivered)} />
          <Component label="Posted" value={entry.components.work.posted_component} raw={String(entry.components.work.jobs_posted)} />
          <Component label="Not penalty" value={-entry.components.work.not_penalty} raw={String(entry.components.work.not_received_on_delivered)} negative />
        </div>
      </section>

      {entry.components.reliability.has_tclk_activity ? (
        <section>
          <h3 className="mb-3 font-mono text-xs tracking-wider text-faint uppercase">
            Reliability components
          </h3>
          <div className="grid grid-cols-3 gap-2">
            <Component
              label="Completion rate"
              value={entry.components.reliability.completion_rate_component}
              raw={
                entry.components.reliability.completion_rate_as_payee != null
                  ? (entry.components.reliability.completion_rate_as_payee * 100).toFixed(0) + "%"
                  : "—"
              }
            />
            <Component label="Volume" value={entry.components.reliability.completed_volume_component} raw={String(entry.components.reliability.deals_completed_as_payee)} />
            <Component label="Payer" value={entry.components.reliability.payer_participation_component} raw={String(entry.components.reliability.deals_as_payer)} />
          </div>
        </section>
      ) : null}
    </article>
  );
}

export function ReputationEmptyDetail() {
  return (
    <div className="flex h-full min-h-64 flex-col items-center justify-center gap-2 px-6 text-center">
      <p className="text-sm font-medium text-fg">Select a DID</p>
      <p className="max-w-xs text-sm text-pretty text-muted">
        Every scored DID ranked by reputation. Open one to inspect its full
        score breakdown — activity, work, and reliability components.
      </p>
    </div>
  );
}

function ScoreBar({
  label,
  score,
  detail,
  tone,
}: {
  label: string;
  score: number;
  detail: string;
  tone: "accent" | "good";
}) {
  const pct = Math.max(0, Math.min(100, score * 100));
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <span className="text-xs text-muted">{label}</span>
        <span className="font-mono text-sm tabular-nums text-fg">
          {score.toFixed(3)}
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-elevated">
        <div
          className={cn(
            "h-full rounded-full transition-[width] duration-500",
            tone === "accent" ? "bg-accent" : "bg-good",
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="mt-1 text-xs text-faint">{detail}</p>
    </div>
  );
}

function Component({
  label,
  value,
  raw,
  negative,
}: {
  label: string;
  value: number;
  raw: string;
  negative?: boolean;
}) {
  return (
    <div className="rounded-lg bg-elevated px-3 py-2.5 shadow-[var(--shadow-border)]">
      <p className="text-xs text-faint">{label}</p>
      <p className={cn("mt-0.5 font-mono text-sm tabular-nums", negative ? "text-low" : "text-fg")}>
        {value.toFixed(3)}
      </p>
      <p className="mt-0.5 font-mono text-xs text-faint">({raw})</p>
    </div>
  );
}
