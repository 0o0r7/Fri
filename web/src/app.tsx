import { useEffect, useState } from "react";
import { Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import { IndexPage } from "@/components/index-page";
import { DidsPage } from "@/components/dids-page";
import { KibblePage } from "@/components/kibble-page";
import { TclkPage } from "@/components/tclk-page";
import { ReputationPage } from "@/components/reputation-page";
import { DidProfilePage } from "@/components/did-profile-page";
import { IndexPageSkeleton } from "@/components/skeleton";
import { LiveTicker } from "@/components/live-ticker";
import { FriMark } from "@/components/logo";
import { HeroSection } from "@/components/hero-section";
import { MobileNav } from "@/components/mobile-nav";
import { SiteFooter } from "@/components/site-footer";
import { LanguageSelector } from "@/components/language-selector";
import { AboutPage } from "@/components/pages/about-page";
import { HowItWorksPage } from "@/components/pages/how-it-works-page";
import { DocsPage } from "@/components/pages/docs-page";
import { PrivacyPage } from "@/components/pages/privacy-page";
import { TermsPage } from "@/components/pages/terms-page";
import { FaqPage } from "@/components/pages/faq-page";
import { cn } from "@/lib/utils";
import { didFromHash, didToHash } from "@/lib/did-profile";
import { useLiveData } from "@/hooks/useLiveData";
import type {
  DidIndex,
  Feed,
  KibbleIndex,
  ReputationIndex,
  TclkIndex,
} from "@/lib/types";

type Tab = "rooms" | "dids" | "kibble" | "tclk" | "reputation";
type PageInfo = "about" | "how-it-works" | "docs" | "privacy" | "terms" | "faq";

type View =
  | { kind: "tab"; tab: Tab }
  | { kind: "profile"; did: string }
  | { kind: "page"; page: PageInfo };

const TABS: { id: Tab; labelKey: string }[] = [
  { id: "rooms", labelKey: "nav.rooms" },
  { id: "dids", labelKey: "nav.dids" },
  { id: "kibble", labelKey: "nav.kibble" },
  { id: "tclk", labelKey: "nav.tclk" },
  { id: "reputation", labelKey: "nav.reputation" },
];

const INFO_PAGES: Record<string, PageInfo> = {
  "#about": "about",
  "#how-it-works": "how-it-works",
  "#docs": "docs",
  "#privacy": "privacy",
  "#terms": "terms",
  "#faq": "faq",
};

function viewFromHash(): View | null {
  if (typeof window === "undefined") return { kind: "tab", tab: "rooms" };
  const h = window.location.hash;
  const did = didFromHash(h);
  if (did) return { kind: "profile", did };
  const lower = h.toLowerCase();
  if (lower === "" || lower === "#") return { kind: "tab", tab: "rooms" };
  if (lower.startsWith("#dids")) return { kind: "tab", tab: "dids" };
  if (lower.startsWith("#kibble")) return { kind: "tab", tab: "kibble" };
  if (lower.startsWith("#tclk")) return { kind: "tab", tab: "tclk" };
  if (lower.startsWith("#reputation")) return { kind: "tab", tab: "reputation" };
  if (INFO_PAGES[lower]) return { kind: "page", page: INFO_PAGES[lower] };
  return null;
}

export function App() {
  const { t } = useTranslation();
  const {
    feed,
    dids,
    kibble,
    tclk,
    reputation,
    counts,
    liveMessages,
    connected,
    stale,
    lastUpdate,
    error,
  } = useLiveData();

  const [view, setView] = useState<View>(
    () => viewFromHash() ?? { kind: "tab", tab: "rooms" },
  );
  const [lookupInput, setLookupInput] = useState("");

  useEffect(() => {
    function onHash() {
      const next = viewFromHash();
      if (next) setView(next);
    }
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  function switchTab(tab: Tab) {
    window.location.hash = tab === "rooms" ? "" : `#${tab}`;
    setView({ kind: "tab", tab });
  }

  function navigateToDid(did: string) {
    if (!did) {
      switchTab("reputation");
      return;
    }
    window.location.hash = didToHash(did);
    setView({ kind: "profile", did });
  }

  function handleLookup(e: React.FormEvent) {
    e.preventDefault();
    const did = lookupInput.trim();
    if (did) {
      navigateToDid(did);
      setLookupInput("");
    }
  }

  // Info pages — render immediately, no live data needed
  if (view.kind === "page") {
    const navCounts = {
      dids: counts?.total_dids ?? dids?.total_dids ?? 0,
      kibble: counts?.total_jobs ?? kibble?.total_jobs ?? 0,
      tclk: counts?.total_contracts ?? tclk?.total_contracts ?? 0,
      reputation: counts?.total_dids_scored ?? reputation?.total_dids_scored ?? 0,
    };
    const pageMap: Record<PageInfo, React.ReactNode> = {
      about: <AboutPage />,
      "how-it-works": <HowItWorksPage />,
      docs: <DocsPage />,
      privacy: <PrivacyPage />,
      terms: <TermsPage />,
      faq: <FaqPage />,
    };
    return (
      <>
        <NavBar
          activeTab={null}
          lookupInput={lookupInput}
          onLookupChange={setLookupInput}
          onSubmitLookup={handleLookup}
          onLogoClick={() => switchTab("rooms")}
          onTabClick={switchTab}
          counts={navCounts}
          connected={connected}
          stale={stale}
          lastUpdate={lastUpdate}
          t={t}
        />
        {pageMap[view.page]}
        <SiteFooter />
      </>
    );
  }

  if (error && !feed) {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-3 px-6 text-center">
        <p className="font-mono text-sm text-low">Could not load live data</p>
        <p className="max-w-sm text-sm text-pretty text-muted">{error}</p>
        <p className="max-w-sm text-xs text-faint">
          The FRI backend is starting up — it fetches live data from technocore.chat.
          This can take a minute on first boot.
        </p>
      </div>
    );
  }

  if (!feed || !dids || !kibble || !tclk || !reputation)
    return <IndexPageSkeleton />;

  const navCounts = {
    dids: counts?.total_dids ?? dids.total_dids,
    kibble: counts?.total_jobs ?? kibble.total_jobs,
    tclk: counts?.total_contracts ?? tclk.total_contracts,
    reputation: counts?.total_dids_scored ?? reputation.total_dids_scored,
  };

  // DID profile view
  if (view.kind === "profile") {
    return (
      <>
        <NavBar
          activeTab="reputation"
          lookupInput={lookupInput}
          onLookupChange={setLookupInput}
          onSubmitLookup={handleLookup}
          onLogoClick={() => switchTab("reputation")}
          onTabClick={switchTab}
          counts={navCounts}
          connected={connected}
          stale={stale}
          lastUpdate={lastUpdate}
          t={t}
        />
        <LiveTicker messages={liveMessages} connected={connected} />
        <DidProfilePage
          did={view.did}
          didIndex={dids}
          kibbleIndex={kibble}
          tclkIndex={tclk}
          reputationIndex={reputation}
          onNavigateDid={navigateToDid}
        />
        <SiteFooter />
      </>
    );
  }

  // Tab views
  const tab = view.tab;
  return (
    <>
      <NavBar
        activeTab={tab}
        lookupInput={lookupInput}
        onLookupChange={setLookupInput}
        onSubmitLookup={handleLookup}
        onLogoClick={() => switchTab("rooms")}
        onTabClick={switchTab}
        counts={navCounts}
        connected={connected}
        stale={stale}
        lastUpdate={lastUpdate}
        t={t}
      />

      <LiveTicker messages={liveMessages} connected={connected} />
      <div className="pb-14 lg:pb-0">
        {tab === "rooms" ? (
          <>
            <HeroSection counts={counts} connected={connected} stale={stale} />
            <IndexPage feed={feed} />
          </>
        ) : tab === "dids" ? (
          <DidsPage index={dids} reputationIndex={reputation} />
        ) : tab === "kibble" ? (
          <KibblePage index={kibble} />
        ) : tab === "tclk" ? (
          <TclkPage index={tclk} />
        ) : (
          <ReputationPage index={reputation} />
        )}
      </div>
      <SiteFooter />
      <MobileNav
        activeTab={tab}
        onTabClick={switchTab}
        counts={navCounts}
      />
    </>
  );
}

function NavBar({
  activeTab,
  lookupInput,
  onLookupChange,
  onSubmitLookup,
  onLogoClick,
  onTabClick,
  counts,
  connected,
  stale,
  lastUpdate,
  t,
}: {
  activeTab: Tab | null;
  lookupInput: string;
  onLookupChange: (v: string) => void;
  onSubmitLookup: (e: React.FormEvent) => void;
  onLogoClick: () => void;
  onTabClick: (tab: Tab) => void;
  counts: { dids: number; kibble: number; tclk: number; reputation: number };
  connected: boolean;
  stale: boolean;
  lastUpdate: number;
  t: (key: string) => string;
}) {
  return (
    <nav className="sticky top-0 z-30 border-b border-border bg-bg/95 backdrop-blur supports-[backdrop-filter]:bg-bg/80">
      <div className="mx-auto flex max-w-screen-2xl flex-wrap items-center justify-between gap-3 px-4 py-2.5 sm:px-6">
        <button
          type="button"
          onClick={onLogoClick}
          className="group flex items-center gap-2.5"
          aria-label="FRI — Flop Reputation Index"
        >
          <FriMark />
          <div className="text-left leading-tight">
            <p className="font-mono text-sm font-bold tracking-[0.18em] text-accent">
              FRI
            </p>
            <h1 className="font-mono text-[11px] tracking-wide text-muted">
              flop reputation index
            </h1>
          </div>
        </button>

        <div className="flex items-center gap-2">
          <form onSubmit={onSubmitLookup} className="relative hidden sm:block">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-faint" />
            <input
              value={lookupInput}
              onChange={(e) => onLookupChange(e.target.value)}
              placeholder={t("nav.lookupPlaceholder")}
              spellCheck={false}
              autoComplete="off"
              aria-label="Lookup DID"
              className="h-8 w-56 rounded border border-border bg-surface pl-8 pr-2 font-mono text-xs text-fg placeholder:text-faint focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent/40 lg:w-72"
            />
          </form>
          <div
            className="hidden items-center gap-0 overflow-x-auto rounded border border-border bg-surface lg:flex"
            role="tablist"
            aria-label="Sections"
          >
            {TABS.map((tab) => (
              <TabButton
                key={tab.id}
                active={activeTab === tab.id}
                onClick={() => onTabClick(tab.id)}
                label={t(tab.labelKey)}
                count={
                  tab.id === "dids"
                    ? counts.dids
                    : tab.id === "kibble"
                      ? counts.kibble
                      : tab.id === "tclk"
                        ? counts.tclk
                        : tab.id === "reputation"
                          ? counts.reputation
                          : null
                }
              />
            ))}
          </div>
          <LanguageSelector compact />
        </div>
      </div>
    </nav>
  );
}

function TabButton({
  active,
  onClick,
  label,
  count,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number | null;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-8 shrink-0 items-center gap-1.5 border-b-2 px-3 font-mono text-xs tracking-wide transition-colors",
        active
          ? "border-accent text-accent"
          : "border-transparent text-muted hover:text-fg",
      )}
    >
      {label}
      {count != null ? <CountBadge value={count} active={active} /> : null}
    </button>
  );
}

function CountBadge({ value, active }: { value: number; active: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex min-w-5 items-center justify-center rounded px-1 font-mono text-[10px] tabular-nums",
        active ? "bg-accent/15 text-accent" : "bg-elevated text-faint",
      )}
    >
      {value.toLocaleString()}
    </span>
  );
}
