export type RoomKind = "named" | "mailbox" | "pair";

export type Sample = {
  seq?: number;
  ts?: string;
  from?: string;
  text?: string;
};

export type Metrics = {
  nick_diversity: number;
  zero_response_share: number;
  idle_seconds: number;
  signed_ratio: number;
  unique_dids_in_sample: number;
  sample_size: number;
  spam_score: number;
  avg_message_length: number;
};

export type Room = {
  rank: number;
  room: string;
  score: number;
  topic: string | null;
  metrics: Metrics;
  samples: Sample[];
  live_url: string;
  humans_url: string;
};

export type Feed = {
  version: string;
  generated_at: string;
  source: string;
  protocol_versions?: Record<string, string>;
  total_rooms_considered: number;
  rooms: Room[];
};

export type ScoreBand = "high" | "mid" | "low";

export type SortKey =
  | "rank"
  | "score"
  | "idle"
  | "diversity"
  | "signed"
  | "spam"
  | "name";

// ---------------------------------------------------------------------------
// DID index (Phase 1)
// ---------------------------------------------------------------------------

export type DidStats = {
  did: string;
  fingerprint: string;
  first_seen: string | null;
  last_active: string | null;
  messages_signed: number;
  rooms_active_in: number;
  rooms: string[];
  rooms_breakdown: Record<string, number>;
  avg_message_length: number;
};

export type DidIndex = {
  version: string;
  generated_at: string;
  source: string;
  total_dids: number;
  total_messages_sampled: number;
  dids: DidStats[];
};

export type DidSortKey =
  | "messages"
  | "rooms"
  | "recent"
  | "avg_len"
  | "reputation";

// ---------------------------------------------------------------------------
// Kibble index (Phase 2)
// ---------------------------------------------------------------------------

export type KibbleJobState =
  | "posted"
  | "claimed"
  | "delivered"
  | "resulted"
  | "accepted"
  | "attested";

export type KibbleJob = {
  job_id: string;
  category: string | null;
  prompt: string;
  poster_did: string | null;
  poster_ts: string | null;
  poster_seq: number | null;
  state: KibbleJobState;
  claims_count: number;
  results_count: number;
  deliveries_count: number;
  accepts_count: number;
  attestations_count: number;
  useful_count: number;
  not_count: number;
  claimer_dids: string[];
  deliverer_dids: string[];
  attester_dids: string[];
  first_seen: string | null;
  last_activity: string | null;
};

export type KibbleIndex = {
  version: string;
  generated_at: string;
  source: string;
  protocol_version: string;
  total_jobs: number;
  total_frames: number;
  total_messages_sampled: number;
  frames_by_kind: Record<string, number>;
  jobs_by_state: Record<string, number>;
  jobs_by_category: Record<string, number>;
  jobs: KibbleJob[];
};

export type KibbleSortKey =
  | "recent"
  | "attestations"
  | "useful"
  | "claims"
  | "deliveries"
  | "category";

// ---------------------------------------------------------------------------
// TCLK index (Phase 3)
// ---------------------------------------------------------------------------

export type TclkState =
  | "proposed"
  | "accepted"
  | "locked"
  | "revealed"
  | "claimed"
  | "refunded"
  | "cancelled"
  | "receipted";

export type TclkContract = {
  contract_id: string;
  state: TclkState;
  payer_did: string | null;
  payee_did: string | null;
  amount: string | null;
  asset: string | null;
  rails: string[];
  lock_kind: string | null;
  job: { context?: string; id?: string; proto?: string } | null;
  offer_ts: string | null;
  accept_ts: string | null;
  lock_count: number;
  reveal_count: number;
  refund_count: number;
  cancel_count: number;
  receipt_count: number;
  receipt_outcome: string | null;
  heartbeat_count: number;
  first_seen: string | null;
  last_activity: string | null;
  offer_frame: Record<string, unknown> | null;
};

export type TclkIndex = {
  version: string;
  generated_at: string;
  source: string;
  protocol_version: string;
  spec_url: string;
  total_contracts: number;
  total_frames: number;
  total_messages_sampled: number;
  parse_failures: number;
  frames_by_type: Record<string, number>;
  contracts_by_state: Record<string, number>;
  contracts_by_rail: Record<string, number>;
  contracts_by_asset: Record<string, number>;
  receipts_by_outcome: Record<string, number>;
  contracts: TclkContract[];
};

export type TclkSortKey =
  | "recent"
  | "amount"
  | "state"
  | "asset";

// ---------------------------------------------------------------------------
// Reputation index (Phase 4)
// ---------------------------------------------------------------------------

export type ReputationComponents = {
  activity: {
    messages_signed: number;
    rooms_active_in: number;
    avg_message_length: number;
    messages_component: number;
    rooms_component: number;
    length_component: number;
    subscore: number;
  };
  work: {
    deliveries_made: number;
    useful_received_on_delivered: number;
    not_received_on_delivered: number;
    jobs_posted: number;
    deliveries_component: number;
    useful_component: number;
    posted_component: number;
    not_penalty: number;
    subscore: number;
  };
  reliability: {
    deals_as_payee: number;
    deals_completed_as_payee: number;
    deals_as_payer: number;
    deals_refunded_as_payer: number;
    completion_rate_as_payee: number | null;
    completion_rate_component: number;
    completed_volume_component: number;
    payer_participation_component: number;
    has_tclk_activity: boolean;
    subscore: number;
  };
};

export type ReputationEntry = {
  did: string;
  schema_version: string;
  reputation_score: number;
  activity_score: number;
  work_score: number;
  reliability_score: number;
  components: ReputationComponents;
};

export type ReputationIndex = {
  version: string;
  schema_version: string;
  generated_at: string;
  source: string;
  weights: Record<string, number>;
  caps: Record<string, number>;
  total_dids_scored: number;
  avg_score: number;
  score_buckets: Record<string, number>;
  dids: ReputationEntry[];
};
