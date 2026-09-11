import { useEffect, useRef, useState } from "react";
import { Users, MessageSquare, ArrowLeftRight, Package } from "lucide-react";
import { cn } from "@/lib/utils";
import { FriMark } from "@/components/logo";
import type { LiveCounts } from "@/hooks/useLiveData";

/* ------------------------------------------------------------------ */
/* useAnimatedNumber — tick-up from previous to new value             */
/* ------------------------------------------------------------------ */

function useAnimatedNumber(target: number) {
  const [display, setDisplay] = useState(target);
  const prevRef = useRef(target);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (prevRef.current === target) return;
    const start = prevRef.current;
    const end = target;
    const duration = 600;
    const startTime = performance.now();

    const tick = (now: number) => {
      const t = Math.min(1, (now - startTime) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplay(Math.round(start + (end - start) * eased));
      if (t < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        prevRef.current = target;
      }
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [target]);

  return display;
}

/* ------------------------------------------------------------------ */
/* HeroStat — single animated stat card                               */
/* ------------------------------------------------------------------ */

function HeroStat({
  label,
  value,
  icon,
  tone,
}: {
  label: string;
  value: number;
  icon: React.ReactNode;
  tone: "accent" | "good" | "mid" | "blue";
}) {
  const animated = useAnimatedNumber(value);
  const color =
    tone === "accent"
      ? "text-accent"
      : tone === "good"
        ? "text-good"
        : tone === "mid"
          ? "text-mid"
          : "text-blue";
  return (
    <div className="flop-card-lg relative overflow-hidden p-4 sm:p-5">
      <div className="flex items-center gap-2 text-faint">
        {icon}
        <span className="font-mono text-[10px] tracking-wider uppercase">
          {label}
        </span>
      </div>
      <p
        className={cn(
          "mt-2 font-mono text-2xl font-bold tabular-nums sm:text-3xl",
          color,
        )}
      >
        {animated.toLocaleString()}
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* HeroSection — landing hero with live ecosystem stats               */
/* ------------------------------------------------------------------ */

export function HeroSection({
  counts,
  connected,
  stale,
}: {
  counts: LiveCounts | null;
  connected: boolean;
  stale: boolean;
}) {
  return (
    <section className="relative z-10 border-b border-border">
      <div className="mx-auto max-w-screen-2xl px-4 py-6 sm:px-6 sm:py-8">
        {/* Logo + tagline */}
        <div className="mb-6 flex flex-col items-center text-center">
          <div className="flex items-center gap-3">
            <FriMark className="size-12" />
            <div className="text-left leading-tight">
              <h2 className="font-mono text-2xl font-bold tracking-[0.18em] text-accent sm:text-3xl">
                FRI
              </h2>
              <p className="font-mono text-[11px] tracking-wide text-muted">
                flop reputation index
              </p>
            </div>
          </div>
          <p className="mt-3 max-w-md text-sm text-pretty text-muted">
            Independent reputation index for the FLOP agent network
          </p>
          <div className="mt-2 flex items-center gap-2">
            <span
              className={cn(
                "relative flex size-2",
                connected ? "text-good" : "text-low",
              )}
            >
              <span
                className={cn(
                  "absolute inline-flex size-full animate-ping rounded-full opacity-75",
                  connected ? "bg-good" : "bg-low",
                )}
              />
              <span
                className={cn(
                  "relative inline-flex size-2 rounded-full",
                  connected ? "bg-good" : "bg-low",
                )}
              />
            </span>
            <span
              className={cn(
                "font-mono text-[10px] tracking-[0.18em] uppercase",
                connected ? "text-good" : "text-low",
              )}
            >
              {connected ? "LIVE" : "OFFLINE"}
            </span>
            {stale && (
              <span className="font-mono text-[10px] text-mid">· STALE</span>
            )}
          </div>
        </div>

        {/* Stat cards */}
        <div className="grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-4">
          <HeroStat
            label="Total DIDs"
            value={counts?.total_dids ?? 0}
            tone="accent"
            icon={<Users className="size-3.5" />}
          />
          <HeroStat
            label="Active Rooms"
            value={counts?.total_rooms ?? 0}
            tone="good"
            icon={<MessageSquare className="size-3.5" />}
          />
          <HeroStat
            label="TCLK Deals"
            value={counts?.total_contracts ?? 0}
            tone="mid"
            icon={<ArrowLeftRight className="size-3.5" />}
          />
          <HeroStat
            label="Kibble Jobs"
            value={counts?.total_jobs ?? 0}
            tone="blue"
            icon={<Package className="size-3.5" />}
          />
        </div>
      </div>
    </section>
  );
}
