import { cn } from "@/lib/utils";
import { formatScore } from "@/lib/format";
import { scoreBand, type ScorePart } from "@/lib/score";

export function ScorePill({ score, className }: { score: number; className?: string }) {
  const band = scoreBand(score);
  return (
    <span
      className={cn(
        "inline-flex min-w-12 items-center justify-end rounded-full px-2 py-0.5 font-mono text-sm font-medium tabular-nums",
        band === "high" && "bg-good-dim text-good",
        band === "mid" && "bg-mid-dim text-mid",
        band === "low" && "bg-low-dim text-low",
        className,
      )}
    >
      {formatScore(score)}
    </span>
  );
}

export function ScoreBar({
  value,
  max,
  tone = "accent",
}: {
  value: number;
  max: number;
  tone?: "accent" | "good" | "mid" | "low";
}) {
  const pct = max <= 0 ? 0 : Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="h-1 w-full overflow-hidden rounded-full bg-elevated">
      <div
        className={cn(
          "h-full rounded-full transition-[width] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)]",
          tone === "accent" && "bg-accent",
          tone === "good" && "bg-good",
          tone === "mid" && "bg-mid",
          tone === "low" && "bg-low",
        )}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

export function ScoreComposition({ parts }: { parts: ScorePart[] }) {
  return (
    <ul className="flex flex-col gap-2.5">
      {parts.map((part) => (
        <li key={part.key} className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1">
          <span className="text-xs text-muted">{part.label}</span>
          <span
            className={cn(
              "font-mono text-xs tabular-nums",
              part.kind === "minus" ? "text-low" : "text-fg",
            )}
          >
            {part.kind === "minus" ? "−" : ""}
            {part.value.toFixed(1)}
            <span className="text-faint"> / {part.max}</span>
          </span>
          <div className="col-span-2">
            <ScoreBar
              value={part.value}
              max={part.max}
              tone={part.kind === "minus" ? "low" : "accent"}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}
