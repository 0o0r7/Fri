import { cn } from "@/lib/utils";

/**
 * FRI mark — FLOP DNA signal bars.
 * Cyan ascending bars (primary signal) capped with an Electric Green
 * bar (verified state). Surface background with 1px border + 4px radius.
 */
export function FriMark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex size-9 items-end justify-center gap-[3px] rounded bg-surface pb-1.5 shadow-[var(--shadow-border)]",
        className,
      )}
      aria-hidden="true"
    >
      <span className="h-1.5 w-[3px] rounded-sm bg-accent/40" />
      <span className="h-2.5 w-[3px] rounded-sm bg-accent/65" />
      <span className="h-3.5 w-[3px] rounded-sm bg-accent" />
      <span className="h-[18px] w-[3px] rounded-sm bg-good" />
    </span>
  );
}
