import type {
  DidIndex,
  DidStats,
  KibbleIndex,
  KibbleJob,
  ReputationEntry,
  ReputationIndex,
  TclkContract,
  TclkIndex,
} from "./types";

export type DidProfile = {
  did: string;
  // From dids.json
  didStats: DidStats | null;
  // From reputation.json
  reputation: ReputationEntry | null;
  // From kibble.json — jobs this DID participated in
  kibbleJobsPosted: KibbleJob[];
  kibbleJobsClaimed: KibbleJob[];
  kibbleJobsDelivered: KibbleJob[];
  kibbleJobsAttested: KibbleJob[];
  // From tclk.json — contracts this DID participated in
  tclkAsPayer: TclkContract[];
  tclkAsPayee: TclkContract[];
  // Derived
  found: boolean;
};

/**
 * Build a unified DID profile by cross-referencing all indices.
 *
 * This is O(n) per lookup (scans all kibble jobs and TCLK contracts) but
 * with ~150 kibble jobs and ~700 TCLK contracts, it's fast enough for
 * a single-DID lookup. For bulk lookups, precompute a DID→jobs index.
 */
export function buildDidProfile(
  did: string,
  didIndex: DidIndex,
  kibbleIndex: KibbleIndex,
  tclkIndex: TclkIndex,
  reputationIndex: ReputationIndex,
): DidProfile {
  // DID stats
  const didStats = didIndex.dids.find((d) => d.did === did) ?? null;

  // Reputation
  const reputation =
    reputationIndex.dids.find((d) => d.did === did) ?? null;

  // Kibble jobs — scan all jobs and filter by DID participation
  const kibbleJobsPosted: KibbleJob[] = [];
  const kibbleJobsClaimed: KibbleJob[] = [];
  const kibbleJobsDelivered: KibbleJob[] = [];
  const kibbleJobsAttested: KibbleJob[] = [];

  for (const job of kibbleIndex.jobs) {
    if (job.poster_did === did) kibbleJobsPosted.push(job);
    if (job.claimer_dids.includes(did)) kibbleJobsClaimed.push(job);
    if (job.deliverer_dids.includes(did)) kibbleJobsDelivered.push(job);
    if (job.attester_dids.includes(did)) kibbleJobsAttested.push(job);
  }

  // TCLK contracts — scan all contracts and filter by payer/payee
  const tclkAsPayer: TclkContract[] = [];
  const tclkAsPayee: TclkContract[] = [];

  for (const contract of tclkIndex.contracts) {
    if (contract.payer_did === did) tclkAsPayer.push(contract);
    if (contract.payee_did === did) tclkAsPayee.push(contract);
  }

  const found =
    didStats !== null ||
    reputation !== null ||
    kibbleJobsPosted.length > 0 ||
    kibbleJobsClaimed.length > 0 ||
    kibbleJobsDelivered.length > 0 ||
    kibbleJobsAttested.length > 0 ||
    tclkAsPayer.length > 0 ||
    tclkAsPayee.length > 0;

  return {
    did,
    didStats,
    reputation,
    kibbleJobsPosted,
    kibbleJobsClaimed,
    kibbleJobsDelivered,
    kibbleJobsAttested,
    tclkAsPayer,
    tclkAsPayee,
    found,
  };
}

/**
 * Extract a DID from a hash like `#did=did:key:z6Mk...`.
 * Returns null if the hash doesn't contain a valid DID lookup.
 */
export function didFromHash(hash: string): string | null {
  const h = hash.replace(/^#/, "");
  if (h.startsWith("did=")) {
    return decodeURIComponent(h.slice(4));
  }
  return null;
}

/**
 * Build the hash for a DID profile link.
 */
export function didToHash(did: string): string {
  return `#did=${encodeURIComponent(did)}`;
}
