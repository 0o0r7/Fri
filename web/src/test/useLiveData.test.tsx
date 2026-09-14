/**
 * useLiveData static-mode boot: the hook must derive counts — including the
 * flagged_dids transparency counter — from the committed /data/*.json
 * snapshots when no backend answers, and stay stale-aware.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useLiveData } from "@/hooks/useLiveData";

const FIXTURES: Record<string, unknown> = {
  "/data/latest.json": {
    version: "1.1",
    generated_at: new Date().toISOString(),
    total_rooms_considered: 150,
    rooms: [{ room: "lobby" }, { room: "events" }],
    source: "https://technocore.chat",
  },
  "/data/dids.json": { total_dids: 2460, dids: [{ did: "did:key:a1" }] },
  "/data/kibble.json": { total_jobs: 152, jobs: [] },
  "/data/tclk.json": { total_contracts: 398, contracts: [] },
  "/data/reputation.json": {
    total_dids_scored: 500,
    dids: [],
    spam: { adjusted: true, flagged_dids: 16 },
  },
  "/data/health.json": { status: "ok" },
};

function stubStaticFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url === "/api/health") {
        // Probe fails → the hook must fall back to static snapshots
        return { ok: false, status: 404, json: async () => ({}) };
      }
      const hit = FIXTURES[url];
      if (hit === undefined) {
        return { ok: false, status: 404, json: async () => ({}) };
      }
      return { ok: true, status: 200, json: async () => hit };
    }),
  );
}

describe("useLiveData static fallback", () => {
  beforeEach(() => {
    stubStaticFetch();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("derives counts (incl. flagged_dids) from committed snapshots", async () => {
    const { result } = renderHook(() => useLiveData());

    // probeApi() burns one 1.5s retry before static boot kicks in
    await waitFor(() => expect(result.current.counts).not.toBeNull(), {
      timeout: 5000,
    });

    expect(result.current.counts).toMatchObject({
      total_dids: 2460,
      total_rooms: 150,
      total_jobs: 152,
      total_contracts: 398,
      total_dids_scored: 500,
      flagged_dids: 16,
    });
    // static mode: no SSE connection, fresh snapshot → not stale
    expect(result.current.connected).toBe(false);
    expect(result.current.stale).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("marks a snapshot older than one commit cycle as stale", async () => {
    FIXTURES["/data/latest.json"] = {
      ...(FIXTURES["/data/latest.json"] as Record<string, unknown>),
      generated_at: new Date(Date.now() - 5 * 60 * 60 * 1000).toISOString(),
    };
    const { result } = renderHook(() => useLiveData());

    await waitFor(() => expect(result.current.counts).not.toBeNull(), {
      timeout: 5000,
    });
    expect(result.current.stale).toBe(true);
    expect(result.current.health?.stale).toBe(true);
  });
});
