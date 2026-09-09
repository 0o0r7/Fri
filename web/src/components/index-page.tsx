import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, Check, Copy, Info, Search, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { MethodDialog } from "@/components/method-dialog";
import { EmptyDetail, RoomDetail } from "@/components/room-detail";
import { RoomRow } from "@/components/room-row";
import {
  LoadMore,
  StatBand,
  StatBandItem,
  usePagination,
} from "@/components/ui";
import {
  filterRooms,
  snapshotStats,
  type BandFilter,
  type KindFilter,
} from "@/lib/filter";
import { absoluteTime, formatScore, relativeTime } from "@/lib/format";
import type { Feed, SortKey } from "@/lib/types";

const SORTS: { id: SortKey; label: string }[] = [
  { id: "rank", label: "Rank" },
  { id: "idle", label: "Idle" },
  { id: "diversity", label: "Diversity" },
  { id: "signed", label: "Signed" },
  { id: "spam", label: "Spam" },
  { id: "name", label: "Name" },
];

const KINDS: { id: KindFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "named", label: "Named" },
  { id: "mailbox", label: "Mailbox" },
  { id: "pair", label: "Pair" },
];

const BANDS: { id: BandFilter; label: string }[] = [
  { id: "all", label: "Any" },
  { id: "high", label: "High" },
  { id: "mid", label: "Mid" },
  { id: "low", label: "Low" },
];

const PAGE_SIZE = 20;
const JSON_PATH = "/data/latest.json";

