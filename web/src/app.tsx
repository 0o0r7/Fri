import { useEffect, useState } from "react";
import { Search } from "lucide-react";
import { IndexPage } from "@/components/index-page";
import { DidsPage } from "@/components/dids-page";
import { KibblePage } from "@/components/kibble-page";
import { TclkPage } from "@/components/tclk-page";
import { ReputationPage } from "@/components/reputation-page";
import { DidProfilePage } from "@/components/did-profile-page";
import { IndexPageSkeleton } from "@/components/skeleton";
import { LiveTicker } from "@/components/live-ticker";
import { FriMark } from "@/components/logo";
import { cn } from "@/lib/utils";
import { didFromHash, didToHash } from "@/lib/did-profile";
import type {
  DidIndex,
  Feed,
  KibbleIndex,
  ReputationIndex,
  TclkIndex,
} from "@/lib/types";

const JSON_PATH = "/data/latest.json";
const DIDS_PATH = "/data/dids.json";
const KIBBLE_PATH = "/data/kibble.json";
const TCLK_PATH = "/data/tclk.json";
const REPUTATION_PATH = "/data/reputation.json";

type Tab = "rooms" | "dids" | "kibble" | "tclk" | "reputation";

type View =
  | { kind: "tab"; tab: Tab }
  | { kind: "profile"; did: string };

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
  // Unknown hash (e.g., #gpu-miners, #did:key:..., #k12345...) — don't change the view.
  // This prevents page-component hash updates from fighting with tab switching.
  return null;
}

