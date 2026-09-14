import { cn } from "@/lib/utils";

/**
 * FRI mark — brand signal bars (user-approved spec):
 * three ascending signal-cyan bars capped by the tallest signal-green bar.
 * Flat vector, no background plate — legible from favicon to hero size.
 * Placeholder geometry until the final Reve artwork arrives; swapping it
 * here (and /favicon.svg) is the single replacement point.
 */
export function FriMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 128 128"
      className={cn("inline-block", className)}
      aria-hidden="true"
    >
      <rect x="10" y="88" width="18" height="32" fill="var(--color-accent)" />
      <rect x="40" y="60" width="18" height="60" fill="var(--color-accent)" />
      <rect x="70" y="32" width="18" height="88" fill="var(--color-accent)" />
      <rect x="100" y="4" width="18" height="116" fill="var(--color-good)" />
    </svg>
  );
}
