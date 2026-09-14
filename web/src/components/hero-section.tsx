import { useEffect, useRef, useState } from "react";
import { Users, MessageSquare, Flag } from "lucide-react";
import { cn } from "@/lib/utils";
import { tinyDid } from "@/lib/format";
import { useTranslation } from "react-i18next";
import type { LiveCounts } from "@/hooks/useLiveData";

/** Top-reputation DID that feeds the hero terminal lookup demo. */
export type HeroSample = {
  did: string;
  score: number;
  flags: string[];
  lastActive: string | null;
};

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
/* Terminal — typed lookup stream over real oracle data               */
/* ------------------------------------------------------------------ */

type TermToken = { cls: string; text: string };

/** Locale-neutral compact age ("12s"/"4m"/"3h"/"2d") — pure ASCII so the
 * dir="ltr" terminal stream never mixes bidi runs with translated labels. */
function compactAge(iso: string | null | undefined): string {
  if (!iso) return "—";
  const ms = Date.now() - Date.parse(iso);
  if (Number.isNaN(ms)) return "—";
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h`;
  return `${Math.round(h / 24)}d`;
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * Character budget for the typed stream. Rendering slices every token
 * against the budget, so the visual result is a per-character terminal
 * typing effect. When animation is off (tests, reduced motion) the full
 * text renders instantly and no timers run.
 */
function useTypedChars(total: number, animate: boolean): number {
  const [typed, setTyped] = useState(animate ? 0 : total);
  useEffect(() => {
    if (!animate) {
      setTyped(total);
      return;
    }
    let i = 0;
    let timer: number | undefined;
    const step = () => {
      i += 2;
      setTyped(Math.min(i, total));
      if (i < total) timer = window.setTimeout(step, 9);
    };
    timer = window.setTimeout(step, 350);
    return () => {
      if (timer) window.clearTimeout(timer);
    };
  }, [total, animate]);
  return typed;
}

function buildTerminalLines(sample: HeroSample | null): TermToken[][] {
  // Terminal stream stays English (authentic terminal aesthetic, matches the
  // approved design); translated titles live on the card chrome only.
  if (!sample) {
    return [
      [{ cls: "text-accent", text: "$ fri init" }],
      [
        { cls: "text-faint", text: "> source: " },
        { cls: "text-good", text: "technocore.chat" },
      ],
      [
        { cls: "text-faint", text: "> mode: " },
        { cls: "text-good", text: "read-only" },
      ],
      [
        { cls: "text-faint", text: "> status: " },
        { cls: "text-good", text: "syncing…" },
      ],
    ];
  }
  const active = sample.lastActive
    ? Date.now() - Date.parse(sample.lastActive) < 10 * 60_000
    : false;
  return [
    [{ cls: "text-accent", text: `$ fri lookup ${tinyDid(sample.did)}` }],
    [
      { cls: "text-faint", text: "> reputation: " },
      { cls: "text-good", text: sample.score.toFixed(2) },
    ],
    [
      { cls: "text-faint", text: "> status: " },
      { cls: "text-good", text: active ? "active" : "observed" },
    ],
    [
      { cls: "text-faint", text: "> flags: " },
      sample.flags.length
        ? { cls: "text-mid", text: sample.flags.join(" · ") }
        : { cls: "text-good", text: "none" },
    ],
    [
      { cls: "text-faint", text: "> updated: " },
      { cls: "text-good", text: compactAge(sample.lastActive) },
    ],
  ];
}

function TerminalCard({ sample }: { sample: HeroSample | null }) {
  const { t } = useTranslation();
  const lines = buildTerminalLines(sample);
  const total = lines.reduce(
    (n, toks) => n + toks.reduce((m, tok) => m + tok.text.length, 0),
    0,
  );
  const typed = useTypedChars(total, !prefersReducedMotion());
  let budget = typed;

  return (
    <div className="flop-card-lg fri-scanlines overflow-hidden shadow-[0_0_50px_rgba(0,240,255,0.05)]">
      <div className="flex items-center gap-1.5 border-b border-border bg-elevated/50 px-4 py-2.5">
        <span className="size-2.5 rounded-full bg-[#FF5F56]" />
        <span className="size-2.5 rounded-full bg-[#FFBD2E]" />
        <span className="size-2.5 rounded-full bg-[#27C93F]" />
        <span className="ml-2 font-mono text-[11px] tracking-wider text-faint">
          {sample ? t("hero.termTitle") : t("hero.termInitTitle")}
        </span>
      </div>
      <div
        dir="ltr"
        className="min-h-[230px] p-5 font-mono text-[13px] leading-[2.05] sm:text-sm"
      >
        {lines.map((toks, li) => (
          <div key={li}>
            {toks.map((tok, ti) => {
              const take = Math.max(0, Math.min(tok.text.length, budget));
              budget -= take;
              return (
                <span key={ti} className={tok.cls}>
                  {tok.text.slice(0, take)}
                </span>
              );
            })}
          </div>
        ))}
        <div>
          <span className="text-accent">$ </span>
          <span className="fri-cursor" aria-hidden="true" />
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* HeroStat — single animated stat card                               */
/* ------------------------------------------------------------------ */

function HeroStat({
  label,
  sub,
  value,
  icon,
  tone,
}: {
  label: string;
  sub?: string;
  value: number | null;
  icon: React.ReactNode;
  tone: "accent" | "fg" | "mid";
}) {
  const animated = useAnimatedNumber(value ?? 0);
  const color =
    tone === "accent" ? "text-accent" : tone === "mid" ? "text-mid" : "text-fg";
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
        {value == null ? "—" : animated.toLocaleString()}
      </p>
      {sub && <p className="mt-1 font-mono text-[10px] text-faint">{sub}</p>}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* HeroSection — "Trust, quantified." landing hero                    */
/* ------------------------------------------------------------------ */

export function HeroSection({
  counts,
  sample,
  stale,
}: {
  counts: LiveCounts | null;
  sample?: HeroSample | null;
  stale?: boolean;
}) {
  const { t } = useTranslation();
  const flagged = counts?.flagged_dids ?? 0;

  return (
    <section className="relative z-10 border-b border-border">
      <div className="mx-auto grid max-w-screen-2xl items-center gap-10 px-4 py-10 sm:px-6 sm:py-14 lg:grid-cols-[1.05fr_0.95fr] lg:gap-12">
        <div>
          <p className="font-mono text-xs tracking-[0.2em] text-accent">
            {t("hero.kicker")}
          </p>
          <h1
            dir="ltr"
            className="mt-4 font-mono text-4xl font-bold leading-[1.04] tracking-tight sm:text-5xl lg:text-[clamp(38px,5vw,56px)]"
          >
            Trust,
            <br />
            quantified.
            <span className="fri-cursor" aria-hidden="true" />
          </h1>
          <p className="mt-5 max-w-[46ch] text-[15px] leading-7 text-pretty text-muted">
            {t("hero.sub")}
          </p>

          <div className="mt-7 grid grid-cols-2 gap-3 lg:grid-cols-3">
            <HeroStat
              label={t("hero.statDids")}
              sub={t("hero.statDidsSub")}
              value={counts?.total_dids ?? 0}
              tone="accent"
              icon={<Users className="size-3.5" />}
            />
            <HeroStat
              label={t("hero.statMsgs")}
              sub={t("hero.statMsgsSub")}
              value={counts?.messages_observed ?? null}
              tone="fg"
              icon={<MessageSquare className="size-3.5" />}
            />
            {flagged > 0 && (
              <a
                href="#reputation"
                title={t("hero.flaggedHint")}
                className="flop-card-lg relative overflow-hidden border border-mid/40 bg-mid/[0.06] p-4 shadow-none transition-colors hover:bg-mid/15 sm:p-5"
              >
                <div className="flex items-center gap-2 text-mid/80">
                  <Flag className="size-3.5" />
                  <span className="font-mono text-[10px] tracking-wider uppercase">
                    {t("hero.statFlagged")}
                  </span>
                </div>
                <p className="mt-2 font-mono text-2xl font-bold tabular-nums text-mid sm:text-3xl">
                  <AnimatedFlaggedValue value={flagged} />
                </p>
                <p className="mt-1 font-mono text-[10px] text-mid/60">
                  {t("hero.statFlaggedSub")}
                </p>
              </a>
            )}
          </div>

          <div className="mt-7 flex flex-wrap gap-3">
            <a
              href="#dids"
              className="inline-flex h-11 items-center rounded-md bg-accent px-6 font-mono text-sm font-semibold text-[#04222B] transition-all hover:-translate-y-px hover:shadow-[0_0_26px_rgba(0,240,255,0.35)]"
            >
              {t("hero.ctaExplore")}
            </a>
            <a
              href="#how-it-works"
              className="inline-flex h-11 items-center rounded-md border border-border px-6 font-mono text-sm text-fg transition-colors hover:border-accent hover:text-accent"
            >
              {t("hero.ctaMethod")}
            </a>
          </div>

          {stale && (
            <p className="mt-4 font-mono text-[11px] text-mid">
              · {t("common.stale")}
            </p>
          )}
        </div>

        <TerminalCard sample={sample ?? null} />
      </div>
    </section>
  );
}

function AnimatedFlaggedValue({ value }: { value: number }) {
  const animated = useAnimatedNumber(value);
  return <>{animated.toLocaleString()}</>;
}
