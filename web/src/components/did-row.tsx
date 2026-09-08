import { cn } from "@/lib/utils";
import { relativeTime, shortDid, tinyDid } from "@/lib/format";
import type { DidStats } from "@/lib/types";

export function DidRow({
  did,
  rank,
  selected,
  onSelect,
}: {
  did: DidStats;
  rank: number;
  selected: boolean;
  onSelect: (did: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(did.did)}
      aria-current={selected ? "true" : undefined}
      className={cn(
        "group grid min-h-11 w-full grid-cols-[2.75rem_minmax(0,1fr)_auto] items-start gap-x-2 rounded-lg px-2.5 py-2.5 text-left",
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
            {tinyDid(did.did)}
          </span>
        </span>
        <span className="mt-0.5 flex min-w-0 items-center gap-1.5 text-xs text-faint">
          <span className="shrink-0 font-mono tabular-nums">
            {did.messages_signed} msgs
          </span>
          <span className="shrink-0">·</span>
          <span className="shrink-0 font-mono tabular-nums">
            {did.rooms_active_in} room{did.rooms_active_in === 1 ? "" : "s"}
          </span>
          {did.last_active ? (
            <>
              <span className="shrink-0">·</span>
              <span className="shrink-0">{relativeTime(did.last_active)}</span>
            </>
          ) : null}
        </span>
        {did.rooms_active_in <= 3 && did.rooms.length > 0 ? (
          <span className="mt-0.5 hidden min-w-0 truncate text-xs text-faint sm:inline">
            {did.rooms.slice(0, 3).join(", ")}
          </span>
        ) : null}
      </span>
      <span className="mt-0.5 inline-flex min-w-16 items-center justify-end rounded-full bg-elevated px-2 py-0.5 font-mono text-[10px] text-muted">
        {did.fingerprint.slice(0, 8)}
      </span>
    </button>
  );
}

export { shortDid };
