import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, Search, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { ReputationRow } from "@/components/reputation-row";
import { ReputationDetail, ReputationEmptyDetail } from "@/components/reputation-detail";
import { filterReputation, reputationStats, type RepSortKey } from "@/lib/reputation-filter";
import { absoluteTime, relativeTime } from "@/lib/format";
import type { ReputationIndex } from "@/lib/types";

const SORTS: { id: RepSortKey; label: string }[] = [
  { id: "reputation", label: "Reputation" },
  { id: "activity", label: "Activity" },
  { id: "work", label: "Work" },
  { id: "reliability", label: "Reliability" },
];

export function ReputationPage({ index }: { index: ReputationIndex }) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<RepSortKey>("reputation");
  const [selected, setSelected] = useState<string | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  const stats = useMemo(() => reputationStats(index), [index]);
  const dids = useMemo(
    () => filterReputation(index.dids, { query, sort }),
    [index.dids, query, sort],
  );

  const selectedEntry =
    dids.find((d) => d.did === selected) ?? dids[0] ?? null;

  useEffect(() => {
    const hash = decodeURIComponent(window.location.hash.replace(/^#/, ""));
    if (hash && hash.startsWith("did:") && index.dids.some((d) => d.did === hash)) {
      setSelected(hash);
    } else if (index.dids[0]) {
      setSelected(index.dids[0].did);
    }
  }, [index.dids]);

  useEffect(() => {
    if (!selectedEntry) return;
    const next = `#${encodeURIComponent(selectedEntry.did)}`;
    if (window.location.hash !== next) {
      window.history.replaceState(null, "", next);
    }
  }, [selectedEntry]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement | null)?.tagName;
      const typing = tag === "INPUT" || tag === "TEXTAREA";
      if (e.key === "/" && !typing) {
        e.preventDefault();
        searchRef.current?.focus();
        return;
      }
      if (e.key === "Escape") {
        if (mobileOpen) setMobileOpen(false);
        else (e.target as HTMLElement | null)?.blur();
        return;
      }
      if (typing) return;
      if (e.key !== "j" && e.key !== "k" && e.key !== "Enter") return;
      if (dids.length === 0) return;
      const idx = Math.max(
        0,
        dids.findIndex((d) => d.did === selectedEntry?.did),
      );
      if (e.key === "j") {
        const next = dids[Math.min(dids.length - 1, idx + 1)];
        if (next) setSelected(next.did);
      } else if (e.key === "k") {
        const next = dids[Math.max(0, idx - 1)];
        if (next) setSelected(next.did);
      } else if (e.key === "Enter") {
        setMobileOpen(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dids, selectedEntry, mobileOpen]);

  function selectDid(did: string) {
    setSelected(did);
    setMobileOpen(true);
  }

  return (
    <div className="flex min-h-dvh flex-col bg-bg text-fg">
      <div className="pointer-events-none fixed inset-0 bg-grid" aria-hidden="true" />

      <section
        aria-label="Reputation snapshot"
        className="relative z-10 border-b border-border bg-surface/60"
      >
        <dl className="mx-auto flex max-w-screen-2xl gap-6 overflow-x-auto px-4 py-3 sm:px-6">
          <UpdatedStat iso={index.generated_at} />
          <Stat label="Scored" value={stats.total_scored.toLocaleString()} />
          <Stat label="Avg" value={stats.avg_score.toFixed(3)} />
          <Stat label="Max" value={stats.max_score.toFixed(3)} />
          <Stat
            label="With work"
            value={stats.with_work.toLocaleString()}
            hint="DIDs with at least 1 kibble delivery."
          />
          <Stat
            label="With TCLK"
            value={stats.with_tclk.toLocaleString()}
            hint="DIDs that have participated in TCLK deals."
          />
        </dl>
      </section>
      <p className="relative z-10 mx-auto w-full max-w-screen-2xl px-4 py-2 text-xs text-faint sm:px-6">
        Transparent reputation score (0-1) per DID. Formula:{" "}
        <code className="font-mono text-muted">0.3·activity + 0.4·work + 0.3·reliability</code>.
        Independent of Flop Labs. Not an airdrop signal.
      </p>

      <div className="relative z-10 mx-auto grid min-h-0 w-full max-w-screen-2xl flex-1 grid-cols-1 lg:h-0 lg:grow lg:grid-cols-12 lg:overflow-hidden">
        <div className="flex min-h-0 flex-col border-border lg:col-span-5 lg:h-full lg:border-r">
          <div className="flex flex-col gap-2 px-4 py-3 sm:px-5">
            <div className="relative">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-faint" />
              <input
                ref={searchRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search DID (or filter: work/tclk only)"
                aria-label="Search DIDs by reputation"
                className="h-10 w-full rounded-md border border-border bg-elevated pl-10 pr-3 text-sm text-fg placeholder:text-faint focus:border-accent focus:ring-2 focus:ring-accent/30 focus:outline-none"
              />
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="mr-1 font-mono text-xs tracking-wider text-faint uppercase">
                Sort
              </span>
              {SORTS.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => setSort(s.id)}
                  className={cn(
                    "h-9 min-w-9 rounded-md px-2.5 text-xs transition-colors duration-150",
                    sort === s.id
                      ? "bg-elevated text-fg shadow-[var(--shadow-border)]"
                      : "text-muted hover:text-fg",
                  )}
                >
                  {s.label}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              <span className="mr-1 font-mono text-xs tracking-wider text-faint uppercase">
                Buckets
              </span>
              {Object.entries(stats.buckets).map(([bucket, count]) => (
                <span
                  key={bucket}
                  className={cn(
                    "inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[10px]",
                    bucket.startsWith("high") && "border-border bg-good-dim text-good",
                    bucket.startsWith("medium") && "border-border bg-mid-dim text-mid",
                    bucket.startsWith("low") && "border-border bg-elevated text-muted",
                  )}
                >
                  {bucket}
                  <span className="tabular-nums">{count}</span>
                </span>
              ))}
            </div>
          </div>
          <div className="h-px bg-border" />
          <div
            className="min-h-0 flex-1 px-2 py-2 pb-20 sm:px-3 lg:overflow-y-auto"
            role="listbox"
            aria-label="DIDs by reputation"
          >
            {dids.length === 0 ? (
              <div className="px-3 py-16 text-center">
                <p className="text-sm text-muted">No DIDs match this filter.</p>
                <button
                  type="button"
                  className="mt-3 inline-flex h-9 items-center rounded-md px-3 text-sm text-muted transition-colors hover:bg-elevated hover:text-fg"
                  onClick={() => {
                    setQuery("");
                    setSort("reputation");
                  }}
                >
                  Reset
                </button>
              </div>
            ) : (
              <div className="flex flex-col gap-0.5">
                {dids.map((entry, i) => (
                  <ReputationRow
                    key={entry.did}
                    entry={entry}
                    rank={i + 1}
                    selected={selectedEntry?.did === entry.did}
                    onSelect={selectDid}
                  />
                ))}
              </div>
            )}
          </div>
          <p className="hidden px-5 py-2 font-mono text-xs text-faint lg:block">
            j / k to move · / to search · {dids.length} shown
          </p>
        </div>

        <aside className="hidden min-h-0 overflow-y-auto lg:col-span-7 lg:block">
          <div className="px-6 py-6 xl:px-8">
            {selectedEntry ? (
              <ReputationDetail entry={selectedEntry} />
            ) : (
              <ReputationEmptyDetail />
            )}
          </div>
        </aside>
      </div>

      {mobileOpen && selectedEntry ? (
        <div className="fixed inset-0 z-40 flex flex-col bg-bg lg:hidden">
          <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
            <button
              type="button"
              className="inline-flex h-9 items-center rounded-md px-3 text-sm text-muted transition-colors hover:bg-elevated hover:text-fg"
              onClick={() => setMobileOpen(false)}
            >
              Back to index
            </button>
            <button
              type="button"
              aria-label="Close detail"
              className="inline-flex size-9 items-center justify-center rounded-md text-muted transition-colors hover:bg-elevated hover:text-fg"
              onClick={() => setMobileOpen(false)}
            >
              <X className="size-4" />
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5">
            <ReputationDetail entry={selectedEntry} />
          </div>
        </div>
      ) : null}

      <footer className="relative z-10 border-t border-border">
        <div className="mx-auto flex max-w-screen-2xl flex-col gap-2 px-4 py-4 text-xs text-faint sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <p>
            Reputation v{index.version} ({index.schema_version}) · read-only ·{" "}
            <a
              className="text-muted hover:text-fg"
              href={index.source}
              target="_blank"
              rel="noopener noreferrer"
            >
              {index.source.replace(/^https?:\/\//, "")}
            </a>
          </p>
          <p className="flex flex-wrap items-center gap-2">
            <a
              href="/data/reputation.json"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded border border-border bg-elevated px-1.5 py-0.5 font-mono text-[10px] text-muted hover:text-fg"
            >
              GET /data/reputation.json
              <ArrowUpRight className="size-3" />
            </a>
            <a
              href="/docs/FRI_SPEC.md"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded border border-border bg-elevated px-1.5 py-0.5 font-mono text-[10px] text-muted hover:text-fg"
            >
              SPEC
              <ArrowUpRight className="size-3" />
            </a>
          </p>
        </div>
      </footer>
    </div>
  );
}

function UpdatedStat({ iso }: { iso: string }) {
  const [rel, setRel] = useState<string | null>(null);
  useEffect(() => {
    setRel(relativeTime(iso));
  }, [iso]);
  return <Stat label="Updated" value={rel ?? absoluteTime(iso)} hint={absoluteTime(iso)} />;
}

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="shrink-0" title={hint}>
      <dt className="font-mono text-xs tracking-wider text-faint uppercase">
        {label}
      </dt>
      <dd className="mt-0.5 font-mono text-sm tabular-nums text-fg">{value}</dd>
    </div>
  );
}
