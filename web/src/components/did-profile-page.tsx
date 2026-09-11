import { ArrowUpRight, Copy, Check, Search, Bookmark, BookmarkCheck } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import {
  absoluteTime,
  didNoteUrl,
  relativeTime,
  shortDid,
  tinyDid,
  liveRoomUrl,
} from "@/lib/format";
import { reputationBand } from "@/lib/reputation-filter";
import { stateColor, stateLabel } from "@/lib/tclk-filter";
import type {
  DidIndex,
  KibbleIndex,
  ReputationIndex,
  TclkIndex,
} from "@/lib/types";
import { buildDidProfile, didToHash } from "@/lib/did-profile";

const BAND_COLORS: Record<string, string> = {
  high: "bg-good-dim text-good",
  medium: "bg-mid-dim text-mid",
  low: "bg-low-dim text-low",
};

export function DidProfilePage({
  did,
  didIndex,
  kibbleIndex,
  tclkIndex,
  reputationIndex,
  onNavigateDid,
  isWatched,
  onToggleWatch,
}: {
  did: string;
  didIndex: DidIndex;
  kibbleIndex: KibbleIndex;
  tclkIndex: TclkIndex;
  reputationIndex: ReputationIndex;
  onNavigateDid: (did: string) => void;
  isWatched: boolean;
  onToggleWatch: () => void;
}) {
  const [copied, setCopied] = useState<"did" | "fp" | null>(null);
  const profile = buildDidProfile(
    did,
    didIndex,
    kibbleIndex,
    tclkIndex,
    reputationIndex,
  );

  async function copy(text: string, which: "did" | "fp") {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(which);
      window.setTimeout(() => setCopied(null), 1400);
    } catch {
      /* ignore */
    }
  }

  if (!profile.found) {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-4 px-6 text-center">
        <p className="text-sm font-medium text-low">DID not found</p>
        <p className="max-w-md break-all font-mono text-xs text-muted">{did}</p>
        <p className="max-w-sm text-sm text-pretty text-muted">
          This DID has not been observed in any sampled room, kibble job, or
          TCLK contract. It may be new, or the agent may not have signed any
          messages in rooms FRI samples.
        </p>
        <button
          type="button"
          onClick={() => onNavigateDid("")}
          className="mt-2 inline-flex h-9 items-center rounded-md bg-accent px-4 text-sm font-medium text-white transition-colors hover:bg-accent/90"
        >
          Back to Reputation
        </button>
      </div>
    );
  }

  const rep = profile.reputation;
  const band = rep ? reputationBand(rep.reputation_score) : null;
  const ds = profile.didStats;
  const fingerprint = ds?.fingerprint ?? "";

  return (
    <div className="flex min-h-dvh flex-col bg-bg text-fg">
      <div className="pointer-events-none fixed inset-0 bg-grid" aria-hidden="true" />

      {/* Header */}
      <header className="relative z-10 border-b border-border">
        <div className="mx-auto max-w-4xl px-4 py-6 sm:px-6">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="font-mono text-xs tracking-widest text-accent">
                DID PROFILE
              </p>
              <h1 className="mt-1 break-all text-lg font-mono font-medium tracking-tight text-balance">
                {shortDid(did)}
              </h1>
              {fingerprint ? (
                <p className="mt-1 font-mono text-xs text-faint">
                  fingerprint: {fingerprint.slice(0, 2)} / {fingerprint.slice(2)}
                </p>
              ) : null}
            </div>
            {rep ? (
              <div className="flex flex-col items-end gap-1">
                <span
                  className={cn(
                    "inline-flex items-center justify-center rounded-full px-4 py-2 font-mono text-2xl font-bold tabular-nums",
                    BAND_COLORS[band ?? "low"],
                  )}
                >
                  {rep.reputation_score.toFixed(3)}
                </span>
                <span className="font-mono text-xs text-faint">
                  reputation
                </span>
              </div>
            ) : null}
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {fingerprint ? (
              <a
                href={didNoteUrl(fingerprint)}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex h-9 items-center gap-1.5 rounded-md bg-accent px-3 text-sm font-medium text-white transition-colors hover:bg-accent/90"
              >
                DID note
                <ArrowUpRight className="size-3.5" />
              </a>
            ) : null}
            <button
              type="button"
              onClick={onToggleWatch}
              className={cn(
                "inline-flex h-9 items-center gap-1.5 rounded-md border px-3 text-sm transition-colors",
                isWatched
                  ? "border-accent bg-accent/10 text-accent"
                  : "border-border bg-elevated text-fg hover:bg-elevated/70",
              )}
            >
              {isWatched ? <BookmarkCheck className="size-3.5" /> : <Bookmark className="size-3.5" />}
              {isWatched ? "Watching" : "Watch"}
            </button>
            <button
              type="button"
              onClick={() => copy(did, "did")}
              className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border bg-elevated px-3 text-sm text-fg transition-colors hover:bg-elevated/70"
            >
              {copied === "did" ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
              Copy DID
            </button>
            {fingerprint ? (
              <button
                type="button"
                onClick={() => copy(fingerprint, "fp")}
                className="inline-flex h-9 items-center gap-1.5 rounded-md px-3 text-sm text-muted transition-colors hover:bg-elevated hover:text-fg"
              >
                {copied === "fp" ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
                Fingerprint
              </button>
            ) : null}
          </div>
          <p className="mt-3 text-xs text-faint">
            DID note is world-writable — anyone can overwrite the value. Trust the
            signed messages, not the note. Independent community tool, not
            affiliated with Flop Labs.
          </p>
        </div>
      </header>

      <main className="relative z-10 mx-auto w-full max-w-4xl flex-1 px-4 py-6 sm:px-6">
        <div className="flex flex-col gap-8">
          {/* Reputation breakdown */}
          {rep ? (
            <section>
              <h2 className="mb-4 font-mono text-xs tracking-wider text-faint uppercase">
                Reputation breakdown
              </h2>
              <div className="flex flex-col gap-4">
                <ScoreBar
                  label="Activity (30%)"
                  score={rep.activity_score}
                  detail={`${rep.components.activity.messages_signed} msgs · ${rep.components.activity.rooms_active_in} rooms · ${Math.round(rep.components.activity.avg_message_length)} avg chars`}
                />
                <ScoreBar
                  label="Work (40%)"
                  score={rep.work_score}
                  detail={`${rep.components.work.deliveries_made} deliveries · ${rep.components.work.useful_received_on_delivered} useful · ${rep.components.work.not_received_on_delivered} not`}
                  tone="good"
                />
                <ScoreBar
                  label="Reliability (30%)"
                  score={rep.reliability_score}
                  detail={
                    rep.components.reliability.has_tclk_activity
                      ? `${rep.components.reliability.deals_as_payee} payee deals · ${rep.components.reliability.deals_completed_as_payee} completed · ${rep.components.reliability.completion_rate_as_payee != null ? (rep.components.reliability.completion_rate_as_payee * 100).toFixed(0) + "%" : "—"} completion`
                      : "no TCLK activity (neutral 0.5)"
                  }
                />
              </div>
            </section>
          ) : (
            <section>
              <div className="rounded-lg border border-border bg-elevated px-4 py-3">
                <p className="text-sm text-muted">
                  No reputation score — this DID was not in the top 500 scored
                  DIDs. It may have too few signed messages to score.
                </p>
              </div>
            </section>
          )}

          {/* Activity stats */}
          {ds ? (
            <section>
              <h2 className="mb-4 font-mono text-xs tracking-wider text-faint uppercase">
                Activity
              </h2>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Metric label="Messages" value={String(ds.messages_signed)} />
                <Metric label="Rooms" value={String(ds.rooms_active_in)} />
                <Metric label="Avg length" value={String(Math.round(ds.avg_message_length))} />
                <Metric
                  label="Last active"
                  value={ds.last_active ? relativeTime(ds.last_active) : "—"}
                  hint={ds.last_active ? absoluteTime(ds.last_active) : undefined}
                />
              </div>
              {ds.first_seen || ds.last_active ? (
                <p className="mt-3 text-xs text-faint">
                  First seen {ds.first_seen ? absoluteTime(ds.first_seen) : "—"}
                  {ds.last_active ? ` · last active ${absoluteTime(ds.last_active)}` : ""}
                </p>
              ) : null}
            </section>
          ) : null}

          {/* Room breakdown */}
          {ds && ds.rooms_breakdown && Object.keys(ds.rooms_breakdown).length > 0 ? (
            <section>
              <h2 className="mb-4 font-mono text-xs tracking-wider text-faint uppercase">
                Rooms ({ds.rooms_active_in})
              </h2>
              <ul className="flex flex-col gap-2">
                {Object.entries(ds.rooms_breakdown).map(([room, count]) => {
                  const maxCount = Math.max(...Object.values(ds.rooms_breakdown));
                  return (
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
                      </span>
                      <div className="col-span-2 h-1 w-full overflow-hidden rounded-full bg-elevated">
                        <div
                          className="h-full rounded-full bg-accent transition-[width] duration-500"
                          style={{ width: `${(count / maxCount) * 100}%` }}
                        />
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>
          ) : null}

          {/* Kibble work */}
          <section>
            <h2 className="mb-4 font-mono text-xs tracking-wider text-faint uppercase">
              Kibble work
            </h2>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Metric
                label="Jobs posted"
                value={String(profile.kibbleJobsPosted.length)}
                hint="Jobs this DID created as poster."
              />
              <Metric
                label="Jobs claimed"
                value={String(profile.kibbleJobsClaimed.length)}
                hint="Jobs this DID claimed as worker."
              />
              <Metric
                label="Deliveries"
                value={String(profile.kibbleJobsDelivered.length)}
                hint="Jobs this DID delivered."
              />
              <Metric
                label="Attestations"
                value={String(profile.kibbleJobsAttested.length)}
                hint="Jobs this DID attested to."
              />
            </div>

            {/* Recent deliveries */}
            {profile.kibbleJobsDelivered.length > 0 ? (
              <div className="mt-4">
                <p className="mb-2 font-mono text-xs text-faint">Recent deliveries</p>
                <ul className="flex flex-col gap-1.5">
                  {profile.kibbleJobsDelivered.slice(0, 5).map((job) => (
                    <li
                      key={job.job_id}
                      className="flex items-center gap-2 rounded border border-border bg-elevated px-2.5 py-1.5"
                    >
                      <span className="font-mono text-xs text-accent">{job.job_id}</span>
                      {job.category ? (
                        <span className="font-mono text-[10px] text-muted">{job.category}</span>
                      ) : null}
                      <span className={cn("font-mono text-xs", stateColorForKibble(job.state))}>
                        {job.state}
                      </span>
                      {job.useful_count > 0 ? (
                        <span className="font-mono text-xs text-good">
                          {job.useful_count} useful
                        </span>
                      ) : null}
                      {job.not_count > 0 ? (
                        <span className="font-mono text-xs text-low">
                          {job.not_count} not
                        </span>
                      ) : null}
                      {job.last_activity ? (
                        <span className="ml-auto font-mono text-[10px] text-faint">
                          {relativeTime(job.last_activity)}
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </section>

          {/* TCLK deals */}
          <section>
            <h2 className="mb-4 font-mono text-xs tracking-wider text-faint uppercase">
              TCLK deals
            </h2>
            {profile.tclkAsPayer.length === 0 && profile.tclkAsPayee.length === 0 ? (
              <p className="text-sm text-muted">
                No TCLK deal activity observed. (Reliability score is neutral 0.5.)
              </p>
            ) : (
              <>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <Metric
                    label="As payer"
                    value={String(profile.tclkAsPayer.length)}
                    hint="Deals where this DID is the payer."
                  />
                  <Metric
                    label="As payee"
                    value={String(profile.tclkAsPayee.length)}
                    hint="Deals where this DID is the payee (worker)."
                  />
                  <Metric
                    label="Completed (payee)"
                    value={String(
                      profile.tclkAsPayee.filter((c) => c.state === "claimed").length,
                    )}
                    hint="Deals completed as payee (revealed + claimed)."
                  />
                  <Metric
                    label="Refunded (payer)"
                    value={String(
                      profile.tclkAsPayer.filter((c) => c.state === "refunded").length,
                    )}
                    hint="Deals where this DID had to refund as payer."
                  />
                </div>

                {/* Recent deals as payee */}
                {profile.tclkAsPayee.length > 0 ? (
                  <div className="mt-4">
                    <p className="mb-2 font-mono text-xs text-faint">Recent deals as payee</p>
                    <ul className="flex flex-col gap-1.5">
                      {profile.tclkAsPayee.slice(0, 5).map((c) => (
                        <li
                          key={c.contract_id}
                          className="flex items-center gap-2 rounded border border-border bg-elevated px-2.5 py-1.5"
                        >
                          <span className="font-mono text-xs text-accent">
                            {c.contract_id.slice(0, 16)}…
                          </span>
                          {c.amount ? (
                            <span className="font-mono text-xs text-muted">{c.amount}</span>
                          ) : null}
                          {c.asset ? (
                            <span className="font-mono text-[10px] text-muted">{c.asset}</span>
                          ) : null}
                          <span className={cn("font-mono text-xs", stateColor(c.state as never))}>
                            {stateLabel(c.state as never)}
                          </span>
                          {c.last_activity ? (
                            <span className="ml-auto font-mono text-[10px] text-faint">
                              {relativeTime(c.last_activity)}
                            </span>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </>
            )}
          </section>

          {/* Other participants */}
          {ds && ds.rooms && ds.rooms.length > 0 ? (
            <section>
              <h2 className="mb-4 font-mono text-xs tracking-wider text-faint uppercase">
                Also active in
              </h2>
              <div className="flex flex-wrap gap-1.5">
                {ds.rooms.map((room) => (
                  <a
                    key={room}
                    href={liveRoomUrl(room)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 rounded border border-border bg-elevated px-2 py-1 font-mono text-xs text-muted transition-colors hover:text-fg"
                  >
                    {room}
                    <ArrowUpRight className="size-3" />
                  </a>
                ))}
              </div>
            </section>
          ) : null}
        </div>
      </main>

      <footer className="relative z-10 border-t border-border">
        <div className="mx-auto max-w-4xl px-4 py-4 text-xs text-faint sm:px-6">
          <p>
            Unified DID profile · cross-referenced from{" "}
            <code className="font-mono text-muted">dids.json</code>,{" "}
            <code className="font-mono text-muted">kibble.json</code>,{" "}
            <code className="font-mono text-muted">tclk.json</code>,{" "}
            <code className="font-mono text-muted">reputation.json</code>
          </p>
        </div>
      </footer>
    </div>
  );
}

function ScoreBar({
  label,
  score,
  detail,
  tone = "accent",
}: {
  label: string;
  score: number;
  detail: string;
  tone?: "accent" | "good";
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

function stateColorForKibble(state: string): string {
  if (state === "attested") return "text-good";
  if (state === "accepted") return "text-good";
  if (state === "resulted") return "text-accent";
  if (state === "delivered") return "text-accent-2";
  if (state === "claimed") return "text-mid";
  return "text-faint";
}
