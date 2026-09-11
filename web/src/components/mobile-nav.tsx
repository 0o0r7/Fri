import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";

type Tab = "rooms" | "dids" | "kibble" | "tclk" | "reputation" | "network" | "health" | "sdk-guide";

const TABS: { id: Tab; labelKey: string }[] = [
  { id: "rooms", labelKey: "nav.rooms" },
  { id: "dids", labelKey: "nav.dids" },
  { id: "reputation", labelKey: "nav.reputation" },
  { id: "network", labelKey: "nav.network" },
  { id: "health", labelKey: "nav.health" },
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
  const { t } = useTranslation();
  return (
    <nav className="fixed bottom-0 left-0 right-0 z-30 border-t border-border bg-bg/95 backdrop-blur supports-[backdrop-filter]:bg-bg/80 lg:hidden">
      <div className="flex items-stretch justify-around">
        {TABS.map((tab) => {
          const count =
            tab.id === "dids"
              ? counts.dids
              : tab.id === "kibble"
                ? counts.kibble
                : tab.id === "tclk"
                  ? counts.tclk
                  : tab.id === "reputation"
                    ? counts.reputation
                    : null;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => onTabClick(tab.id)}
              className={cn(
                "flex flex-1 flex-col items-center gap-0.5 py-2 font-mono text-[10px] tracking-wide transition-colors",
                activeTab === tab.id
                  ? "text-accent"
                  : "text-faint hover:text-muted",
              )}
            >
              <span className="font-bold">{t(tab.labelKey)}</span>
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
