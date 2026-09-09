import type { TclkContract, TclkIndex, TclkSortKey, TclkState } from "./types";

export type TclkStateFilter = "all" | TclkState;

const STATE_ORDER: Record<TclkState, number> = {
  proposed: 0,
  accepted: 1,
  locked: 2,
  revealed: 3,
  claimed: 4,
  receipted: 5,
  refunded: 6,
  cancelled: 7,
};

const STATE_COLORS: Record<TclkState, string> = {
  proposed: "text-faint",
  accepted: "text-mid",
  locked: "text-accent-2",
  revealed: "text-accent",
  claimed: "text-good",
  receipted: "text-good",
  refunded: "text-low",
  cancelled: "text-low",
};

const STATE_LABELS: Record<TclkState, string> = {
  proposed: "Proposed",
  accepted: "Accepted",
  locked: "Locked",
  revealed: "Revealed",
  claimed: "Claimed",
  receipted: "Receipted",
  refunded: "Refunded",
  cancelled: "Cancelled",
};

export function stateColor(state: TclkState): string {
  return STATE_COLORS[state] ?? "text-fg";
}

export function stateLabel(state: TclkState): string {
  return STATE_LABELS[state] ?? state;
}

export function stateOrder(state: TclkState): number {
  return STATE_ORDER[state] ?? 99;
}

export function filterContracts(
  contracts: TclkContract[],
  opts: {
    query: string;
    state: TclkStateFilter;
    sort: TclkSortKey;
  },
): TclkContract[] {
  const q = opts.query.trim().toLowerCase();
  const list = contracts.filter((c) => {
    if (opts.state !== "all" && c.state !== opts.state) return false;
    if (!q) return true;
    if (c.contract_id.toLowerCase().includes(q)) return true;
    if (c.payer_did?.toLowerCase().includes(q)) return true;
    if (c.payee_did?.toLowerCase().includes(q)) return true;
    if (c.asset?.toLowerCase().includes(q)) return true;
    if (c.rails.some((r) => r.toLowerCase().includes(q))) return true;
    if (c.job?.id?.toLowerCase().includes(q)) return true;
    if (c.job?.proto?.toLowerCase().includes(q)) return true;
    return false;
  });

  const sorted = [...list];
  sorted.sort((a, b) => {
    switch (opts.sort) {
      case "amount":
        return (
          (parseInt(b.amount ?? "0", 10) || 0) -
            (parseInt(a.amount ?? "0", 10) || 0) ||
          (b.last_activity ?? "").localeCompare(a.last_activity ?? "")
        );
      case "state":
        return (
          stateOrder(a.state) - stateOrder(b.state) ||
          (b.last_activity ?? "").localeCompare(a.last_activity ?? "")
        );
      case "asset":
        return (
          (a.asset ?? "zzz").localeCompare(b.asset ?? "zzz") ||
          (b.last_activity ?? "").localeCompare(a.last_activity ?? "")
        );
      case "recent":
      default:
        return (b.last_activity ?? "").localeCompare(a.last_activity ?? "");
    }
  });
  return sorted;
}

export function tclkIndexStats(idx: TclkIndex) {
  const contracts = idx.contracts;
  const total = contracts.length;
  const claimed = contracts.filter((c) => c.state === "claimed").length;
  const refunded = contracts.filter((c) => c.state === "refunded").length;
  const cancelled = contracts.filter((c) => c.state === "cancelled").length;
  // Refund rate = refunded / (claimed + refunded) — only counts terminal states
  const terminalClaimedRefund = claimed + refunded;
  const refundRate =
    terminalClaimedRefund > 0 ? refunded / terminalClaimedRefund : null;

  // Unique DIDs
  const uniquePayers = new Set(
    contracts.map((c) => c.payer_did).filter(Boolean),
  ).size;
  const uniquePayees = new Set(
    contracts.map((c) => c.payee_did).filter(Boolean),
  ).size;

  // Total volume (sum of amounts as integers — may be imprecise for large values)
  let totalVolume = 0;
  for (const c of contracts) {
    if (c.amount && c.asset === "FLOP") {
      totalVolume += parseInt(c.amount, 10) || 0;
    }
  }

  // Top payers by deal count
  const payerDeals = new Map<string, number>();
  for (const c of contracts) {
    if (c.payer_did) {
      payerDeals.set(c.payer_did, (payerDeals.get(c.payer_did) ?? 0) + 1);
    }
  }
  const topPayers = [...payerDeals.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([did, count]) => ({ did, count }));

  // Top payees by completed deals
  const payeeCompletions = new Map<string, number>();
  for (const c of contracts) {
    if (c.payee_did && c.state === "claimed") {
      payeeCompletions.set(c.payee_did, (payeeCompletions.get(c.payee_did) ?? 0) + 1);
    }
  }
  const topPayees = [...payeeCompletions.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([did, count]) => ({ did, count }));

  return {
    total_contracts: total,
    claimed,
    refunded,
    cancelled,
    refund_rate: refundRate,
    unique_payers: uniquePayers,
    unique_payees: uniquePayees,
    total_volume_flop: totalVolume,
    top_payers: topPayers,
    top_payees: topPayees,
    frames_by_type: idx.frames_by_type,
    contracts_by_state: idx.contracts_by_state,
    contracts_by_rail: idx.contracts_by_rail,
    contracts_by_asset: idx.contracts_by_asset,
    receipts_by_outcome: idx.receipts_by_outcome,
  };
}

/** Format an amount string (which may be very large) with thousand separators. */
export function formatAmount(amount: string | null): string {
  if (!amount) return "—";
  try {
    const n = BigInt(amount);
    return n.toLocaleString();
  } catch {
    return amount;
  }
}
