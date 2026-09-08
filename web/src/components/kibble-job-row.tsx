import { cn } from "@/lib/utils";
import { relativeTime, tinyDid } from "@/lib/format";
import { stateColor, stateLabel } from "@/lib/kibble-filter";
import type { KibbleJob } from "@/lib/types";

export function KibbleJobRow({
  job,
  rank,
  selected,
  onSelect,
}: {
  job: KibbleJob;
  rank: number;
  selected: boolean;
  onSelect: (jobId: string) => void;
}) {
  const prompt = job.prompt ? job.prompt.slice(0, 80) : "(no prompt — JOB frame missed)";
  const hasAttest = job.attestations_count > 0;

  return (
    <button
      type="button"
      onClick={() => onSelect(job.job_id)}
      aria-current={selected ? "true" : undefined}
      className={cn(
        "group grid min-h-12 w-full grid-cols-[2.75rem_minmax(0,1fr)_auto] items-start gap-x-2 rounded-lg px-2.5 py-2.5 text-left",
        "transition-[background-color,box-shadow] duration-150 ease-out",
        "focus-visible:ring-2 focus-visible:ring-accent/50 focus-visible:outline-none",
        selected
          ? "bg-elevated shadow-[var(--shadow-border-hover)]"
          : "hover:bg-elevated/70",
      )}
    >
      <span className="pt-0.5 font-mono text-xs tabular-nums text-faint">
        {String(rank).padStart(3, "0")}
      </span>
      <span className="min-w-0">
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate font-mono text-sm text-fg">
            {job.job_id}
          </span>
          {job.category ? (
            <span className="inline-flex shrink-0 items-center rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-accent">
              {job.category}
            </span>
          ) : null}
        </span>
        <span className="mt-0.5 block min-w-0 truncate text-xs text-muted">
          {prompt}
        </span>
        <span className="mt-0.5 flex min-w-0 items-center gap-1.5 text-xs text-faint">
          <span className={cn("font-mono", stateColor(job.state))}>
            {stateLabel(job.state)}
          </span>
          <span>·</span>
          <span className="font-mono tabular-nums">{job.claims_count} claim</span>
          <span>·</span>
          <span className="font-mono tabular-nums">{job.deliveries_count} deliv</span>
          {hasAttest ? (
            <>
              <span>·</span>
              <span className="font-mono tabular-nums text-good">
                {job.useful_count} useful
              </span>
              {job.not_count > 0 ? (
                <span className="font-mono tabular-nums text-low">
                  {job.not_count} not
                </span>
              ) : null}
            </>
          ) : null}
          {job.last_activity ? (
            <>
              <span>·</span>
              <span>{relativeTime(job.last_activity)}</span>
            </>
          ) : null}
        </span>
      </span>
      <span className="mt-0.5 inline-flex min-w-14 items-center justify-end rounded-full bg-elevated px-2 py-0.5 font-mono text-[10px] text-muted">
        {job.poster_did ? tinyDid(job.poster_did) : "—"}
      </span>
    </button>
  );
}
