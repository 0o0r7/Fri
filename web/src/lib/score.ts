import type { Metrics, ScoreBand } from "./types";

/** Mirrors collector/score.py WEIGHTS — display only, does not change scoring. */
export const WEIGHTS = {
  nickDiversity: 25,
  zeroResponse: 20,
  freshnessHot: 15,
  freshnessWarm: 8,
  freshnessCool: 3,
  signedRatio: 15,
  uniqueDids: 15,
  lengthGood: 8,
  lengthOk: 3,
  spamPenalty: 25,
  topicBonus: 4,
} as const;

export type ScorePart = {
  key: string;
  label: string;
  value: number;
  max: number;
  kind: "plus" | "minus";
};

export function scoreBand(score: number): ScoreBand {
  if (score >= 65) return "high";
  if (score >= 40) return "mid";
  return "low";
}

export function freshnessPoints(idle: number): number {
  if (idle < 300) return WEIGHTS.freshnessHot;
  if (idle < 1800) return WEIGHTS.freshnessWarm;
  if (idle < 7200) return WEIGHTS.freshnessCool;
  return 0;
}

export function lengthPoints(avg: number): number {
  if (avg >= 40 && avg <= 400) return WEIGHTS.lengthGood;
  if (avg > 15) return WEIGHTS.lengthOk;
  return 0;
}

export function scoreParts(metrics: Metrics, topic: string | null): ScorePart[] {
  const n = Math.max(metrics.sample_size, 1);
  const uniqueRatio = metrics.unique_dids_in_sample / n;
  const topicOk = Boolean(topic && topic.trim().length > 8);

  return [
    {
      key: "div",
      label: "Nick diversity",
      value: metrics.nick_diversity * WEIGHTS.nickDiversity,
      max: WEIGHTS.nickDiversity,
      kind: "plus",
    },
    {
      key: "resp",
      label: "Response rate",
      value: (1 - metrics.zero_response_share) * WEIGHTS.zeroResponse,
      max: WEIGHTS.zeroResponse,
      kind: "plus",
    },
    {
      key: "fresh",
      label: "Freshness",
      value: freshnessPoints(metrics.idle_seconds),
      max: WEIGHTS.freshnessHot,
      kind: "plus",
    },
    {
      key: "signed",
      label: "Signed ratio",
      value: metrics.signed_ratio * WEIGHTS.signedRatio,
      max: WEIGHTS.signedRatio,
      kind: "plus",
    },
    {
      key: "dids",
      label: "Unique DIDs",
      value: Math.min(uniqueRatio * 20, WEIGHTS.uniqueDids),
      max: WEIGHTS.uniqueDids,
      kind: "plus",
    },
    {
      key: "len",
      label: "Message length",
      value: lengthPoints(metrics.avg_message_length),
      max: WEIGHTS.lengthGood,
      kind: "plus",
    },
    {
      key: "topic",
      label: "Topic bonus",
      value: topicOk ? WEIGHTS.topicBonus : 0,
      max: WEIGHTS.topicBonus,
      kind: "plus",
    },
    {
      key: "spam",
      label: "Spam penalty",
      value: metrics.spam_score * WEIGHTS.spamPenalty,
      max: WEIGHTS.spamPenalty,
      kind: "minus",
    },
  ];
}
