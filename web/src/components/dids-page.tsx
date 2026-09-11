import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, Search, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { AgentCard } from "@/components/agent-card";
import { DidDetail, DidEmptyDetail } from "@/components/did-detail";
import {
  LoadMore,
  StatBand,
  StatBandItem,
  usePagination,
} from "@/components/ui";
import { filterDids, didIndexStats, type ReputationFilter, type ActivityFilter } from "@/lib/did-filter";
import { absoluteTime, relativeTime } from "@/lib/format";
import type { DidIndex, DidSortKey, ReputationIndex } from "@/lib/types";

const SORTS: { id: DidSortKey; label: string }[] = [
  { id: "messages", label: "Messages" },
  { id: "reputation", label: "Reputation" },
  { id: "rooms", label: "Rooms" },
  { id: "recent", label: "Recent" },
  { id: "avg_len", label: "Avg len" },
];

const REP_FILTERS: { id: ReputationFilter; label: string }[] = [
  { id: "all", label: "Any" },
  { id: "high", label: "High" },
  { id: "mid", label: "Mid" },
  { id: "low", label: "Low" },
];

const ACTIVITY_FILTERS: { id: ActivityFilter; label: string }[] = [
  { id: "all", label: "Any" },
  { id: "high", label: "100+" },
  { id: "medium", label: "10-99" },
  { id: "low", label: "<10" },
];

const PAGE_SIZE = 20;

export function DidsPage({ index, reputationIndex }: { index: DidIndex; reputationIndex: ReputationIndex | null }) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<DidSortKey>("messages");
  const [repFilter, setRepFilter] = useState<ReputationFilter>("all");
  const [actFilter, setActFilter] = useState<ActivityFilter>("all");
  const [roomFilter, setRoomFilter] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  const stats = useMemo(() => didIndexStats(index), [index]);
  const repMap = useMemo(() => {
    if (!reputationIndex) return new Map<string, ReputationIndex["dids"][number]>();
    return new Map(reputationIndex.dids.map((d) => [d.did, d]));
  }, [reputationIndex]);

  const dids = useMemo(
    () => filterDids(index.dids, { query, sort, reputation: repFilter, activity: actFilter, room: roomFilter ?? undefined }, repMap),
    [index.dids, query, sort, repFilter, actFilter, roomFilter, repMap],
  );
  const { visible, visibleCount, loadMore, total } = usePagination(dids, PAGE_SIZE);

  const selectedDid =
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
    if (!selectedDid) return;
    const next = `#${encodeURIComponent(selectedDid.did)}`;
    if (window.location.hash !== next) {
      window.history.replaceState(null, "", next);
    }
  }, [selectedDid]);

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
        dids.findIndex((d) => d.did === selectedDid?.did),
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
  }, [dids, selectedDid, mobileOpen]);

  function selectDid(did: string) {
    setSelected(did);
    setMobileOpen(true);
  }

  return (
    <div className="flex min-h-dvh flex-col bg-bg text-fg">
      <div className="pointer-events-none fixed inset-0 bg-grid" aria-hidden="true" />

      <section
        aria-label="DID index snapshot"
        className="relative z-10 border-b border-border bg-surface/40"
      >
        <div className="mx-auto max-w-screen-2xl px-4 py-3 sm:px-6">
          <StatBand>
            <UpdatedStat iso={index.generated_at} />
            <StatBandItem label="Total DIDs" value={stats.total_dids.toLocaleString()} tone="accent" />
            <StatBandItem
              label="Sampled msgs"
              value={stats.sampled_messages.toLocaleString()}
            />
            <StatBandItem
              label="Signed ratio"
              value={`${(stats.signed_ratio * 100).toFixed(1)}%`}
              hint="Fraction of sampled messages from did:key writers."
              tone="good"
            />
            <StatBandItem
              label="Multi-room"
              value={stats.multi_room_dids.toLocaleString()}
              hint="DIDs active in 2+ rooms. A rough diversity signal."
            />
          </StatBand>
        </div>
      </section>

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
                placeholder="Search DID, fingerprint, or room"
                aria-label="Search DIDs"
                className="h-10 w-full rounded border border-border bg-surface pl-10 pr-3 font-mono text-sm text-fg placeholder:text-faint focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent/40"
              />
            </div>
            <FilterRow label="Sort" value={sort} options={SORTS} onChange={setSort} />
            <FilterRow label="Rep" value={repFilter} options={REP_FILTERS} onChange={setRepFilter} />
            <FilterRow label="Activity" value={actFilter} options={ACTIVITY_FILTERS} onChange={setActFilter} />
            {stats.top_rooms.length > 0 ? (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="mr-1 font-mono text-[10px] tracking-wider text-faint uppercase">
                  {roomFilter ? "Room" : "Top rooms"}
                </span>
                {roomFilter && (
                  <button
                    type="button"
                    onClick={() => setRoomFilter(null)}
                    className="inline-flex items-center gap-1 rounded border border-accent bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] text-accent"
                  >
                    ✕ {roomFilter}
                  </button>
                )}
                {!roomFilter && stats.top_rooms.map((r) => (
                  <button
                    key={r.room}
                    type="button"
                    onClick={() => setRoomFilter(r.room)}
                    className="inline-flex items-center gap-1 rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-[10px] text-muted transition-colors hover:border-accent hover:text-accent"
                  >
                    {r.room}
                    <span className="text-faint tabular-nums">{r.count}</span>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
          <div
            className="min-h-0 flex-1 px-2 py-2 pb-20 sm:px-3 lg:overflow-y-auto"
            role="listbox"
            aria-label="DIDs"
          >
            {dids.length === 0 ? (
              <div className="px-3 py-16 text-center">
                <p className="font-mono text-sm text-muted">No DIDs match this filter.</p>
                <button
                  type="button"
                  className="mt-3 inline-flex h-9 items-center rounded border border-border bg-surface px-3 font-mono text-xs text-muted transition-colors hover:border-accent hover:text-fg"
                  onClick={() => {
                    setQuery("");
                    setSort("messages");
                    setRepFilter("all");
                    setActFilter("all");
                    setRoomFilter(null);
                  }}
                >
                  Reset
                </button>
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-2">
                {visible.map((did, i) => (
                  <AgentCard
                    key={did.did}
                    did={did}
                    rank={i + 1}
                    reputation={repMap.get(did.did)}
                    selected={selectedDid?.did === did.did}
                    onSelect={selectDid}
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
            {selectedDid ? <DidDetail did={selectedDid} /> : <DidEmptyDetail />}
          </div>
        </aside>
      </div>

      {mobileOpen && selectedDid ? (
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
            <DidDetail did={selectedDid} />
          </div>
        </div>
      ) : null}

      <footer className="relative z-10 border-t border-border">
        <div className="mx-auto flex max-w-screen-2xl flex-col gap-2 px-4 py-4 font-mono text-[11px] text-faint sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <p>
            DID index v{index.version} · read-only ·{" "}
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
              href="/data/dids.json"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-[10px] text-muted hover:border-accent hover:text-accent"
            >
              GET /data/dids.json
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
