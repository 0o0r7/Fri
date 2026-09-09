import { cn } from "@/lib/utils";
import { tinyDid } from "@/lib/format";
import { reputationBand } from "@/lib/reputation-filter";
import type { ReputationEntry } from "@/lib/types";

const BAND_COLORS = {
  high: "bg-good-dim text-good",
  medium: "bg-mid-dim text-mid",
  low: "bg-low-dim text-low",
};

export function ReputationRow({
  entry,
  rank,
  selected,
  onSelect,
}: {
  entry: ReputationEntry;
  rank: number;
  selected: boolean;
  onSelect: (did: string) => void;
}) {
  const band = reputationBand(entry.reputation_score);
  const hasWork = entry.components.work.deliveries_made > 0;
  const hasTclk = entry.components.reliability.has_tclk_activity;

  return (
    <button
      type="button"
      onClick={() => onSelect(entry.did)}
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
            {tinyDid(entry.did)}
          </span>
          {hasWork ? (
            <span className="inline-flex shrink-0 items-center rounded bg-good-dim px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-good">
              work
            </span>
          ) : null}
          {hasTclk ? (
            <span className="inline-flex shrink-0 items-center rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-accent">
              tclk
            </span>
          ) : null}
        </span>
        <span className="mt-0.5 flex min-w-0 items-center gap-1.5 text-xs text-faint">
          <span className="font-mono tabular-nums">
            act {entry.activity_score.toFixed(2)}
          </span>
          <span>·</span>
          <span className="font-mono tabular-nums">
            work {entry.work_score.toFixed(2)}
          </span>
          <span>·</span>
          <span className="font-mono tabular-nums">
            rel {entry.reliability_score.toFixed(2)}
          </span>
          {hasWork ? (
            <>
              <span>·</span>
              <span className="font-mono tabular-nums text-good">
                {entry.components.work.deliveries_made} deliv
              </span>
            </>
          ) : null}
          {hasTclk ? (
            <>
              <span>·</span>
              <span className="font-mono tabular-nums text-accent">
                {entry.components.reliability.deals_as_payee} deals
              </span>
            </>
          ) : null}
        </span>
      </span>
      <span
        className={cn(
          "mt-0.5 inline-flex min-w-16 items-center justify-center rounded-full px-2.5 py-1 font-mono text-sm font-medium tabular-nums",
          BAND_COLORS[band],
        )}
      >
        {entry.reputation_score.toFixed(3)}
      </span>
    </button>
  );
}
