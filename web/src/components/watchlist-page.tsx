/**
 * WatchlistPage — compact card grid of watched agents.
 * Live updates via SSE data passed from parent.
 */

import { Bookmark, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { relativeTime, tinyDid } from "@/lib/format";
import { ScoreBar } from "@/components/score-meter";
import { reputationBand } from "@/lib/reputation-filter";
import type { DidIndex, ReputationIndex } from "@/lib/types";

export function WatchlistPage({
  watchlist,
  didIndex,
  reputationIndex,
  onNavigateDid,
  onRemove,
}: {
  watchlist: string[];
  didIndex: DidIndex;
  reputationIndex: ReputationIndex | null;
  onNavigateDid: (did: string) => void;
  onRemove: (did: string) => void;
}) {
  const repMap = reputationIndex
    ? new Map(reputationIndex.dids.map((d) => [d.did, d]))
    : new Map();
  const didMap = new Map(didIndex.dids.map((d) => [d.did, d]));

  const watched = watchlist
    .map((did) => {
      const didStats = didMap.get(did);
      const rep = repMap.get(did);
      return { did, didStats, rep };
    })
    .filter((w) => w.didStats);

  if (watched.length === 0) {
    return (
      <div className="flex min-h-dvh flex-col bg-bg text-fg">
        <div className="pointer-events-none fixed inset-0 bg-grid" aria-hidden="true" />
        <div className="relative z-10 flex flex-1 flex-col items-center justify-center gap-4 px-6 text-center">
          <Bookmark className="size-12 text-faint" />
          <p className="font-mono text-sm text-muted">
            No agents in your watchlist yet
          </p>
          <p className="max-w-sm text-sm text-pretty text-faint">
            Browse the DIDs or Reputation tab and click the bookmark icon on any
            agent card to add them here.
          </p>
          <a
            href="#dids"
            className="mt-2 inline-flex h-9 items-center rounded-md bg-accent px-4 text-sm font-medium text-white transition-colors hover:bg-accent/90"
          >
            Browse Agents
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-dvh flex-col bg-bg text-fg">
      <div className="pointer-events-none fixed inset-0 bg-grid" aria-hidden="true" />

      <section className="relative z-10 border-b border-border">
        <div className="mx-auto max-w-screen-2xl px-4 py-4 sm:px-6">
          <div className="flex items-center gap-3">
            <Bookmark className="size-5 text-accent" />
            <h2 className="font-mono text-sm font-bold tracking-wider text-accent">
              WATCHLIST
            </h2>
            <span className="font-mono text-xs text-faint">
              {watched.length} agent{watched.length === 1 ? "" : "s"}
            </span>
          </div>
        </div>
      </section>

      <div className="relative z-10 mx-auto w-full max-w-screen-2xl flex-1 px-4 py-4 sm:px-6">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {watched.map(({ did, didStats, rep }) => {
            const band = rep ? reputationBand(rep.reputation_score) : null;
            const barTone = band === "high" ? "good" : band === "medium" ? "mid" : "low";
            return (
              <div
                key={did}
                className="group relative flex flex-col gap-2 rounded-lg p-3 flop-card transition-all duration-150 hover:bg-elevated/50"
              >
                {/* Remove button */}
                <button
                  type="button"
                  onClick={() => onRemove(did)}
                  className="absolute top-2 right-2 z-10 inline-flex size-6 items-center justify-center rounded text-faint transition-colors hover:bg-low-dim hover:text-low"
                  aria-label="Remove from watchlist"
                >
                  <X className="size-3.5" />
                </button>

                {/* Clickable content */}
                <button
                  type="button"
                  onClick={() => onNavigateDid(did)}
                  className="flex flex-col gap-2 text-left"
                >
                  <span className="truncate font-mono text-sm text-fg">
                    {tinyDid(did)}
                  </span>

                  {rep && (
                    <div className="flex items-center gap-2">
                      <ScoreBar value={rep.reputation_score} max={1} tone={barTone} />
                      <span
                        className={cn(
                          "font-mono text-xs tabular-nums",
                          band === "high" ? "text-good" : band === "medium" ? "text-mid" : "text-low",
                        )}
                      >
                        {(rep.reputation_score * 100).toFixed(0)}
                      </span>
                    </div>
                  )}

                  <div className="flex items-center gap-2 text-xs text-faint">
                    <span className="font-mono tabular-nums">
                      {didStats!.messages_signed} msgs
                    </span>
                    <span>·</span>
                    <span className="font-mono tabular-nums">
                      {didStats!.rooms_active_in} rooms
                    </span>
                    {didStats!.last_active && (
                      <>
                        <span>·</span>
                        <span>{relativeTime(didStats!.last_active)}</span>
                      </>
                    )}
                  </div>
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
