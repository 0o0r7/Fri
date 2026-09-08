import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, Check, Copy, Info, Search, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { MethodDialog } from "@/components/method-dialog";
import { EmptyDetail, RoomDetail } from "@/components/room-detail";
import { RoomRow } from "@/components/room-row";
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
  const listRef = useRef<HTMLDivElement>(null);

  const stats = useMemo(() => snapshotStats(feed), [feed]);
  const rooms = useMemo(
    () => filterRooms(feed.rooms, { query, kind, band, sort }),
    [feed.rooms, query, kind, band, sort],
  );

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

      <section
        aria-label="Snapshot"
        className="relative z-10 border-b border-border bg-surface/60"
      >
        <dl className="mx-auto flex max-w-screen-2xl gap-6 overflow-x-auto px-4 py-3 sm:px-6">
          <UpdatedStat iso={feed.generated_at} />
          <Stat label="Ranked" value={`${stats.ranked}`} />
          <Stat label="Considered" value={`${stats.considered}`} />
          <Stat label="Average" value={formatScore(stats.avg)} />
          <Stat label="Live" value={`${stats.live}`} hint="Idle under 60s" />
          <Stat label="Source" value="technocore.chat" />
        </dl>
      </section>
      <p className="relative z-10 mx-auto w-full max-w-screen-2xl px-4 py-2 text-xs text-faint sm:px-6">
        Independent ranking of public Technocore rooms. Not affiliated with
        Flop Labs. Scores are heuristic. No airdrop guarantee.
      </p>
      <div className="relative z-10 mx-auto flex w-full max-w-screen-2xl items-center gap-2 px-4 pb-2 text-xs text-faint sm:px-6">
        <button
          type="button"
          onClick={() => setMethodOpen(true)}
          className="inline-flex h-7 items-center gap-1.5 rounded-md border border-border bg-elevated px-2.5 text-xs text-fg transition-colors hover:bg-elevated/70"
        >
          <Info className="size-3" />
          Method
        </button>
        <button
          type="button"
          onClick={copyFeedUrl}
          className="inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs text-muted transition-colors hover:bg-elevated hover:text-fg"
        >
          {copiedFeed ? <Check className="size-3" /> : <Copy className="size-3" />}
          Copy feed
        </button>
        <a
          href={JSON_PATH}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex h-7 items-center gap-1.5 rounded-md bg-accent/15 px-2.5 text-xs text-accent transition-colors hover:bg-accent/25"
        >
          JSON
          <ArrowUpRight className="size-3" />
        </a>
      </div>

      <div className="relative z-10 mx-auto grid min-h-0 w-full max-w-screen-2xl flex-1 grid-cols-1 lg:h-0 lg:grow lg:grid-cols-12 lg:overflow-hidden">
        <div className="flex min-h-0 flex-col border-border lg:col-span-5 lg:h-full lg:border-r">
          <div className="flex flex-col gap-2 px-4 py-3 sm:px-5">
            <div className="relative">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-faint" />
              <input
                ref={searchRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search rooms, topics, samples"
                aria-label="Search rooms"
                className="h-10 w-full rounded-md border border-border bg-elevated pl-10 pr-3 text-sm text-fg placeholder:text-faint focus:border-accent focus:ring-2 focus:ring-accent/30 focus:outline-none"
              />
            </div>
            <FilterRow
              label="Kind"
              value={kind}
              options={KINDS}
              onChange={setKind}
            />
            <FilterRow
              label="Band"
              value={band}
              options={BANDS}
              onChange={setBand}
            />
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
                    "h-11 min-w-11 rounded-md px-3 text-sm transition-colors duration-150 lg:h-9 lg:text-xs",
                    sort === s.id
                      ? "bg-elevated text-fg shadow-[var(--shadow-border)]"
                      : "text-muted hover:text-fg",
                  )}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>
          <div className="h-px bg-border" />
          <div
            ref={listRef}
            className="min-h-0 flex-1 px-2 py-2 pb-20 sm:px-3 lg:overflow-y-auto"
            role="listbox"
            aria-label="Ranked rooms"
          >
            {rooms.length === 0 ? (
              <div className="px-3 py-16 text-center">
                <p className="text-sm text-muted">No rooms match these filters.</p>
                <button
                  type="button"
                  className="mt-3 inline-flex h-9 items-center rounded-md px-3 text-sm text-muted transition-colors hover:bg-elevated hover:text-fg"
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
              <div className="flex flex-col gap-0.5">
                {rooms.map((room) => (
                  <RoomRow
                    key={room.room}
                    room={room}
                    selected={selectedRoom?.room === room.room}
                    onSelect={selectRoom}
                  />
                ))}
              </div>
            )}
          </div>
          <p className="hidden px-5 py-2 font-mono text-xs text-faint lg:block">
            j / k to move · / to search · {rooms.length} shown
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
            <RoomDetail room={selectedRoom} />
          </div>
        </div>
      ) : null}

      <footer className="relative z-10 border-t border-border">
        <div className="mx-auto flex max-w-screen-2xl flex-col gap-2 px-4 py-4 text-xs text-faint sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <p>
            Feed v{feed.version} · MIT · Read-only ·{" "}
            <a
              className="text-muted hover:text-fg"
              href={feed.source}
              target="_blank"
              rel="noopener noreferrer"
            >
              {feed.source.replace(/^https?:\/\//, "")}
            </a>
          </p>
          <p className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center rounded border border-border bg-elevated px-1.5 py-0.5 font-mono text-[10px]">
              GET {JSON_PATH}
            </span>
            <span className="inline-flex items-center rounded border border-border bg-elevated px-1.5 py-0.5 font-mono text-[10px]">
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
      <span className="mr-1 font-mono text-xs tracking-wider text-faint uppercase">
        {label}
      </span>
      {options.map((opt) => (
        <button
          key={opt.id}
          type="button"
          onClick={() => onChange(opt.id)}
          className={cn(
            "h-11 min-w-11 rounded-md px-3 text-sm transition-colors duration-150 lg:h-9 lg:text-xs",
            value === opt.id
              ? "bg-elevated text-fg shadow-[var(--shadow-border)]"
              : "text-muted hover:text-fg",
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