export function IndexPage({ feed }: { feed: Feed }) {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<KindFilter>("all");
  const [band, setBand] = useState<BandFilter>("all");
  const [sort, setSort] = useState<SortKey>("rank");
  const [selected, setSelected] = useState<string | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [methodOpen, setMethodOpen] = useState(false);
  const [copiedFeed, setCopiedFeed] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  const stats = useMemo(() => snapshotStats(feed), [feed]);
  const rooms = useMemo(
    () => filterRooms(feed.rooms, { query, kind, band, sort }),
    [feed.rooms, query, kind, band, sort],
  );
  const { visible, visibleCount, loadMore, total } = usePagination(rooms, PAGE_SIZE);

  const selectedRoom = rooms.find((r) => r.room === selected) ?? rooms[0] ?? null;

  useEffect(() => {
    const hash = decodeURIComponent(window.location.hash.replace(/^#/, ""));
    if (hash && feed.rooms.some((r) => r.room === hash)) {
      setSelected(hash);
    } else if (feed.rooms[0]) {
      setSelected(feed.rooms[0].room);
    }
  }, [feed.rooms]);

  useEffect(() => {
    if (!selectedRoom) return;
    const next = `#${encodeURIComponent(selectedRoom.room)}`;
    if (window.location.hash !== next) {
      window.history.replaceState(null, "", next);
    }
  }, [selectedRoom]);

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
      if (rooms.length === 0) return;
      const idx = Math.max(
        0,
        rooms.findIndex((r) => r.room === selectedRoom?.room),
      );
      if (e.key === "j") {
        const next = rooms[Math.min(rooms.length - 1, idx + 1)];
        if (next) setSelected(next.room);
      } else if (e.key === "k") {
        const next = rooms[Math.max(0, idx - 1)];
        if (next) setSelected(next.room);
      } else if (e.key === "Enter") {
        setMobileOpen(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rooms, selectedRoom, mobileOpen]);

  function selectRoom(name: string) {
    setSelected(name);
    setMobileOpen(true);
  }

  async function copyFeedUrl() {
    const url = new URL(JSON_PATH, window.location.origin).toString();
    try {
      await navigator.clipboard.writeText(url);
      setCopiedFeed(true);
      window.setTimeout(() => setCopiedFeed(false), 1400);
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="flex min-h-dvh flex-col bg-bg text-fg">
      <div className="pointer-events-none fixed inset-0 bg-grid" aria-hidden="true" />

      {/* Snapshot metrics — FLOP `.metrics` band */}
      <section
        aria-label="Snapshot"
        className="relative z-10 border-b border-border bg-surface/40"
      >
        <div className="mx-auto max-w-screen-2xl px-4 py-3 sm:px-6">
          <StatBand>
            <UpdatedStat iso={feed.generated_at} />
            <StatBandItem label="Ranked" value={`${stats.ranked}`} />
            <StatBandItem label="Considered" value={`${stats.considered}`} />
            <StatBandItem label="Average" value={formatScore(stats.avg)} tone="accent" />
            <StatBandItem
              label="Live"
              value={`${stats.live}`}
              hint="Idle under 60s"
              tone="good"
            />
            <StatBandItem label="Source" value="technocore.chat" />
          </StatBand>
        </div>
      </section>

      <p className="relative z-10 mx-auto w-full max-w-screen-2xl px-4 py-2 font-mono text-[11px] text-faint sm:px-6">
        Independent ranking of public Technocore rooms. Not affiliated with
        Flop Labs. Scores are heuristic. No airdrop guarantee.
      </p>

      <div className="relative z-10 mx-auto flex w-full max-w-screen-2xl items-center gap-2 px-4 pb-2 text-xs text-faint sm:px-6">
        <button
          type="button"
          onClick={() => setMethodOpen(true)}
          className="inline-flex h-7 items-center gap-1.5 rounded border border-border bg-surface px-2.5 font-mono text-xs text-fg transition-colors hover:border-accent hover:text-accent"
        >
          <Info className="size-3" />
          Method
        </button>
        <button
          type="button"
          onClick={copyFeedUrl}
          className="inline-flex h-7 items-center gap-1.5 rounded px-2.5 font-mono text-xs text-muted transition-colors hover:bg-surface hover:text-fg"
        >
          {copiedFeed ? <Check className="size-3" /> : <Copy className="size-3" />}
          Copy feed
        </button>
        <a
          href={JSON_PATH}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex h-7 items-center gap-1.5 rounded border border-accent/40 bg-accent/10 px-2.5 font-mono text-xs text-accent transition-colors hover:bg-accent/20"
        >
          JSON
          <ArrowUpRight className="size-3" />
        </a>
      </div>

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
                placeholder="Search rooms, topics, samples"
                aria-label="Search rooms"
                className="h-10 w-full rounded border border-border bg-surface pl-10 pr-3 font-mono text-sm text-fg placeholder:text-faint focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent/40"
              />
            </div>
            <FilterRow label="Kind" value={kind} options={KINDS} onChange={setKind} />
            <FilterRow label="Band" value={band} options={BANDS} onChange={setBand} />
            <FilterRow label="Sort" value={sort} options={SORTS} onChange={setSort} />
          </div>
          <div
            className="min-h-0 flex-1 px-2 py-2 pb-20 sm:px-3 lg:overflow-y-auto"
            role="listbox"
            aria-label="Ranked rooms"
          >
            {rooms.length === 0 ? (
              <div className="px-3 py-16 text-center">
                <p className="font-mono text-sm text-muted">No rooms match these filters.</p>
                <button
                  type="button"
                  className="mt-3 inline-flex h-9 items-center rounded border border-border bg-surface px-3 font-mono text-xs text-muted transition-colors hover:border-accent hover:text-fg"
                  onClick={() => {
                    setQuery("");
                    setKind("all");
                    setBand("all");
                    setSort("rank");
                  }}
                >
                  Reset filters
                </button>
              </div>
            ) : (
              <div className="flex flex-col gap-1">
                {visible.map((room) => (
                  <RoomRow
                    key={room.room}
                    room={room}
                    selected={selectedRoom?.room === room.room}
                    onSelect={selectRoom}
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
            {selectedRoom ? <RoomDetail room={selectedRoom} /> : <EmptyDetail />}
          </div>
        </aside>
      </div>

      {mobileOpen && selectedRoom ? (
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
            <RoomDetail room={selectedRoom} />
          </div>
        </div>
      ) : null}

      <footer className="relative z-10 border-t border-border">
        <div className="mx-auto flex max-w-screen-2xl flex-col gap-2 px-4 py-4 font-mono text-[11px] text-faint sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <p>
            Feed v{feed.version} · MIT · Read-only ·{" "}
            <a
              className="text-muted hover:text-accent"
              href={feed.source}
              target="_blank"
              rel="noopener noreferrer"
            >
              {feed.source.replace(/^https?:\/\//, "")}
            </a>
          </p>
          <p className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-[10px]">
              GET {JSON_PATH}
            </span>
            <span className="inline-flex items-center rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-[10px]">
              GET /api/v1/rooms.json
            </span>
          </p>
        </div>
      </footer>

      <MethodDialog open={methodOpen} onOpenChange={setMethodOpen} />
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
