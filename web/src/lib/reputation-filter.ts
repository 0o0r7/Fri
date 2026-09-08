import type { ReputationEntry, ReputationIndex } from "./types";

export type RepSortKey = "reputation" | "activity" | "work" | "reliability";

export function filterReputation(
  dids: ReputationEntry[],
  opts: {
    query: string;
    sort: RepSortKey;
  },
): ReputationEntry[] {
  const q = opts.query.trim().toLowerCase();
  const list = q
    ? dids.filter(
        (d) =>
          d.did.toLowerCase().includes(q) ||
          d.components.work.deliveries_made > 0 ||
          d.components.reliability.deals_as_payee > 0 ||
          d.components.reliability.deals_as_payer > 0,
      )
    : dids;

  const sorted = [...list];
  sorted.sort((a, b) => {
    switch (opts.sort) {
      case "activity":
        return b.activity_score - a.activity_score;
      case "work":
        return b.work_score - a.activity_score;
      case "reliability":
        return b.reliability_score - a.reliability_score;
      case "reputation":
      default:
        return b.reputation_score - a.reputation_score;
    }
  });
  return sorted;
}

export function reputationBand(score: number): "high" | "medium" | "low" {
  if (score >= 0.7) return "high";
  if (score >= 0.4) return "medium";
  return "low";
}

export function reputationStats(idx: ReputationIndex) {
  const dids = idx.dids;
  const n = dids.length;
  const scores = dids.map((d) => d.reputation_score);
  const avg = n ? scores.reduce((a, b) => a + b, 0) / n : 0;
  const max = n ? Math.max(...scores) : 0;
  const withWork = dids.filter((d) => d.components.work.deliveries_made > 0).length;
  const withTclk = dids.filter((d) => d.components.reliability.has_tclk_activity).length;
  return {
    total_scored: n,
    avg_score: avg,
    max_score: max,
    with_work: withWork,
    with_tclk: withTclk,
    buckets: idx.score_buckets,
  };
}
