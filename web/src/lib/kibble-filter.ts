import type { KibbleIndex, KibbleJob, KibbleJobState, KibbleSortKey } from "./types";

export type StateFilter = "all" | KibbleJobState;

export function filterJobs(
  jobs: KibbleJob[],
  opts: {
    query: string;
    state: StateFilter;
    sort: KibbleSortKey;
  },
): KibbleJob[] {
  const q = opts.query.trim().toLowerCase();
  const list = jobs.filter((j) => {
    if (opts.state !== "all" && j.state !== opts.state) return false;
    if (!q) return true;
    if (j.job_id.toLowerCase().includes(q)) return true;
    if (j.category?.toLowerCase().includes(q)) return true;
    if (j.prompt.toLowerCase().includes(q)) return true;
    if (j.poster_did?.toLowerCase().includes(q)) return true;
    return false;
  });

  const sorted = [...list];
  sorted.sort((a, b) => {
    switch (opts.sort) {
      case "attestations":
        return (
          b.attestations_count - a.attestations_count ||
          b.useful_count - a.useful_count ||
          (b.last_activity ?? "").localeCompare(a.last_activity ?? "")
        );
      case "useful":
        return (
          b.useful_count - a.useful_count ||
          b.attestations_count - a.attestations_count ||
          (b.last_activity ?? "").localeCompare(a.last_activity ?? "")
        );
      case "claims":
        return (
          b.claims_count - a.claims_count ||
          b.deliveries_count - a.deliveries_count ||
          (b.last_activity ?? "").localeCompare(a.last_activity ?? "")
        );
      case "deliveries":
        return (
          b.deliveries_count - a.deliveries_count ||
          b.claims_count - a.claims_count ||
          (b.last_activity ?? "").localeCompare(a.last_activity ?? "")
        );
      case "category":
        return (
          (a.category ?? "zzz").localeCompare(b.category ?? "zzz") ||
          (b.last_activity ?? "").localeCompare(a.last_activity ?? "")
        );
      case "recent":
      default:
        return (b.last_activity ?? "").localeCompare(a.last_activity ?? "");
    }
  });
  return sorted;
}

export function kibbleIndexStats(idx: KibbleIndex) {
  const jobs = idx.jobs;
  const total = jobs.length;
  const attested = jobs.filter((j) => j.state === "attested").length;
  const delivered = jobs.filter((j) =>
    ["delivered", "resulted", "accepted", "attested"].includes(j.state),
  ).length;
  const useful = jobs.reduce((acc, j) => acc + j.useful_count, 0);
  const not = jobs.reduce((acc, j) => acc + j.not_count, 0);
  const uniquePosters = new Set(jobs.map((j) => j.poster_did).filter(Boolean)).size;
  const uniqueWorkers = new Set(
    jobs.flatMap((j) => [...j.claimer_dids, ...j.deliverer_dids]),
  ).size;
  const uniqueAttesters = new Set(jobs.flatMap((j) => j.attester_dids)).size;

  // Top workers by deliveries
  const workerDeliveries = new Map<string, number>();
  for (const j of jobs) {
    for (const did of j.deliverer_dids) {
      workerDeliveries.set(did, (workerDeliveries.get(did) ?? 0) + 1);
    }
  }
  const topWorkers = [...workerDeliveries.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([did, count]) => ({ did, count }));

  return {
    total_jobs: total,
    attested_jobs: attested,
    delivered_jobs: delivered,
    useful_attestations: useful,
    not_attestations: not,
    unique_posters: uniquePosters,
    unique_workers: uniqueWorkers,
    unique_attesters: uniqueAttesters,
    top_workers: topWorkers,
    frames_by_kind: idx.frames_by_kind,
    jobs_by_state: idx.jobs_by_state,
    jobs_by_category: idx.jobs_by_category,
  };
}

const STATE_COLORS: Record<KibbleJobState, string> = {
  posted: "text-faint",
  claimed: "text-mid",
  delivered: "text-accent-2",
  resulted: "text-accent",
  accepted: "text-good",
  attested: "text-good",
};

const STATE_LABELS: Record<KibbleJobState, string> = {
  posted: "Posted",
  claimed: "Claimed",
  delivered: "Delivered",
  resulted: "Resulted",
  accepted: "Accepted",
  attested: "Attested",
};

export function stateColor(state: KibbleJobState): string {
  return STATE_COLORS[state] ?? "text-fg";
}

export function stateLabel(state: KibbleJobState): string {
  return STATE_LABELS[state] ?? state;
}
