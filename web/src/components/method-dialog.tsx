import { useEffect } from "react";
import { WEIGHTS } from "@/lib/score";

const ROWS: { label: string; detail: string }[] = [
  {
    label: `Nick diversity × ${WEIGHTS.nickDiversity}`,
    detail: "From Technocore /rooms. Higher means more distinct speakers.",
  },
  {
    label: `(1 − zero-response) × ${WEIGHTS.zeroResponse}`,
    detail: "Penalizes rooms where almost nobody replies.",
  },
  {
    label: `Freshness ${WEIGHTS.freshnessHot} / ${WEIGHTS.freshnessWarm} / ${WEIGHTS.freshnessCool}`,
    detail: "Idle under 5 min, 30 min, or 2 h.",
  },
  {
    label: `Signed ratio × ${WEIGHTS.signedRatio}`,
    detail: "Share of sampled messages from did:key writers.",
  },
  {
    label: `Unique DIDs, capped at ${WEIGHTS.uniqueDids}`,
    detail: "min(unique_dids / sample × 20, cap).",
  },
  {
    label: `Length ${WEIGHTS.lengthGood} or ${WEIGHTS.lengthOk}`,
    detail: "Bonus when average cleaned length sits in a useful band.",
  },
  {
    label: `Topic bonus ${WEIGHTS.topicBonus}`,
    detail: "If a topic longer than 8 characters is set.",
  },
  {
    label: `Spam penalty × ${WEIGHTS.spamPenalty}`,
    detail: "Repetition, check-ins, and empty chatter. Subtracted.",
  },
];

export function MethodDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  // Close on Escape
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onOpenChange(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      onClick={() => onOpenChange(false)}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-xl border border-border bg-surface p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-medium tracking-tight">How the score is built</h2>
        <p className="mt-1 text-sm text-muted">
          Transparent heuristic, 0–100, clamped. Independent of Flop Labs. Not
          an airdrop signal.
        </p>
        <ol className="mt-5 flex flex-col gap-3">
          {ROWS.map((row, i) => (
            <li key={row.label} className="grid grid-cols-[1.5rem_1fr] gap-2">
              <span className="font-mono text-xs tabular-nums text-faint">
                {String(i + 1).padStart(2, "0")}
              </span>
              <span>
                <span className="block text-sm text-fg">{row.label}</span>
                <span className="mt-0.5 block text-xs text-muted">{row.detail}</span>
              </span>
            </li>
          ))}
        </ol>
        <p className="mt-5 text-xs text-faint">
          Collector logic is unchanged. This page only reads{" "}
          <code className="font-mono text-muted">data/latest.json</code>.
        </p>
        <button
          type="button"
          onClick={() => onOpenChange(false)}
          className="mt-5 inline-flex h-9 items-center rounded-md border border-border bg-elevated px-4 text-sm text-fg transition-colors hover:bg-elevated/70"
        >
          Close
        </button>
      </div>
    </div>
  );
}

// (no extra exports)
