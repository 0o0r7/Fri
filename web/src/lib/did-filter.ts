import type { DidIndex, DidSortKey, DidStats } from "./types";

export function filterDids(
  dids: DidStats[],
  opts: {
    query: string;
    sort: DidSortKey;
  },
): DidStats[] {
  const q = opts.query.trim().toLowerCase();
  const list = q
    ? dids.filter(
        (d) =>
          d.did.toLowerCase().includes(q) ||
          d.fingerprint.toLowerCase().includes(q) ||
          d.rooms.some((r) => r.toLowerCase().includes(q)),
      )
    : dids;

  const sorted = [...list];
  sorted.sort((a, b) => {
    switch (opts.sort) {
      case "messages":
        return b.messages_signed - a.messages_signed || b.rooms_active_in - a.rooms_active_in;
      case "rooms":
        return b.rooms_active_in - a.rooms_active_in || b.messages_signed - a.messages_signed;
      case "recent":
        return (
          (b.last_active ?? "").localeCompare(a.last_active ?? "") ||
          b.messages_signed - a.messages_signed
        );
      case "avg_len":
        return b.avg_message_length - a.avg_message_length;
      default:
        return b.messages_signed - a.messages_signed;
    }
  });
  return sorted;
}

export function didIndexStats(idx: DidIndex) {
  const dids = idx.dids;
  const n = dids.length;
  const totalMsgs = idx.total_messages_sampled;
  const signedMsgs = dids.reduce((acc, d) => acc + d.messages_signed, 0);
  const signedRatio = totalMsgs > 0 ? signedMsgs / totalMsgs : 0;
  const multiRoom = dids.filter((d) => d.rooms_active_in >= 2).length;
  const topRooms = new Map<string, number>();
  for (const d of dids) {
    for (const [room, count] of Object.entries(d.rooms_breakdown)) {
      topRooms.set(room, (topRooms.get(room) ?? 0) + count);
    }
  }
  const topRoomsList = [...topRooms.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([room, count]) => ({ room, count }));
  return {
    total_dids: idx.total_dids,
    sampled_messages: totalMsgs,
    signed_ratio: signedRatio,
    multi_room_dids: multiRoom,
    top_rooms: topRoomsList,
  };
}
