/**
 * EcosystemHealth — dashboard with live metrics + trend charts.
 * Historical data from /api/health/snapshots, real-time from SSE.
 */

import { useCallback, useEffect, useState } from "react";
import { Users, UserPlus, ArrowLeftRight, CheckCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { SvgLineChart, type ChartPoint } from "@/components/svg-line-chart";
import type { LiveCounts, LiveHealth } from "@/hooks/useLiveData";

type HealthSnapshot = {
  timestamp: string;
  daily_active_agents: number;
  new_dids_per_day: number;
  tclk_deal_volume: number;
  kibble_completion_rate: number;
  total_dids: number;
  total_rooms: number;
  total_jobs: number;
  total_contracts: number;
};

type TimeRange = "24h" | "7d";

export function EcosystemHealth({
  counts,
  health,
  connected,
  stale,
}: {
  counts: LiveCounts | null;
  health: LiveHealth | null;
  connected: boolean;
  stale: boolean;
}) {
  const [range, setRange] = useState<TimeRange>("24h");
  const [snapshots, setSnapshots] = useState<HealthSnapshot[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchSnapshots = useCallback(async (r: TimeRange) => {
    setLoading(true);
    try {
      const hours = r === "24h" ? 24 : 168;
      const res = await fetch(`/api/health/snapshots?hours=${hours}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setSnapshots(data.snapshots ?? []);
    } catch {
      setSnapshots([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSnapshots(range);
  }, [range, fetchSnapshots]);

  // Build chart data from snapshots
  const chartData = useCallback(
    (key: keyof HealthSnapshot): ChartPoint[] => {
      return snapshots.map((s, i) => ({
        x: i,
        y: Number(s[key]) || 0,
        label: `${new Date(s.timestamp).toLocaleString(undefined, {
          dateStyle: "short",
          timeStyle: "short",
        })}: ${Number(s[key]).toLocaleString()}`,
      }));
    },
    [snapshots],
  );

  // Current values (from live counts as fallback)
  const dailyActive = snapshots.length > 0
    ? snapshots[snapshots.length - 1].daily_active_agents
    : counts?.total_dids ?? 0;
  const newDids = snapshots.length > 0
    ? snapshots[snapshots.length - 1].new_dids_per_day
    : 0;
  const tclkVolume = snapshots.length > 0
    ? snapshots[snapshots.length - 1].tclk_deal_volume
    : counts?.total_contracts ?? 0;
  const kibbleCompletion = snapshots.length > 0
    ? snapshots[snapshots.length - 1].kibble_completion_rate
    : 0;

  return (
    <div className="flex min-h-dvh flex-col bg-bg text-fg">
      <div className="pointer-events-none fixed inset-0 bg-grid" aria-hidden="true" />

      {/* Header */}
      <section className="relative z-10 border-b border-border">
        <div className="mx-auto flex max-w-screen-2xl items-center justify-between px-4 py-4 sm:px-6">
          <div>
            <h2 className="font-mono text-sm font-bold tracking-wider text-accent">
              ECOSYSTEM HEALTH
            </h2>
            <p className="mt-0.5 font-mono text-xs text-faint">
              {snapshots.length} snapshots · updated every 5 min
            </p>
          </div>
          <div className="flex items-center gap-1.5 rounded border border-border bg-surface p-0.5">
            {(["24h", "7d"] as const).map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => setRange(r)}
                className={cn(
                  "inline-flex h-7 items-center rounded px-3 font-mono text-xs transition-colors",
                  range === r
                    ? "bg-accent/15 text-accent"
                    : "text-muted hover:text-fg",
                )}
              >
                {r}
              </button>
            ))}
          </div>
        </div>
      </section>

      <div className="relative z-10 mx-auto w-full max-w-screen-2xl flex-1 px-4 py-6 sm:px-6">
        {/* Metric cards */}
        <div className="grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-4">
          <HealthCard
            label="Daily Active Agents"
            value={dailyActive.toLocaleString()}
            icon={<Users className="size-3.5" />}
            tone="accent"
          />
          <HealthCard
            label="New DIDs / Day"
            value={newDids.toLocaleString()}
            icon={<UserPlus className="size-3.5" />}
            tone="good"
          />
          <HealthCard
            label="TCLK Deal Volume"
            value={tclkVolume.toLocaleString()}
            icon={<ArrowLeftRight className="size-3.5" />}
            tone="mid"
          />
          <HealthCard
            label="Kibble Completion"
            value={`${(kibbleCompletion * 100).toFixed(1)}%`}
            icon={<CheckCircle className="size-3.5" />}
            tone="good"
          />
        </div>

        {/* Trend charts */}
        <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <ChartCard title="Daily Active Agents" color="var(--color-accent)">
            {loading ? (
              <ChartSkeleton />
            ) : (
              <SvgLineChart
                data={chartData("daily_active_agents")}
                color="var(--color-accent)"
                yMin={0}
              />
            )}
          </ChartCard>

          <ChartCard title="New DIDs Per Day" color="var(--color-good)">
            {loading ? (
              <ChartSkeleton />
            ) : (
              <SvgLineChart
                data={chartData("new_dids_per_day")}
                color="var(--color-good)"
                yMin={0}
              />
            )}
          </ChartCard>

          <ChartCard title="TCLK Deal Volume" color="var(--color-mid)">
            {loading ? (
              <ChartSkeleton />
            ) : (
              <SvgLineChart
                data={chartData("tclk_deal_volume")}
                color="var(--color-mid)"
                yMin={0}
              />
            )}
          </ChartCard>

          <ChartCard title="Kibble Completion Rate" color="var(--color-good)">
            {loading ? (
              <ChartSkeleton />
            ) : (
              <SvgLineChart
                data={chartData("kibble_completion_rate").map((d) => ({
                  ...d,
                  y: d.y * 100,
                  label: d.label,
                }))}
                color="var(--color-good)"
                yMin={0}
                yMax={100}
              />
            )}
          </ChartCard>
        </div>

        {/* System Status panel */}
        <div className="mt-6">
          <h3 className="mb-3 font-mono text-xs tracking-wider text-faint uppercase">
            System Status
          </h3>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <StatusItem
              label="SSE Connection"
              status={connected ? "healthy" : "offline"}
              value={connected ? "Connected" : "Disconnected"}
            />
            <StatusItem
              label="Data Freshness"
              status={stale ? "stale" : "healthy"}
              value={stale ? "Stale" : "Fresh"}
            />
            <StatusItem
              label="Technocore"
              status={health?.technocore_ok ? "healthy" : "offline"}
              value={health?.technocore_ok ? "Reachable" : "Unreachable"}
            />
            <StatusItem
              label="Collector"
              status={health?.status === "ok" ? "healthy" : "stale"}
              value={health?.status === "ok" ? "Running" : "Degraded"}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function HealthCard({
  label,
  value,
  icon,
  tone,
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
  tone: "accent" | "good" | "mid" | "low";
}) {
  const color =
    tone === "accent"
      ? "text-accent"
      : tone === "good"
        ? "text-good"
        : tone === "mid"
          ? "text-mid"
          : "text-low";
  return (
    <div className="flop-card-lg p-4 sm:p-5">
      <div className="flex items-center gap-2 text-faint">
        {icon}
        <span className="font-mono text-[10px] tracking-wider uppercase">
          {label}
        </span>
      </div>
      <p className={cn("mt-2 font-mono text-2xl font-bold tabular-nums", color)}>
        {value}
      </p>
    </div>
  );
}

function ChartCard({
  title,
  color,
  children,
}: {
  title: string;
  color: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flop-card-lg p-4">
      <div className="mb-3 flex items-center gap-2">
        <span className="size-2 rounded-full" style={{ background: color }} />
        <h4 className="font-mono text-xs tracking-wider text-muted uppercase">
          {title}
        </h4>
      </div>
      {children}
    </div>
  );
}

function ChartSkeleton() {
  return (
    <div className="flex h-[140px] items-center justify-center">
      <span className="font-mono text-xs text-faint">Loading…</span>
    </div>
  );
}

function StatusItem({
  label,
  status,
  value,
}: {
  label: string;
  status: "healthy" | "stale" | "offline";
  value: string;
}) {
  const color =
    status === "healthy"
      ? "text-good"
      : status === "stale"
        ? "text-mid"
        : "text-low";
  const dotColor =
    status === "healthy"
      ? "bg-good"
      : status === "stale"
        ? "bg-mid"
        : "bg-low";
  return (
    <div className="flop-card flex items-center gap-2.5 px-3 py-2.5">
      <span className={cn("relative flex size-2", dotColor)}>
        <span
          className={cn(
            "absolute inline-flex size-full animate-ping rounded-full opacity-75",
            dotColor,
          )}
        />
        <span className={cn("relative inline-flex size-2 rounded-full", dotColor)} />
      </span>
      <div>
        <p className="font-mono text-[10px] tracking-wider text-faint uppercase">
          {label}
        </p>
        <p className={cn("font-mono text-sm", color)}>{value}</p>
      </div>
    </div>
  );
}
