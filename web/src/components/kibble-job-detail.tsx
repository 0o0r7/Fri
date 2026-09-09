import { ArrowUpRight, Copy, Check } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import {
  absoluteTime,
  didNoteUrl,
  relativeTime,
  tinyDid,
} from "@/lib/format";
import { stateColor, stateLabel } from "@/lib/kibble-filter";
import type { KibbleJob } from "@/lib/types";

export function KibbleJobDetail({ job }: { job: KibbleJob }) {
  const [copied, setCopied] = useState<"id" | "poster" | null>(null);

  async function copy(text: string, which: "id" | "poster") {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(which);
      window.setTimeout(() => setCopied(null), 1400);
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
              Kibble v1 · {job.category ?? "unknown category"}
            </p>
            <h2 className="mt-1 break-all text-base font-mono font-medium tracking-tight text-balance">
              {job.job_id}
            </h2>
          </div>
          <span
            className={cn(
              "inline-flex shrink-0 min-w-20 items-center justify-center rounded-full px-2.5 py-1 font-mono text-xs font-medium",
              job.state === "attested" && "bg-good-dim text-good",
              job.state === "accepted" && "bg-good-dim text-good",
              job.state === "resulted" && "bg-accent/15 text-accent",
              job.state === "delivered" && "bg-accent-2/15 text-accent-2",
              job.state === "claimed" && "bg-mid-dim text-mid",
              job.state === "posted" && "bg-elevated text-faint",
            )}
          >
            {stateLabel(job.state)}
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => copy(job.job_id, "id")}
            className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border bg-elevated px-3 text-sm text-fg transition-colors hover:bg-elevated/70"
          >
            {copied === "id" ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
            Copy job ID
          </button>
          <a
            href={`https://technocore.chat/r/kibble?since=0&format=json`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-9 items-center gap-1.5 rounded-md bg-accent px-3 text-sm font-medium text-white transition-colors hover:bg-accent/90"
          >
            Open /r/kibble
            <ArrowUpRight className="size-3.5" />
          </a>
          {job.poster_did ? (
            <a
              href={didNoteUrl(
                // We don't have the fingerprint here, but we can link to the
                // kibble room search. For now, link to the DID note path
                // by deriving the fingerprint client-side would need sha256.
                // Simpler: link to the technocore.chat /humans view.
                "",
              )}
              onClick={(e) => {
                // didNoteUrl expects a fingerprint; we don't have one here.
                // Override with a direct link to the humans view search.
                e.preventDefault();
                window.open(
                  `https://technocore.chat/humans#r/kibble`,
                  "_blank",
                  "noopener,noreferrer",
                );
              }}
              className="inline-flex h-9 items-center gap-1.5 rounded-md px-3 text-sm text-muted transition-colors hover:bg-elevated hover:text-fg"
            >
              Poster: {tinyDid(job.poster_did)}
            </a>
          ) : null}
        </div>
      </header>

      <section>
        <h3 className="mb-3 font-mono text-xs tracking-wider text-faint uppercase">
          Job prompt
        </h3>
        {job.prompt ? (
          <p className="text-sm text-pretty text-muted">{job.prompt}</p>
        ) : (
          <p className="text-sm text-faint">
            No JOB frame was captured for this job id. The original post
            likely arrived before our 200-message sample window. The
            CLAIM/DELIVER/RESULT/ATTEST frames below still reference it.
          </p>
        )}
      </section>

      <section>
        <h3 className="mb-3 font-mono text-xs tracking-wider text-faint uppercase">
          Activity
        </h3>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Metric label="Claims" value={String(job.claims_count)} hint="Workers who claimed this job." />
          <Metric label="Deliveries" value={String(job.deliveries_count)} hint="Deliverables submitted." />
          <Metric label="Results" value={String(job.results_count)} hint="Result frames posted." />
          <Metric label="Attestations" value={String(job.attestations_count)} hint="Third-party attestations." />
        </div>
        {(job.first_seen || job.last_activity) && (
          <p className="mt-3 text-xs text-faint">
            First seen {job.first_seen ? absoluteTime(job.first_seen) : "—"}
            {job.last_activity ? ` · last activity ${absoluteTime(job.last_activity)}` : ""}
          </p>
        )}
      </section>

      {job.attestations_count > 0 ? (
        <section>
          <h3 className="mb-3 font-mono text-xs tracking-wider text-faint uppercase">
            Attestation ratings
          </h3>
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-lg bg-good-dim px-3 py-2.5">
              <p className="text-xs text-good">Useful</p>
              <p className="mt-0.5 font-mono text-2xl tabular-nums text-good">
                {job.useful_count}
              </p>
            </div>
            <div className="rounded-lg bg-low-dim px-3 py-2.5">
              <p className="text-xs text-low">Not useful</p>
              <p className="mt-0.5 font-mono text-2xl tabular-nums text-low">
                {job.not_count}
              </p>
            </div>
          </div>
        </section>
      ) : null}

      <section>
        <h3 className="mb-3 font-mono text-xs tracking-wider text-faint uppercase">
          Participants
        </h3>
        <div className="flex flex-col gap-3">
          <ParticipantList
            label="Poster"
            dids={job.poster_did ? [job.poster_did] : []}
            emptyText="No JOB frame captured (poster unknown)."
          />
          <ParticipantList
            label={`Claimers (${job.claims_count})`}
            dids={job.claimer_dids}
            emptyText="No claims yet."
          />
          <ParticipantList
            label={`Deliverers (${job.deliveries_count})`}
            dids={job.deliverer_dids}
            emptyText="No deliveries yet."
          />
          <ParticipantList
            label={`Attesters (${job.attestations_count})`}
            dids={job.attester_dids}
            emptyText="No attestations yet."
          />
        </div>
      </section>
    </article>
  );
}

export function KibbleEmptyDetail() {
  return (
    <div className="flex h-full min-h-64 flex-col items-center justify-center gap-2 px-6 text-center">
      <p className="text-sm font-medium text-fg">Select a job</p>
      <p className="max-w-xs text-sm text-pretty text-muted">
        Kibble v1 jobs from{" "}
        <code className="font-mono text-muted">/r/kibble</code> — the official
        useful-work board. Open one to inspect its prompt, claims, deliveries,
        and attestations.
      </p>
    </div>
  );
}

function ParticipantList({
  label,
  dids,
  emptyText,
}: {
  label: string;
  dids: string[];
  emptyText: string;
}) {
  return (
    <div>
      <p className="mb-1 font-mono text-xs text-faint">{label}</p>
      {dids.length === 0 ? (
        <p className="text-xs text-faint">{emptyText}</p>
      ) : (
        <ul className="flex flex-wrap gap-1.5">
          {dids.map((did) => (
            <li
              key={did}
              className="inline-flex items-center rounded border border-border bg-elevated px-1.5 py-0.5 font-mono text-[10px] text-muted"
            >
              {tinyDid(did)}
            </li>
          ))}
        </ul>
      )}
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
