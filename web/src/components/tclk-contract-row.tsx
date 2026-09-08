import { cn } from "@/lib/utils";
import { relativeTime, tinyDid } from "@/lib/format";
import {
  formatAmount,
  stateColor,
  stateLabel,
} from "@/lib/tclk-filter";
import type { TclkContract } from "@/lib/types";

export function TclkContractRow({
  contract,
  rank,
  selected,
  onSelect,
}: {
  contract: TclkContract;
  rank: number;
  selected: boolean;
  onSelect: (contractId: string) => void;
}) {
  const hasReceipt = contract.receipt_count > 0;
  const isRefunded = contract.state === "refunded";

  return (
    <button
      type="button"
      onClick={() => onSelect(contract.contract_id)}
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
          <span className="truncate font-mono text-xs text-fg">
            {contract.contract_id.slice(0, 18)}…
          </span>
          {contract.asset ? (
            <span
              className={cn(
                "inline-flex shrink-0 items-center rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider",
                contract.asset === "FLOP"
                  ? "bg-accent/10 text-accent"
                  : "bg-elevated text-muted",
              )}
            >
              {contract.asset}
            </span>
          ) : null}
        </span>
        <span className="mt-0.5 flex min-w-0 items-center gap-1.5 text-xs text-faint">
          <span className={cn("font-mono", stateColor(contract.state))}>
            {stateLabel(contract.state)}
          </span>
          <span>·</span>
          <span className="font-mono tabular-nums">
            {formatAmount(contract.amount)}
          </span>
          {contract.rails.length > 0 ? (
            <>
              <span>·</span>
              <span className="font-mono text-faint">{contract.rails.join(",")}</span>
            </>
          ) : null}
          {contract.job?.proto ? (
            <>
              <span>·</span>
              <span className="font-mono text-faint">{contract.job.proto}</span>
            </>
          ) : null}
          {contract.last_activity ? (
            <>
              <span>·</span>
              <span>{relativeTime(contract.last_activity)}</span>
            </>
          ) : null}
        </span>
        <span className="mt-0.5 flex min-w-0 items-center gap-1.5 text-xs text-faint">
          {contract.payer_did ? (
            <span className="font-mono">
              <span className="text-faint">P:</span>
              {tinyDid(contract.payer_did)}
            </span>
          ) : null}
          {contract.payee_did ? (
            <span className="font-mono">
              <span className="text-faint">·Y:</span>
              {tinyDid(contract.payee_did)}
            </span>
          ) : null}
          {hasReceipt ? (
            <span
              className={cn(
                "font-mono",
                isRefunded ? "text-low" : "text-good",
              )}
            >
              ·{contract.receipt_outcome ?? "?"}
            </span>
          ) : null}
        </span>
      </span>
      <span className="mt-0.5 inline-flex min-w-14 items-center justify-end rounded-full bg-elevated px-2 py-0.5 font-mono text-[10px] text-muted">
        {contract.lock_count}L
        <span className="mx-0.5 text-faint">/</span>
        {contract.reveal_count}R
      </span>
    </button>
  );
}
