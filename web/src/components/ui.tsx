/**
 * FRI shared layout components — FLOP Design DNA.
 *
 * These are the building blocks every tab page uses so the five tabs
 * (Rooms, DIDs, Kibble, TCLK, Reputation) feel like the same product:
 *
 *   - Metric        single label + tabular-nums value, FLOP card surface
 *   - StatBand      grid of Metrics with 1px grid-line separators
 *   - Card          generic surface card (1px border, 8px radius)
 *   - SectionHeading  Space Mono cyan heading with `#` anchor on hover
 *   - DefCallout    left-border accent surface (FLOP `.def`)
 *   - LoadMore      "Load more" button replacing infinite scroll
 *   - usePagination small hook returning {visible, loadMore, reset}
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/* Metric                                                             */
/* ------------------------------------------------------------------ */

export function Metric({
  label,
  value,
  hint,
  tone = "default",
  className,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  tone?: "default" | "accent" | "good" | "mid" | "low";
  className?: string;
}) {
  const valueColor =
    tone === "accent"
      ? "text-accent"
      : tone === "good"
        ? "text-good"
        : tone === "mid"
          ? "text-mid"
          : tone === "low"
            ? "text-low"
            : "text-fg";
  return (
    <div className={cn("flop-card px-3 py-2.5", className)} title={hint}>
      <p className="font-mono text-[10px] tracking-wider text-faint uppercase">
        {label}
      </p>
      <p
        className={cn(
          "mt-1 font-mono text-sm tabular-nums",
          valueColor,
        )}
      >
        {value}
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* StatBand — FLOP `.metrics` grid with 1px grid lines                */
/* ------------------------------------------------------------------ */

export function StatBand({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <dl className={cn("flop-metrics", className)} aria-label="Snapshot metrics">
      {children}
    </dl>
  );
}

export function StatBandItem({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  tone?: "default" | "accent" | "good" | "mid" | "low";
}) {
  const valueColor =
    tone === "accent"
      ? "text-accent"
      : tone === "good"
        ? "text-good"
        : tone === "mid"
          ? "text-mid"
          : tone === "low"
            ? "text-low"
            : "text-fg";
  return (
    <div className="px-4 py-3" title={hint}>
      <dt className="font-mono text-[10px] tracking-wider text-faint uppercase">
        {label}
      </dt>
      <dd
        className={cn(
          "mt-1 font-mono text-base tabular-nums",
          valueColor,
        )}
      >
        {value}
      </dd>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Card — generic content panel                                       */
/* ------------------------------------------------------------------ */

export function Card({
  children,
  className,
  as: Tag = "div",
}: {
  children: React.ReactNode;
  className?: string;
  as?: React.ElementType;
}) {
  return (
    <Tag className={cn("flop-card-lg p-4 sm:p-5", className)}>{children}</Tag>
  );
}

/* ------------------------------------------------------------------ */
/* SectionHeading — Space Mono cyan, # anchor on hover                */
/* ------------------------------------------------------------------ */

export function SectionHeading({
  id,
  children,
  className,
  uppercase = false,
}: {
  id?: string;
  children: React.ReactNode;
  className?: string;
  uppercase?: boolean;
}) {
  const safeId = id ?? slugify(typeof children === "string" ? children : "");
  return (
    <h3
      id={safeId || undefined}
      className={cn(
        "group flop-section-heading text-sm",
        uppercase && "tracking-wider uppercase",
        className,
      )}
    >
      <a
        href={safeId ? `#${safeId}` : undefined}
        className="inline-flex items-center gap-1.5 text-accent no-underline"
        aria-label={typeof children === "string" ? children : undefined}
      >
        {children}
        <span
          aria-hidden="true"
          className="font-mono text-muted opacity-0 transition-opacity group-hover:opacity-100"
        >
          #
        </span>
      </a>
    </h3>
  );
}

/* ------------------------------------------------------------------ */
/* DefCallout — FLOP `.def`                                            */
/* ------------------------------------------------------------------ */

export function DefCallout({
  children,
  className,
  title,
}: {
  children: React.ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <div className={cn("flop-def", className)}>
      {title ? (
        <p className="mb-1 font-mono text-xs tracking-wider text-accent uppercase">
          {title}
        </p>
      ) : null}
      <div className="text-sm text-pretty text-muted">{children}</div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* LoadMore — replaces infinite scroll                                 */
/* ------------------------------------------------------------------ */

export function LoadMore({
  shown,
  total,
  pageSize,
  onLoadMore,
  className,
}: {
  shown: number;
  total: number;
  pageSize: number;
  onLoadMore: () => void;
  className?: string;
}) {
  const remaining = Math.max(0, total - shown);
  const nextBatch = Math.min(pageSize, remaining);
  if (remaining <= 0) {
    return (
      <div
        className={cn(
          "flex items-center justify-center gap-2 px-4 py-3 font-mono text-[11px] tracking-wider text-faint uppercase",
          className,
        )}
      >
        End of list · {total.toLocaleString()} total
      </div>
    );
  }
  return (
    <div className={cn("flex flex-col items-center gap-1.5 px-4 py-4", className)}>
      <button
        type="button"
        onClick={onLoadMore}
        className="inline-flex h-9 items-center gap-2 rounded border border-border bg-surface px-4 font-mono text-xs tracking-wider text-accent uppercase transition-colors hover:border-accent hover:bg-elevated"
      >
        Load more
        <span className="tabular-nums text-muted">+{nextBatch.toLocaleString()}</span>
      </button>
      <p className="font-mono text-[10px] tabular-nums text-faint">
        {shown.toLocaleString()} / {total.toLocaleString()} shown
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* usePagination — shared "20 per page, Load more" hook                */
/* ------------------------------------------------------------------ */

/**
 * Keeps a visible-count state in sync with a list. When the source list
 * shrinks below the current visible count (e.g. a filter change), the
 * counter is reset to the initial page size automatically.
 */
export function usePagination<T>(items: T[], pageSize = 20) {
  const [visibleCount, setVisibleCount] = useState(pageSize);

  // Reset pagination whenever the underlying list identity changes.
  // We track items.length + the first item identity so filter/sort changes
  // restart at page 1 but expanding the same list (rare) doesn't.
  const firstKey = items[0]
    ? (items[0] as { id?: string; did?: string; room?: string; job_id?: string; contract_id?: string })
    : null;
  const fingerprint = `${items.length}:${firstKey?.id ?? firstKey?.did ?? firstKey?.room ?? firstKey?.job_id ?? firstKey?.contract_id ?? ""}`;

  const lastFingerprint = useRef(fingerprint);
  useLayoutEffect(() => {
    if (lastFingerprint.current !== fingerprint) {
      lastFingerprint.current = fingerprint;
      setVisibleCount(pageSize);
    }
  }, [fingerprint, pageSize]);

  // Also reset when the page size itself changes.
  useEffect(() => {
    setVisibleCount((c) => Math.min(Math.max(c, pageSize), Math.max(items.length, pageSize)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pageSize]);

  const visible = items.slice(0, visibleCount);
  const loadMore = useCallback(() => {
    setVisibleCount((c) => c + pageSize);
  }, [pageSize]);
  const reset = useCallback(() => setVisibleCount(pageSize), [pageSize]);

  return { visible, visibleCount, loadMore, reset, pageSize, total: items.length };
}

/* ------------------------------------------------------------------ */
/* helpers                                                            */
/* ------------------------------------------------------------------ */

function slugify(input: string): string {
  return input
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}
