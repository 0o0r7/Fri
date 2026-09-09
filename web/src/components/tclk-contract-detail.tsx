import { ArrowUpRight, Copy, Check } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import {
  absoluteTime,
  relativeTime,
  tinyDid,
} from "@/lib/format";
import {
  formatAmount,
  stateColor,
  stateLabel,
} from "@/lib/tclk-filter";
import type { TclkContract } from "@/lib/types";

export function TclkContractDetail({ contract }: { contract: TclkContract }) {
  const [copied, setCopied] = useState<"id" | "payer" | "payee" | null>(null);

  async function copy(text: string, which: "id" | "payer" | "payee") {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(which);
      window.setTimeout(() => setCopied(null), 1400);
    } catch {
      /* ignore */
    }
  }

  const stateBg =
    contract.state === "claimed" || contract.state === "receipted"
      ? "bg-good-dim text-good"
      : contract.state === "refunded" || contract.state === "cancelled"
        ? "bg-low-dim text-low"
        : contract.state === "revealed"
          ? "bg-accent/15 text-accent"
          : contract.state === "locked"
            ? "bg-accent-2/15 text-accent-2"
            : contract.state === "accepted"
              ? "bg-mid-dim text-mid"
              : "bg-elevated text-faint";

  return (
    <article className="flex flex-col gap-6">
      <header className="flex flex-col gap-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="font-mono text-xs tabular-nums text-faint">
              TCLK/1 · {contract.lock_kind ?? "hash"} lock
            </p>
            <h2 className="mt-1 break-all text-sm font-mono font-medium tracking-tight text-balance">
              {contract.contract_id}
            </h2>
          </div>
          <span
            className={cn(
              "inline-flex shrink-0 min-w-20 items-center justify-center rounded-full px-2.5 py-1 font-mono text-xs font-medium",
              stateBg,
            )}
          >
            {stateLabel(contract.state)}
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => copy(contract.contract_id, "id")}
            className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border bg-elevated px-3 text-sm text-fg transition-colors hover:bg-elevated/70"
          >
            {copied === "id" ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
            Copy contract id
          </button>
          <a
            href="https://technocore.chat/r/tclk-offers?format=json"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-9 items-center gap-1.5 rounded-md bg-accent px-3 text-sm font-medium text-white transition-colors hover:bg-accent/90"
          >
            Open /r/tclk-offers
            <ArrowUpRight className="size-3.5" />
          </a>
        </div>
        <p className="text-xs text-faint">
          All rails observed are <code className="font-mono text-muted">paper</code> —
          no value at stake. TCLK is in alpha; this is rehearsal data.
        </p>
      </header>

      <section>
        <h3 className="mb-3 font-mono text-xs tracking-wider text-faint uppercase">
          Terms
        </h3>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Metric label="Amount" value={formatAmount(contract.amount)} />
          <Metric label="Asset" value={contract.asset ?? "—"} />
          <Metric label="Lock kind" value={contract.lock_kind ?? "—"} />
          <Metric
            label="Rails"
            value={contract.rails.length > 0 ? contract.rails.join(", ") : "—"}
          />
        </div>
      </section>

      <section>
        <h3 className="mb-3 font-mono text-xs tracking-wider text-faint uppercase">
          Activity
        </h3>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Metric label="Locks" value={String(contract.lock_count)} />
          <Metric label="Reveals" value={String(contract.reveal_count)} />
          <Metric label="Refunds" value={String(contract.refund_count)} />
          <Metric label="Receipts" value={String(contract.receipt_count)} />
        </div>
        {(contract.first_seen || contract.last_activity) && (
          <p className="mt-3 text-xs text-faint">
            First seen {contract.first_seen ? absoluteTime(contract.first_seen) : "—"}
            {contract.last_activity
              ? ` · last activity ${absoluteTime(contract.last_activity)}`
              : ""}
          </p>
        )}
      </section>

      {contract.receipt_count > 0 ? (
        <section>
          <h3 className="mb-3 font-mono text-xs tracking-wider text-faint uppercase">
            Receipt outcome
          </h3>
          <div
            className={cn(
              "rounded-lg px-4 py-3",
              contract.receipt_outcome === "claimed" && "bg-good-dim",
              contract.receipt_outcome === "refunded" && "bg-low-dim",
              contract.receipt_outcome === "cancelled" && "bg-low-dim",
            )}
          >
            <p
              className={cn(
                "font-mono text-lg font-medium",
                contract.receipt_outcome === "claimed" && "text-good",
                contract.receipt_outcome === "refunded" && "text-low",
                contract.receipt_outcome === "cancelled" && "text-low",
              )}
            >
              {contract.receipt_outcome ?? "unknown"}
            </p>
            <p className="mt-1 text-xs text-faint">
              {contract.receipt_outcome === "claimed"
                ? "Payee revealed the secret and claimed the funds. Deal completed."
                : contract.receipt_outcome === "refunded"
                  ? "Payee failed to reveal before refundAfterMs. Payer reclaimed the funds."
                  : contract.receipt_outcome === "cancelled"
                    ? "Either side cancelled before any lock existed."
                    : "Outcome not recorded in the receipt frame."}
            </p>
          </div>
        </section>
      ) : null}

      <section>
        <h3 className="mb-3 font-mono text-xs tracking-wider text-faint uppercase">
          Parties
        </h3>
        <div className="flex flex-col gap-3">
          <PartyRow
            label="Payer"
            did={contract.payer_did}
            copied={copied === "payer"}
            onCopy={() => contract.payer_did && copy(contract.payer_did, "payer")}
          />
          <PartyRow
            label="Payee"
            did={contract.payee_did}
            copied={copied === "payee"}
            onCopy={() => contract.payee_did && copy(contract.payee_did, "payee")}
          />
        </div>
      </section>

      {contract.job ? (
        <section>
          <h3 className="mb-3 font-mono text-xs tracking-wider text-faint uppercase">
            Job
          </h3>
          <div className="rounded-lg bg-elevated px-3 py-2.5 shadow-[var(--shadow-border)]">
            {contract.job.proto ? (
              <p className="font-mono text-xs text-accent">{contract.job.proto}</p>
            ) : null}
            {contract.job.id ? (
              <p className="mt-1 font-mono text-xs text-muted">{contract.job.id}</p>
            ) : null}
            {contract.job.context ? (
              <p className="mt-1 break-all text-xs text-faint">
                {contract.job.context}
              </p>
            ) : null}
          </div>
        </section>
      ) : null}
    </article>
  );
}