export function App() {
  const [feed, setFeed] = useState<Feed | null>(null);
  const [dids, setDids] = useState<DidIndex | null>(null);
  const [kibble, setKibble] = useState<KibbleIndex | null>(null);
  const [tclk, setTclk] = useState<TclkIndex | null>(null);
  const [reputation, setReputation] = useState<ReputationIndex | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>(() => viewFromHash() ?? { kind: "tab", tab: "rooms" });
  const [lookupInput, setLookupInput] = useState("");

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetch(JSON_PATH).then((r) => {
        if (!r.ok) throw new Error(`rooms HTTP ${r.status}`);
        return r.json();
      }),
      fetch(DIDS_PATH).then((r) => {
        if (!r.ok) throw new Error(`dids HTTP ${r.status}`);
        return r.json();
      }),
      fetch(KIBBLE_PATH).then((r) => {
        if (!r.ok) throw new Error(`kibble HTTP ${r.status}`);
        return r.json();
      }),
      fetch(TCLK_PATH).then((r) => {
        if (!r.ok) throw new Error(`tclk HTTP ${r.status}`);
        return r.json();
      }),
      fetch(REPUTATION_PATH).then((r) => {
        if (!r.ok) throw new Error(`reputation HTTP ${r.status}`);
        return r.json();
      }),
    ])
      .then(([f, d, k, t, r]: [Feed, DidIndex, KibbleIndex, TclkIndex, ReputationIndex]) => {
        if (!cancelled) {
          setFeed(f);
          setDids(d);
          setKibble(k);
          setTclk(t);
          setReputation(r);
        }
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

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
      // Empty DID = go back to reputation tab
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

  if (error) {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-3 px-6 text-center">
        <p className="text-sm font-medium text-low">Could not load feed</p>
        <p className="max-w-sm text-sm text-pretty text-muted">{error}</p>
        <p className="max-w-sm text-xs text-faint">
          Run the collector:{" "}
          <code className="font-mono text-muted">
            python -m collector.main --once
          </code>
        </p>
      </div>
    );
  }

  if (!feed || !dids || !kibble || !tclk || !reputation)
    return <IndexPageSkeleton />;

  // DID profile view
  if (view.kind === "profile") {
    return (
      <>
        <nav className="sticky top-0 z-30 border-b border-border bg-bg/95 backdrop-blur supports-[backdrop-filter]:bg-bg/75">
          <div className="mx-auto flex max-w-screen-2xl items-center justify-between gap-3 px-4 py-2 sm:px-6">
            <button
              type="button"
              onClick={() => switchTab("reputation")}
              className="flex items-center gap-3"
            >
              <FriMark />
              <div className="text-left">
                <p className="font-mono text-xs tracking-widest text-accent">FRI</p>
                <h1 className="text-sm font-medium tracking-tight sm:text-base">
                  Flop Reputation Index
                </h1>
              </div>
            </button>
            <form onSubmit={handleLookup} className="relative">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-faint" />
              <input
                value={lookupInput}
                onChange={(e) => setLookupInput(e.target.value)}
                placeholder="Lookup did:key:..."
                className="h-8 w-48 rounded-md border border-border bg-elevated pl-8 pr-2 text-xs text-fg placeholder:text-faint focus:border-accent focus:ring-1 focus:ring-accent/30 focus:outline-none sm:w-64"
              />
            </form>
          </div>
        </nav>
        <LiveTicker />
        <DidProfilePage
          did={view.did}
          didIndex={dids}
          kibbleIndex={kibble}
          tclkIndex={tclk}
          reputationIndex={reputation}
          onNavigateDid={navigateToDid}
        />
      </>
    );
  }

  // Tab views
  const tab = view.tab;
  return (
    <>
      <nav className="sticky top-0 z-30 border-b border-border bg-bg/95 backdrop-blur supports-[backdrop-filter]:bg-bg/75">
        <div className="mx-auto flex max-w-screen-2xl items-center justify-between gap-3 px-4 py-2 sm:px-6">
          <div className="flex items-center gap-3">
            <FriMark />
            <div>
              <p className="font-mono text-xs tracking-widest text-accent">FRI</p>
              <h1 className="text-sm font-medium tracking-tight sm:text-base">
                Flop Reputation Index
              </h1>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <form onSubmit={handleLookup} className="relative hidden sm:block">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-faint" />
              <input
                value={lookupInput}
                onChange={(e) => setLookupInput(e.target.value)}
                placeholder="Lookup did:key:..."
                className="h-8 w-48 rounded-md border border-border bg-elevated pl-8 pr-2 text-xs text-fg placeholder:text-faint focus:border-accent focus:ring-1 focus:ring-accent/30 focus:outline-none"
              />
            </form>
            <div className="flex items-center gap-1 overflow-x-auto rounded-lg border border-border bg-elevated p-1">
              <TabButton active={tab === "rooms"} onClick={() => switchTab("rooms")}>
                Rooms
              </TabButton>
              <TabButton active={tab === "dids"} onClick={() => switchTab("dids")}>
                DIDs
                <CountBadge value={dids.total_dids} />
              </TabButton>
              <TabButton active={tab === "kibble"} onClick={() => switchTab("kibble")}>
                Kibble
                <CountBadge value={kibble.total_jobs} />
              </TabButton>
              <TabButton active={tab === "tclk"} onClick={() => switchTab("tclk")}>
                TCLK
                <CountBadge value={tclk.total_contracts} />
              </TabButton>
              <TabButton active={tab === "reputation"} onClick={() => switchTab("reputation")}>
                Reputation
                <CountBadge value={reputation.total_dids_scored} />
              </TabButton>
            </div>
          </div>
        </div>
      </nav>

      <LiveTicker />
      {tab === "rooms" ? (
        <IndexPage feed={feed} />
      ) : tab === "dids" ? (
        <DidsPage index={dids} />
      ) : tab === "kibble" ? (
        <KibblePage index={kibble} />
      ) : tab === "tclk" ? (
        <TclkPage index={tclk} />
      ) : (
        <ReputationPage index={reputation} />
      )}
    </>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex h-8 shrink-0 items-center rounded-md px-3 text-sm font-medium transition-colors",
        active ? "bg-accent text-white" : "text-muted hover:text-fg",
      )}
    >
      {children}
    </button>
  );
}

function CountBadge({ value }: { value: number }) {
  return (
    <span
      className={cn(
        "ml-1.5 inline-flex min-w-5 items-center justify-center rounded-full px-1.5 py-0.5 font-mono text-[10px] tabular-nums",
        "bg-bg/70 text-muted",
      )}
    >
      {value.toLocaleString()}
    </span>
  );
}
