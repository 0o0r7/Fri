import type { Feed, Room, RoomKind, SortKey } from "./types";
import { roomKind } from "./format";
import { scoreBand } from "./score";

export type KindFilter = "all" | RoomKind;
export type BandFilter = "all" | "high" | "mid" | "low";

export function filterRooms(
  rooms: Room[],
  opts: {
    query: string;
    kind: KindFilter;
    band: BandFilter;
    sort: SortKey;
  },
): Room[] {
  const q = opts.query.trim().toLowerCase();
  const list = rooms.filter((r) => {
    if (opts.kind !== "all" && roomKind(r.room) !== opts.kind) return false;
    if (opts.band !== "all" && scoreBand(r.score) !== opts.band) return false;
    if (!q) return true;
    if (r.room.toLowerCase().includes(q)) return true;
    if (r.topic?.toLowerCase().includes(q)) return true;
    return r.samples.some((s) => (s.text ?? "").toLowerCase().includes(q));
  });

  const sorted = [...list];
  sorted.sort((a, b) => {
    switch (opts.sort) {
      case "score":
        return b.score - a.score || a.rank - b.rank;
      case "idle":
        return a.metrics.idle_seconds - b.metrics.idle_seconds;
      case "diversity":
        return b.metrics.nick_diversity - a.metrics.nick_diversity;
      case "signed":
        return b.metrics.signed_ratio - a.metrics.signed_ratio;
      case "spam":
        return a.metrics.spam_score - b.metrics.spam_score;
      case "name":
        return a.room.localeCompare(b.room);
      default:
        return a.rank - b.rank;
    }
  });
  return sorted;
}

export function snapshotStats(feed: Feed) {
  const rooms = feed.rooms;
  const n = rooms.length;
  const scores = rooms.map((r) => r.score);
  const avg = n ? scores.reduce((a, b) => a + b, 0) / n : 0;
  const live = rooms.filter((r) => r.metrics.idle_seconds < 60).length;
  const named = rooms.filter((r) => roomKind(r.room) === "named").length;
  return {
    ranked: n,
    considered: feed.total_rooms_considered,
    avg,
    live,
    named,
    high: rooms.filter((r) => scoreBand(r.score) === "high").length,
    mid: rooms.filter((r) => scoreBand(r.score) === "mid").length,
    low: rooms.filter((r) => scoreBand(r.score) === "low").length,
  };
}
