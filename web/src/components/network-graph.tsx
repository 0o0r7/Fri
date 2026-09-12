/**
 * NetworkGraph — force-directed graph of agent-to-agent connections.
 * Uses d3-force for layout + SVG for rendering.
 * Nodes = agents (sized by reputation, colored by band).
 * Edges = shared room membership.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY, type Simulation } from "d3-force";
import { select } from "d3-selection";
import { zoom, zoomIdentity } from "d3-zoom";
import { cn } from "@/lib/utils";
import { reputationBand } from "@/lib/reputation-filter";
import { tinyDid } from "@/lib/format";
import type { DidIndex, DidStats, ReputationEntry, ReputationIndex } from "@/lib/types";

type GraphNode = {
  id: string;
  did: DidStats;
  reputation?: ReputationEntry;
  score: number;
  band: "high" | "medium" | "low";
  x: number;
  y: number;
  vx: number;
  vy: number;
};

type GraphLink = {
  source: string | GraphNode;
  target: string | GraphNode;
  weight: number;
};

const BAND_COLORS: Record<string, string> = {
  high: "var(--color-good)",
  medium: "var(--color-mid)",
  low: "var(--color-low)",
};

const MAX_NODES = 50;

export function NetworkGraph({
  didIndex,
  reputationIndex,
  onNavigateDid,
}: {
  didIndex: DidIndex;
  reputationIndex: ReputationIndex | null;
  onNavigateDid: (did: string) => void;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const simRef = useRef<Simulation<GraphNode, GraphLink> | null>(null);
  const [hovered, setHovered] = useState<{ node: GraphNode; x: number; y: number } | null>(null);
  const [bandFilter, setBandFilter] = useState<"all" | "high" | "mid" | "low">("all");
  const [roomFilter, setRoomFilter] = useState<string | null>(null);
  const [width, setWidth] = useState(800);
  const [height, setHeight] = useState(500);
  const [tick, setTick] = useState(0);

  // Build rep map
  const repMap = useMemo(() => {
    if (!reputationIndex) return new Map<string, ReputationEntry>();
    return new Map(reputationIndex.dids.map((d) => [d.did, d]));
  }, [reputationIndex]);

  // Compute top rooms
  const topRooms = useMemo(() => {
    const roomCounts = new Map<string, number>();
    for (const d of didIndex.dids) {
      for (const r of d.rooms) {
        roomCounts.set(r, (roomCounts.get(r) ?? 0) + 1);
      }
    }
    return [...roomCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
  }, [didIndex]);

  // Build graph data
  const { nodes, links } = useMemo(() => {
    // Sort by reputation score (or messages as fallback), take top N
    const sorted = [...didIndex.dids].sort((a, b) => {
      const ra = repMap.get(a.did)?.reputation_score ?? 0;
      const rb = repMap.get(b.did)?.reputation_score ?? 0;
      return rb - ra || b.messages_signed - a.messages_signed;
    });

    let filtered = sorted.slice(0, MAX_NODES);

    // Apply band filter — note: reputationBand() returns "medium", the UI
    // filter value is "mid"
    if (bandFilter !== "all") {
      filtered = filtered.filter((d) => {
        const rep = repMap.get(d.did);
        if (!rep) return bandFilter === "low";
        const band = reputationBand(rep.reputation_score);
        return band === (bandFilter === "mid" ? "medium" : bandFilter);
      });
    }

    // Apply room filter
    if (roomFilter) {
      filtered = filtered.filter((d) => d.rooms.includes(roomFilter));
    }

    const nodeSet = new Set(filtered.map((d) => d.did));

    const graphNodes: GraphNode[] = filtered.map((d, i) => {
      const rep = repMap.get(d.did);
      const score = rep?.reputation_score ?? 0;
      // Deterministic golden-angle (phyllotaxis) starting disc — evenly
      // spread, stable across reloads. The simulation is pre-warmed below so
      // users always see a settled layout.
      const startA = i * 2.399963229728653;
      const startR = Math.sqrt((i + 0.5) / Math.max(1, filtered.length)) * Math.min(width, height) * 0.35;
      return {
        id: d.did,
        did: d,
        reputation: rep,
        score,
        band: rep ? reputationBand(score) : "low",
        x: width / 2 + Math.cos(startA) * startR,
        y: height / 2 + Math.sin(startA) * startR,
        vx: 0,
        vy: 0,
      };
    });

    // Build edges from shared rooms
    const edgeMap = new Map<string, GraphLink>();
    for (let i = 0; i < filtered.length; i++) {
      for (let j = i + 1; j < filtered.length; j++) {
        const a = filtered[i];
        const b = filtered[j];
        const shared = a.rooms.filter((r) => b.rooms.includes(r));
        if (shared.length > 0) {
          const key = `${a.did}|${b.did}`;
          edgeMap.set(key, { source: a.did, target: b.did, weight: shared.length });
        }
      }
    }

    // Only keep edges where both endpoints are in the node set
    const graphLinks = [...edgeMap.values()].filter(
      (l) => nodeSet.has(l.source as string) && nodeSet.has(l.target as string),
    );

    return { nodes: graphNodes, links: graphLinks };
  }, [didIndex, repMap, bandFilter, roomFilter, width, height]);

  // Resize observer
  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        setWidth(e.contentRect.width);
        setHeight(Math.max(400, e.contentRect.height));
      }
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  // Run force simulation
  useEffect(() => {
    if (nodes.length === 0) return;

    const sim = forceSimulation<GraphNode>(nodes)
      .force("charge", forceManyBody().strength(-140))
      .force(
        "link",
        forceLink<GraphNode, GraphLink>(links)
          .id((d) => d.id)
          .distance((l) => 70 + 130 / l.weight)
          .strength((l) => Math.min(0.5, 0.04 + 0.06 * l.weight)),
      )
      .force("collide", forceCollide<GraphNode>((d) => nodeRadius(d) + 6).iterations(2))
      // Gentle gravity instead of forceCenter: it also holds disconnected
      // single-node components near the main cluster instead of letting
      // charge repulsion fling them to the canvas edges.
      .force("x", forceX<GraphNode>(width / 2).strength(0.045))
      .force("y", forceY<GraphNode>(height / 2).strength(0.06))
      .alphaDecay(0.02);

    simRef.current = sim;

    // Pre-warm the layout synchronously, then stop. Previously the sim ran
    // ~2000+ ticks with a React re-render per tick, so the tab showed a
    // minutes-long random mid-flight animation and often froze clumped.
    sim.tick(280);
    sim.on("tick", null);
    sim.stop();

    // Fit the settled layout into the viewport: scale + translate node
    // coordinates so the whole graph (incl. outlier components) is visible
    // and roughly centered. Links reference the same node objects, so they
    // follow automatically.
    if (width > 160 && height > 160) {
      const pad = 60;
      const xs = nodes.map((n) => n.x);
      const ys = nodes.map((n) => n.y);
      const bx = Math.min(...xs) - pad;
      const by = Math.min(...ys) - pad;
      const bw = Math.max(...xs) + pad - bx;
      const bh = Math.max(...ys) + pad - by;
      if (bw > 0 && bh > 0) {
        const k = Math.min((width - 2 * pad) / bw, (height - 2 * pad) / bh, 1.15);
        const cx = bx + bw / 2;
        const cy = by + bh / 2;
        for (const n of nodes) {
          n.x = (n.x - cx) * k + width / 2;
          n.y = (n.y - cy) * k + height / 2;
        }
      }
    }

    setTick((t) => t + 1);

    return () => {
      sim.stop();
      simRef.current = null;
    };
  }, [nodes, links, width, height]);

  // Pan/zoom — re-attach if the svg remounts (e.g. after the empty-state
  // branch unmounted it); resize deliberately does NOT reset the transform.
  const svgReady = nodes.length > 0;
  useEffect(() => {
    if (!svgReady || !svgRef.current) return;
    const svg = select(svgRef.current);
    const g = svg.select("g.zoom-layer");
    const zb = zoom<SVGSVGElement, unknown>().scaleExtent([0.3, 4]).on("zoom", (event) => {
      g.attr("transform", event.transform.toString());
    });
    svg.call(zb);
    svg.call(zb.transform, zoomIdentity);
    return () => {
      svg.on(".zoom", null);
    };
  }, [svgReady]);

  // Debounced re-render trigger
  const tickRef = useRef(0);
  tickRef.current = tick;

  function nodeRadius(d: GraphNode): number {
    const min = 6;
    const max = 28;
    return min + (max - min) * d.score;
  }

  function nodeColor(d: GraphNode): string {
    return BAND_COLORS[d.band] ?? "var(--color-faint)";
  }

  function edgeOpacity(l: GraphLink): number {
    return Math.min(0.4, 0.1 + l.weight * 0.08);
  }

  function edgeWidth(l: GraphLink): number {
    return Math.min(3, 0.5 + l.weight * 0.5);
  }

  return (
    <div className="flex min-h-dvh flex-col bg-bg text-fg">
      <div className="pointer-events-none fixed inset-0 bg-grid" aria-hidden="true" />

      {/* Filter bar */}
      <div className="relative z-10 border-b border-border px-4 py-3 sm:px-6">
        <div className="mx-auto flex max-w-screen-2xl flex-wrap items-center gap-3">
          <h2 className="font-mono text-sm font-bold tracking-wider text-accent">
            NETWORK GRAPH
          </h2>
          <span className="font-mono text-xs text-faint">
            {nodes.length} agents · {links.length} connections
          </span>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 font-mono text-[10px] tracking-wider text-faint uppercase">Band</span>
            {(["all", "high", "mid", "low"] as const).map((b) => (
              <button
                key={b}
                type="button"
                onClick={() => setBandFilter(b)}
                className={cn(
                  "inline-flex h-8 items-center rounded border px-2.5 font-mono text-xs transition-colors",
                  bandFilter === b
                    ? "border-accent bg-accent/10 text-accent"
                    : "border-border bg-surface text-muted hover:text-fg",
                )}
              >
                {b === "all" ? "Any" : b === "high" ? "High" : b === "mid" ? "Mid" : "Low"}
              </button>
            ))}
          </div>
          {topRooms.length > 0 && (
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
              {!roomFilter && topRooms.map((r) => (
                <button
                  key={r[0]}
                  type="button"
                  onClick={() => setRoomFilter(r[0])}
                  className="inline-flex items-center gap-1 rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-[10px] text-muted transition-colors hover:border-accent hover:text-accent"
                >
                  {r[0]}
                  <span className="text-faint tabular-nums">{r[1]}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Graph canvas */}
      <div ref={containerRef} className="relative z-10 flex-1 overflow-hidden" style={{ minHeight: "70vh" }}>
        {/* Legend */}
        <div className="pointer-events-none absolute top-3 left-3 z-20 flex flex-col gap-1.5 rounded border border-border bg-bg/80 px-3 py-2 backdrop-blur">
          <p className="font-mono text-[10px] tracking-wider text-faint uppercase">Legend</p>
          <div className="flex items-center gap-1.5">
            <span className="size-2.5 rounded-full" style={{ background: BAND_COLORS.high }} />
            <span className="font-mono text-[10px] text-muted">High (≥0.70)</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="size-2.5 rounded-full" style={{ background: BAND_COLORS.medium }} />
            <span className="font-mono text-[10px] text-muted">Mid (0.40–0.70)</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="size-2.5 rounded-full" style={{ background: BAND_COLORS.low }} />
            <span className="font-mono text-[10px] text-muted">Low (&lt;0.40)</span>
          </div>
          <p className="mt-1 font-mono text-[9px] text-faint">Node size = reputation</p>
          <p className="font-mono text-[9px] text-faint">Edge = shared rooms</p>
        </div>

        {nodes.length === 0 ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <p className="font-mono text-sm text-muted">No agents match this filter.</p>
          </div>
        ) : (
          <svg
            ref={svgRef}
            width={width}
            height={height}
            className="absolute inset-0"
            style={{ cursor: "grab" }}
          >
            <g className="zoom-layer">
              {/* Edges */}
              {links.map((l, i) => {
                const s = l.source as GraphNode;
                const t = l.target as GraphNode;
                return (
                  <line
                    key={i}
                    x1={s.x}
                    y1={s.y}
                    x2={t.x}
                    y2={t.y}
                    stroke="var(--color-muted)"
                    strokeWidth={edgeWidth(l)}
                    opacity={edgeOpacity(l)}
                  />
                );
              })}

              {/* Nodes */}
              {nodes.map((n) => (
                <g
                  key={n.id}
                  transform={`translate(${n.x},${n.y})`}
                  style={{ cursor: "pointer" }}
                  onMouseEnter={(e) => {
                    const rect = svgRef.current?.getBoundingClientRect();
                    if (rect) {
                      setHovered({ node: n, x: e.clientX - rect.left, y: e.clientY - rect.top });
                    }
                  }}
                  onMouseLeave={() => setHovered(null)}
                  onClick={() => onNavigateDid(n.id)}
                >
                  <circle
                    r={nodeRadius(n)}
                    fill={nodeColor(n)}
                    opacity={0.85}
                    stroke="var(--color-bg)"
                    strokeWidth={1.5}
                  />
                  <circle
                    r={nodeRadius(n) + 3}
                    fill="none"
                    stroke={nodeColor(n)}
                    strokeWidth={1}
                    opacity={0.3}
                  />
                </g>
              ))}
            </g>
          </svg>
        )}

        {/* Hover tooltip */}
        {hovered && (
          <div
            className="pointer-events-none absolute z-30 rounded-lg border border-border bg-elevated px-3 py-2 shadow-lg"
            style={{ left: hovered.x + 12, top: hovered.y + 12 }}
          >
            <p className="font-mono text-xs text-accent">{tinyDid(hovered.node.id)}</p>
            <p className="mt-1 font-mono text-[10px] text-muted">
              Score: <span className="text-fg">{hovered.node.score.toFixed(3)}</span>
            </p>
            <p className="font-mono text-[10px] text-muted">
              Msgs: <span className="text-fg">{hovered.node.did.messages_signed}</span>
              {" · "}
              Rooms: <span className="text-fg">{hovered.node.did.rooms_active_in}</span>
            </p>
            <p className="mt-1 font-mono text-[9px] text-faint">Click to view profile →</p>
          </div>
        )}
      </div>

      <footer className="relative z-10 border-t border-border px-4 py-3 sm:px-6">
        <div className="mx-auto max-w-screen-2xl">
          <p className="font-mono text-[11px] text-faint">
            Graph derived from shared room membership in DidIndex · top {MAX_NODES} agents by reputation · pan & zoom enabled
          </p>
        </div>
      </footer>
    </div>
  );
}
