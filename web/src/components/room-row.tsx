import { cn } from "@/lib/utils";
import { formatIdle, kindLabel, roomKind } from "@/lib/format";
import type { Room } from "@/lib/types";
import { ScorePill } from "./score-meter";

export function RoomRow({
  room,
  selected,
  onSelect,
}: {
  room: Room;
  selected: boolean;
  onSelect: (name: string) => void;
}) {
  const kind = roomKind(room.room);
  const idle = room.metrics.idle_seconds;
  const live = idle < 30;
  const sample = room.samples[0]?.text ?? "";

  return (
    <button
      type="button"
      onClick={() => onSelect(room.room)}
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
        {String(room.rank).padStart(2, "0")}
      </span>
      <span className="min-w-0">
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate font-medium tracking-tight text-fg">
            {room.room}
          </span>
          {live ? (
            <span className="relative flex size-1.5 shrink-0">
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-good opacity-60" />
              <span className="relative inline-flex size-1.5 rounded-full bg-good" />
            </span>
          ) : null}
        </span>
        <span className="mt-0.5 flex min-w-0 items-center gap-1.5 text-xs text-faint">
          <span
            className={cn(
              "inline-flex shrink-0 items-center rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider",
              kind === "named"
                ? "bg-accent/10 text-accent"
                : "bg-elevated text-muted",
            )}
          >
            {kindLabel(kind)}
          </span>
          <span className="shrink-0 font-mono tabular-nums">{formatIdle(idle)}</span>
          {room.topic ? (
            <span className="hidden min-w-0 truncate sm:inline">{room.topic}</span>
          ) : sample ? (
            <span className="hidden min-w-0 truncate sm:inline">{sample}</span>
          ) : null}
        </span>
      </span>
      <ScorePill score={room.score} className="mt-0.5" />
    </button>
  );
}
