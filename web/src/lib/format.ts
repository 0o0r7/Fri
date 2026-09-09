import { formatDistanceToNowStrict, parseISO } from "date-fns";
import type { RoomKind } from "./types";

export function formatIdle(sec: number | null | undefined): string {
  if (sec == null || Number.isNaN(sec)) return "—";
  if (sec < 60) return `${Math.round(sec)}s`;
  if (sec < 3600) return `${Math.round(sec / 60)}m`;
  if (sec < 86400) return `${Math.round(sec / 3600)}h`;
  return `${Math.round(sec / 86400)}d`;
}

export function formatRatio(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toFixed(digits);
}

export function formatScore(v: number): string {
  return v.toFixed(1);
}

export function shortFrom(from: string | undefined): string {
  if (!from) return "?";
  if (from.startsWith("did:key:"))
    return `${from.slice(8, 16)}…`;
  if (from.startsWith("~"))
    return from.length > 16 ? `${from.slice(0, 14)}…` : from;
  return from.length > 14 ? `${from.slice(0, 12)}…` : from;
}

export function relativeTime(iso: string | undefined): string {
  if (!iso) return "unknown";
  try {
    return `${formatDistanceToNowStrict(parseISO(iso))} ago`;
  } catch {
    return iso;
  }
}

export function absoluteTime(iso: string | undefined): string {
  if (!iso) return "unknown";
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

export function roomKind(name: string): RoomKind {
  if (name.startsWith("mb-pair-")) return "pair";
  if (name.startsWith("mb-")) return "mailbox";
  return "named";
}

export function kindLabel(kind: RoomKind): string {
  if (kind === "named") return "Named";
  if (kind === "mailbox") return "Mailbox";
  return "Pair";
}

// ---------------------------------------------------------------------------
// DID helpers (Phase 1)
// ---------------------------------------------------------------------------

/** Short display form for a DID: did:key:z6Mkqztv… */
export function shortDid(did: string | undefined | null): string {
  if (!did) return "?";
  if (did.startsWith("did:key:")) {
    const key = did.slice(8);
    return `${key.slice(0, 12)}…`;
  }
  return did.length > 14 ? `${did.slice(0, 12)}…` : did;
}

/** Very short form: z6Mkqztv… (no prefix) */
export function tinyDid(did: string | undefined | null): string {
  if (!did) return "?";
  const stripped = did.startsWith("did:key:") ? did.slice(8) : did;
  return stripped.length > 8 ? `${stripped.slice(0, 8)}…` : stripped;
}

/** Group a fingerprint into the sharded form flopkit uses: 4f / 541151fd42c677 */
export function shardedFingerprint(fingerprint: string): { shard: string; key: string } {
  return {
    shard: fingerprint.slice(0, 2),
    key: fingerprint.slice(2),
  };
}

/** Technocore DID note URL for a fingerprint (read-only). */
export function didNoteUrl(fingerprint: string): string {
  const { shard, key } = shardedFingerprint(fingerprint);
  return `https://technocore.chat/kv/did-${shard}/${key}`;
}

/** Technocore live-room URL for a room name. */
export function liveRoomUrl(room: string): string {
  return `https://technocore.chat/r/${encodeURIComponent(room)}`;
}
