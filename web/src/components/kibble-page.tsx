import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, Search, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { KibbleJobRow } from "@/components/kibble-job-row";
import { KibbleEmptyDetail, KibbleJobDetail } from "@/components/kibble-job-detail";
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
        className="relative z-10 border-b border-border bg-surface/60"
      >
        <dl className="mx-auto flex max-w-screen-2xl gap-6 overflow-x-auto px-4 py-3 sm:px-6">
          <UpdatedStat iso={index.generated_at} />
          <Stat label="Jobs" value={stats.total_jobs.toLocaleString()} />
          <Stat
            label="Attested"
            value={stats.attested_jobs.toLocaleString()}
            hint="Jobs with at least one ATTEST frame."
          />
          <Stat
            label="Useful"
            value={stats.useful_attestations.toLocaleString()}
            hint="ATTEST frames with rating=useful."
          />
          <Stat
            label="Not useful"
            value={stats.not_attestations.toLocaleString()}
            hint="ATTEST frames with rating=not."
          />
          <Stat label="Frames" value={index.total_frames.toLocaleString()} />
        </dl>
      </section>
      <p className="relative z-10 mx-auto w-full max-w-screen-2xl px-4 py-2 text-xs text-faint sm:px-6">
        Kibble is the official useful-work attribution board. FRI parses{" "}
        <code className="font-mono text-muted">JOB/CLAIM/RESULT/DELIVER/ATTEST/ACCEPT</code>{" "}
        v1 frames from <code className="font-mono text-muted">/r/kibble</code>.
        Independent of Flop Labs. No airdrop guarantee.
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
                placeholder="Search job id, category, prompt, or DID"
                aria-label="Search kibble jobs"
                className="h-10 w-full rounded-md border border-border bg-elevated pl-10 pr-3 text-sm text-fg placeholder:text-faint focus:border-accent focus:ring-2 focus:ring-accent/30 focus:outline-none"
              />
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="mr-1 font-mono text-xs tracking-wider text-faint uppercase">
                State
              </span>
              {STATES.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => setState(s.id)}
                  className={cn(
                    "h-9 min-w-9 rounded-md px-2.5 text-xs transition-colors duration-150",
                    state === s.id
                      ? "bg-elevated text-fg shadow-[var(--shadow-border)]"
                      : "text-muted hover:text-fg",
                  )}
                >
                  {s.label}
                </button>
              ))}
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
            {stats.top_workers.length > 0 ? (
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                <span className="mr-1 font-mono text-xs tracking-wider text-faint uppercase">
                  Top workers
                </span>
                {stats.top_workers.map((w) => (
                  <span
                    key={w.did}
                    className="inline-flex items-center gap-1 rounded border border-border bg-elevated px-1.5 py-0.5 font-mono text-[10px] text-muted"
                  >
                    {w.did.slice(8, 16)}…
                    <span className="text-good">{w.count}</span>
                  </span>
                ))}
              </div>
            ) : null}
          </div>
          <div className="h-px bg-border" />
          <div
            className="min-h-0 flex-1 px-2 py-2 pb-20 sm:px-3 lg:overflow-y-auto"
            role="listbox"
            aria-label="Kibble jobs"
          >
            {jobs.length === 0 ? (
              <div className="px-3 py-16 text-center">
                <p className="text-sm text-muted">No jobs match these filters.</p>
                <button
                  type="button"
                  className="mt-3 inline-flex h-9 items-center rounded-md px-3 text-sm text-muted transition-colors hover:bg-elevated hover:text-fg"
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
              <div className="flex flex-col gap-0.5">
                {jobs.map((job, i) => (
                  <KibbleJobRow
                    key={job.job_id}
                    job={job}
                    rank={i + 1}
                    selected={selectedJob?.job_id === job.job_id}
                    onSelect={selectJob}
                  />
                ))}
              </div>
            )}
          </div>
          <p className="hidden px-5 py-2 font-mono text-xs text-faint lg:block">
            j / k to move · / to search · {jobs.length} shown
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
            <KibbleJobDetail job={selectedJob} />
          </div>
        </div>
      ) : null}

      <footer className="relative z-10 border-t border-border">
        <div className="mx-auto flex max-w-screen-2xl flex-col gap-2 px-4 py-4 text-xs text-faint sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <p>
            Kibble index v{index.version} ({index.protocol_version}) · read-only ·{" "}
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
              href="/data/kibble.json"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded border border-border bg-elevated px-1.5 py-0.5 font-mono text-[10px] text-muted hover:text-fg"
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
