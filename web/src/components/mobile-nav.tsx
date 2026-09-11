import { cn } from "@/lib/utils";

type Tab = "rooms" | "dids" | "kibble" | "tclk" | "reputation";

const TABS: { id: Tab; label: string }[] = [
  { id: "rooms", label: "Rooms" },
  { id: "dids", label: "DIDs" },
  { id: "kibble", label: "Kibble" },
  { id: "tclk", label: "TCLK" },
  { id: "reputation", label: "Rep" },
];

/**
 * MobileNav — fixed bottom tab bar for mobile.
 * Hidden on desktop (lg:hidden) where the top NavBar tabs are visible.
 */
export function MobileNav({
  activeTab,
  onTabClick,
  counts,
}: {
  activeTab: Tab;
  onTabClick: (tab: Tab) => void;
  counts: { dids: number; kibble: number; tclk: number; reputation: number };
}) {
  return (
    <nav className="fixed bottom-0 left-0 right-0 z-30 border-t border-border bg-bg/95 backdrop-blur supports-[backdrop-filter]:bg-bg/80 lg:hidden">
      <div className="flex items-stretch justify-around">
        {TABS.map((t) => {
          const count =
            t.id === "dids"
              ? counts.dids
              : t.id === "kibble"
                ? counts.kibble
                : t.id === "tclk"
                  ? counts.tclk
                  : t.id === "reputation"
                    ? counts.reputation
                    : null;
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => onTabClick(t.id)}
              className={cn(
                "flex flex-1 flex-col items-center gap-0.5 py-2 font-mono text-[10px] tracking-wide transition-colors",
                activeTab === t.id
                  ? "text-accent"
                  : "text-faint hover:text-muted",
              )}
            >
              <span className="font-bold">{t.label}</span>
              {count != null && (
                <span className="tabular-nums text-[9px]">
                  {count.toLocaleString()}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
