import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, Search, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { KibbleJobRow } from "@/components/kibble-job-row";
import { KibbleEmptyDetail, KibbleJobDetail } from "@/components/kibble-job-detail";
import {
  LoadMore,
  StatBand,
  StatBandItem,
  usePagination,
} from "@/components/ui";
import { filterJobs, kibbleIndexStats, type StateFilter } from "@/lib/kibble-filter";
import { absoluteTime, relativeTime } from "@/lib/format";
import type { KibbleIndex, KibbleSortKey } from "@/lib/types";

const SORTS: { id: KibbleSortKey; label: string }[] = [
  { id: "recent", label: "Recent" },
  { id: "attestations", label: "Attests" },
  { id: "useful", label: "Useful" },
  { id: "claims", label: "Claims" },
  { id: "deliveries", label: "Deliv" },
  { id: "category", label: "Category" },
];

const STATES: { id: StateFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "posted", label: "Posted" },
  { id: "claimed", label: "Claimed" },
  { id: "delivered", label: "Delivered" },
  { id: "resulted", label: "Resulted" },
  { id: "attested", label: "Attested" },
];

const PAGE_SIZE = 20;

export function KibblePage({ index }: { index: KibbleIndex }) {
  const [query, setQuery] = useState("");
  const [state, setState] = useState<StateFilter>("all");
  const [sort, setSort] = useState<KibbleSortKey>("recent");
  const [selected, setSelected] = useState<string | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  const stats = useMemo(() => kibbleIndexStats(index), [index]);
  const jobs = useMemo(
    () => filterJobs(index.jobs, { query, state, sort }),
    [index.jobs, query, state, sort],
  );
  const { visible, visibleCount, loadMore, total } = usePagination(jobs, PAGE_SIZE);

  const selectedJob =
    jobs.find((j) => j.job_id === selected) ?? jobs[0] ?? null;

  useEffect(() => {
    const hash = decodeURIComponent(window.location.hash.replace(/^#/, ""));
    if (hash && hash.startsWith("k") && index.jobs.some((j) => j.job_id === hash)) {
      setSelected(hash);
    } else if (index.jobs[0]) {
      setSelected(index.jobs[0].job_id);
    }
  }, [index.jobs]);

  useEffect(() => {
    if (!selectedJob) return;
    const next = `#${encodeURIComponent(selectedJob.job_id)}`;
    if (window.location.hash !== next) {
      window.history.replaceState(null, "", next);
    }
  }, [selectedJob]);

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
      if (jobs.length === 0) return;
      const idx = Math.max(
        0,
        jobs.findIndex((j) => j.job_id === selectedJob?.job_id),
      );
      if (e.key === "j") {
        const next = jobs[Math.min(jobs.length - 1, idx + 1)];
        if (next) setSelected(next.job_id);
      } else if (e.key === "k") {
        const next = jobs[Math.max(0, idx - 1)];
        if (next) setSelected(next.job_id);
      } else if (e.key === "Enter") {
        setMobileOpen(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [jobs, selectedJob, mobileOpen]);

  function selectJob(jobId: string) {
    setSelected(jobId);
    setMobileOpen(true);
  }

  return (
    <div className="flex min-h-dvh flex-col bg-bg text-fg">
      <div className="pointer-events-none fixed inset-0 bg-grid" aria-hidden="true" />

      <section
        aria-label="Kibble snapshot"
        className="relative z-10 border-b border-border bg-surface/40"
      >
        <div className="mx-auto max-w-screen-2xl px-4 py-3 sm:px-6">
          <StatBand>
            <UpdatedStat iso={index.generated_at} />
            <StatBandItem label="Jobs" value={stats.total_jobs.toLocaleString()} tone="accent" />
            <StatBandItem
              label="Attested"
              value={stats.attested_jobs.toLocaleString()}
              hint="Jobs with at least one ATTEST frame."
              tone="good"
            />
            <StatBandItem
              label="Useful"
              value={stats.useful_attestations.toLocaleString()}
              hint="ATTEST frames with rating=useful."
              tone="good"
            />
            <StatBandItem
              label="Not useful"
              value={stats.not_attestations.toLocaleString()}
              hint="ATTEST frames with rating=not."
              tone="low"
            />
            <StatBandItem label="Frames" value={index.total_frames.toLocaleString()} />
          </StatBand>
        </div>
      </section>

      <p className="relative z-10 mx-auto w-full max-w-screen-2xl px-4 py-2 font-mono text-[11px] text-faint sm:px-6">
        Kibble is the official useful-work attribution board. FRI parses{" "}
        <code className="font-mono text-muted">JOB/CLAIM/RESULT/DELIVER/ATTEST/ACCEPT</code>{" "}
        v1 frames from <code className="font-mono text-muted">/r/kibble</code>.
        Independent of Flop Labs. No airdrop guarantee.
      </p>

      <div className="relative z-10 mx-auto grid min-h-0 w-full max-w-screen-2xl flex-1 grid-cols-1 lg:h-0 lg:grow lg:grid-cols-12 lg:overflow-hidden">
        <div className="flex min-h-0 flex-col border-border lg:col-span-5 lg:h-full lg:border-r">
          {/* Sticky filter bar */}
          <div className="sticky top-0 z-10 flex flex-col gap-2 border-b border-border bg-bg/95 px-4 py-3 backdrop-blur sm:px-5">
            <div className="relative">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-faint" />
              <input
                ref={searchRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search job id, category, prompt, or DID"
                aria-label="Search kibble jobs"
                className="h-10 w-full rounded border border-border bg-surface pl-10 pr-3 font-mono text-sm text-fg placeholder:text-faint focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent/40"
              />
            </div>
            <FilterRow label="State" value={state} options={STATES} onChange={setState} />
            <FilterRow label="Sort" value={sort} options={SORTS} onChange={setSort} />
            {stats.top_workers.length > 0 ? (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="mr-1 font-mono text-[10px] tracking-wider text-faint uppercase">
                  Top workers
                </span>
                {stats.top_workers.map((w) => (
                  <span
                    key={w.did}
                    className="inline-flex items-center gap-1 rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-[10px] text-muted"
                  >
                    {w.did.slice(8, 16)}…
                    <span className="text-good tabular-nums">{w.count}</span>
                  </span>
                ))}
              </div>
            ) : null}
          </div>
          <div
            className="min-h-0 flex-1 px-2 py-2 pb-20 sm:px-3 lg:overflow-y-auto"
            role="listbox"
            aria-label="Kibble jobs"
          >
            {jobs.length === 0 ? (
              <div className="px-3 py-16 text-center">
                <p className="font-mono text-sm text-muted">No jobs match these filters.</p>
                <button
                  type="button"
                  className="mt-3 inline-flex h-9 items-center rounded border border-border bg-surface px-3 font-mono text-xs text-muted transition-colors hover:border-accent hover:text-fg"
                  onClick={() => {
                    setQuery("");
                    setState("all");
                    setSort("recent");
                  }}
                >
                  Reset
                </button>
              </div>
            ) : (
              <div className="flex flex-col gap-1">
                {visible.map((job, i) => (
                  <KibbleJobRow
                    key={job.job_id}
                    job={job}
                    rank={i + 1}
                    selected={selectedJob?.job_id === job.job_id}
                    onSelect={selectJob}
                  />
                ))}
                <LoadMore
                  shown={visibleCount}
                  total={total}
                  pageSize={PAGE_SIZE}
                  onLoadMore={loadMore}
                />
              </div>
            )}
          </div>
          <p className="hidden border-t border-border px-5 py-2 font-mono text-[11px] text-faint lg:block">
            j / k to move · / to search · {visibleCount} of {total} shown
          </p>
        </div>

        <aside className="hidden min-h-0 overflow-y-auto lg:col-span-7 lg:block">
          <div className="px-6 py-6 xl:px-8">
            {selectedJob ? <KibbleJobDetail job={selectedJob} /> : <KibbleEmptyDetail />}
          </div>
        </aside>
      </div>

      {mobileOpen && selectedJob ? (
        <div className="fixed inset-0 z-40 flex flex-col bg-bg lg:hidden">
          <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
            <button
              type="button"
              className="inline-flex h-9 items-center rounded px-3 font-mono text-xs text-muted transition-colors hover:text-fg"
              onClick={() => setMobileOpen(false)}
            >
              Back to index
            </button>
            <button
              type="button"
              aria-label="Close detail"
              className="inline-flex size-9 items-center justify-center rounded text-muted transition-colors hover:text-fg"
              onClick={() => setMobileOpen(false)}
            >
              <X className="size-4" />
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5">
            <KibbleJobDetail job={selectedJob} />
          </div>
        </div>
      ) : null}

      <footer className="relative z-10 border-t border-border">
        <div className="mx-auto flex max-w-screen-2xl flex-col gap-2 px-4 py-4 font-mono text-[11px] text-faint sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <p>
            Kibble index v{index.version} ({index.protocol_version}) · read-only ·{" "}
            <a
              className="text-muted hover:text-accent"
              href={index.source}
              target="_blank"
              rel="noopener noreferrer"
            >
              {index.source.replace(/^https?:\/\//, "")}
            </a>
          </p>
          <p className="flex flex-wrap items-center gap-2">
            <a
              href="/data/kibble.json"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-[10px] text-muted hover:border-accent hover:text-accent"
            >
              GET /data/kibble.json
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
  return (
    <StatBandItem
      label="Updated"
      value={rel ?? absoluteTime(iso)}
      hint={absoluteTime(iso)}
    />
  );
}

function FilterRow<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { id: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="mr-1 font-mono text-[10px] tracking-wider text-faint uppercase">
        {label}
      </span>
      {options.map((opt) => (
        <button
          key={opt.id}
          type="button"
          onClick={() => onChange(opt.id)}
          className={cn(
            "inline-flex h-8 min-w-8 items-center rounded border px-2.5 font-mono text-xs transition-colors",
            value === opt.id
              ? "border-accent bg-accent/10 text-accent"
              : "border-border bg-surface text-muted hover:text-fg",
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
