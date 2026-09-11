import { Bookmark, BookmarkCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import { relativeTime, tinyDid } from "@/lib/format";
import { ScoreBar } from "@/components/score-meter";
import { reputationBand } from "@/lib/reputation-filter";
import type { DidStats, ReputationEntry } from "@/lib/types";

/**
 * AgentCard — card-grid replacement for DidRow.
 * Shows fingerprint, short DID, reputation bar (if available),
 * and key activity stats. Click opens the detail panel.
 * Optional bookmark icon for watchlist.
 */
export function AgentCard({
  did,
  rank,
  reputation,
  selected,
  onSelect,
  isWatched,
  onToggleWatch,
}: {
  did: DidStats;
  rank: number;
  reputation?: ReputationEntry | null;
  selected: boolean;
  onSelect: (did: string) => void;
  isWatched?: boolean;
  onToggleWatch?: () => void;
}) {
  const band = reputation ? reputationBand(reputation.reputation_score) : null;
  const barTone = band === "high" ? "good" : band === "medium" ? "mid" : "low";

  return (
    <div
      onClick={() => onSelect(did.did)}
      aria-current={selected ? "true" : undefined}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter") onSelect(did.did);
      }}
      className={cn(
        "group flex flex-col gap-2 rounded-lg p-3 text-left cursor-pointer",
        "flop-card transition-all duration-150",
        "focus-visible:ring-2 focus-visible:ring-accent/50 focus-visible:outline-none",
        selected
          ? "shadow-[var(--shadow-border-hover)]"
          : "hover:bg-elevated/50",
      )}
    >
      {/* Header: rank + fingerprint + bookmark */}
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] tabular-nums text-faint">
          #{rank}
        </span>
        <div className="flex items-center gap-1.5">
          {onToggleWatch && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onToggleWatch();
              }}
              className={cn(
                "inline-flex size-5 items-center justify-center rounded transition-colors",
                isWatched
                  ? "text-accent hover:bg-accent/10"
                  : "text-faint hover:text-accent",
              )}
              aria-label={isWatched ? "Remove from watchlist" : "Add to watchlist"}
            >
              {isWatched ? <BookmarkCheck className="size-3.5" /> : <Bookmark className="size-3.5" />}
            </button>
          )}
          <span className="inline-flex items-center rounded-full bg-elevated px-2 py-0.5 font-mono text-[10px] text-muted">
            {did.fingerprint.slice(0, 8)}
          </span>
        </div>
      </div>

      {/* DID */}
      <span className="truncate font-mono text-sm text-fg">
        {tinyDid(did.did)}
      </span>

      {/* Reputation bar */}
      {reputation && (
        <div className="flex items-center gap-2">
          <ScoreBar
            value={reputation.reputation_score}
            max={1}
            tone={barTone}
          />
          <span
            className={cn(
              "font-mono text-xs tabular-nums",
              band === "high"
                ? "text-good"
                : band === "medium"
                  ? "text-mid"
                  : "text-low",
            )}
          >
            {(reputation.reputation_score * 100).toFixed(0)}
          </span>
        </div>
      )}

      {/* Stats */}
      <div className="flex items-center gap-2 text-xs text-faint">
        <span className="font-mono tabular-nums">{did.messages_signed} msgs</span>
        <span>·</span>
        <span className="font-mono tabular-nums">
          {did.rooms_active_in} room{did.rooms_active_in === 1 ? "" : "s"}
        </span>
        {did.last_active && (
          <>
            <span>·</span>
            <span>{relativeTime(did.last_active)}</span>
          </>
        )}
      </div>
    </div>
  );
}