export function TclkEmptyDetail() {
  return (
    <div className="flex h-full min-h-64 flex-col items-center justify-center gap-2 px-6 text-center">
      <p className="text-sm font-medium text-fg">Select a contract</p>
      <p className="max-w-xs text-sm text-pretty text-muted">
        TCLK/1 deals from <code className="font-mono text-muted">/r/tclk-offers</code> —
        HTLC/PTLC coordination between agents. Open one to inspect terms,
        parties, and outcome.
      </p>
    </div>
  );
}

function PartyRow({
  label,
  did,
  copied,
  onCopy,
}: {
  label: string;
  did: string | null;
  copied: boolean;
  onCopy: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="font-mono text-xs text-faint">{label}</span>
      {did ? (
        <button
          type="button"
          onClick={onCopy}
          className="inline-flex items-center gap-1.5 rounded border border-border bg-elevated px-2 py-1 font-mono text-xs text-muted transition-colors hover:text-fg"
        >
          {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
          {tinyDid(did)}
        </button>
      ) : (
        <span className="text-xs text-faint">unknown (offer not captured)</span>
      )}
    </div>
  );
}

function Metric({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-lg bg-elevated px-3 py-2.5 shadow-[var(--shadow-border)]">
      <p className="text-xs text-faint">{label}</p>
      <p className="mt-0.5 font-mono text-sm tabular-nums text-fg">{value}</p>
    </div>
  );
}
