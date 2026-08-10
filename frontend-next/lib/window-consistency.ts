import type { Claim, ClaimEvidence, Hotspot, HotspotEvent } from "@/lib/api";
import type { ClaimStatus } from "@/lib/claims";
import { eventsInWindow, type Window } from "@/lib/window-metrics";

// pipeline/consistency.py: SENTINEL_NLI_MIN_PROB, SENTINEL_CONSISTENCY_DISPUTE_RATIO.
// Env-overridable server side and invisible here, which is what
// consistencyTrusted() exists to detect.
export const NLI_MIN_PROB = 0.6;
export const DISPUTE_RATIO = 0.5;
// pipeline/consistency.py uses .get(domain, 0.4) for a domain with no trust row.
const DEFAULT_TRUST = 0.4;
const RECONSTRUCT_TOLERANCE = 0.51;

const STATUS_VALUE: Record<ClaimStatus, number> = {
  corroborated: 1.0, uncorroborated: 0.5, disputed: 0.0,
};

export type ClaimOutcome = {
  claim_id: number;
  text: string;
  status: ClaimStatus | "unverifiable";
  support: number;
  dispute: number;
  weight: number;
};

export type WindowConsistency =
  | { mode: "score"; score: number; outcomes: ClaimOutcome[] }
  | { mode: "countsOnly"; outcomes: ClaimOutcome[] };

function trustByDomain(events: HotspotEvent[]): Map<string, number> {
  const map = new Map<string, number>();
  for (const e of events) if (!map.has(e.domain)) map.set(e.domain, e.trust_score);
  return map;
}

/** Strongest surviving judgment per domain — consistency.py:352-357. */
function bestPerDomain(evidence: ClaimEvidence[]): Map<string, ClaimEvidence> {
  const best = new Map<string, ClaimEvidence>();
  for (const j of evidence) {
    const p = j.probability;
    if (p == null || p < NLI_MIN_PROB || j.relation === "neutral") continue;
    const current = best.get(j.domain);
    if (current == null || p > (current.probability ?? 0)) best.set(j.domain, j);
  }
  return best;
}

function outcomeFor(c: Claim, allowedEventIds: Set<number>, trust: Map<string, number>): ClaimOutcome {
  // NULL origin_domains = written before migration 023. Treating it as an
  // empty set would let a claim's own sources corroborate it, so the honest
  // answer is that this claim cannot be evaluated here.
  if (c.origin_domains == null) {
    return { claim_id: c.claim_id, text: c.claim_text, status: "unverifiable", support: 0, dispute: 0, weight: 0 };
  }
  const origins = new Set(c.origin_domains);
  const best = bestPerDomain(c.evidence.filter((e) => allowedEventIds.has(e.event_id)));

  let support = 0;
  let dispute = 0;
  let supporters = 0;
  let contradictors = 0;
  for (const [domain, j] of best) {
    const w = (trust.get(domain) ?? DEFAULT_TRUST) * (j.probability ?? 0);
    if (j.relation === "supports") {
      if (origins.has(domain)) continue;
      support += w;
      supporters += 1;
    } else if (j.relation === "contradicts") {
      dispute += w;
      contradictors += 1;
    }
  }

  let status: ClaimStatus;
  if (contradictors > 0 && dispute >= DISPUTE_RATIO * support) status = "disputed";
  else if (supporters >= 2) status = "corroborated";
  else status = "uncorroborated";

  return {
    claim_id: c.claim_id, text: c.claim_text, status,
    support, dispute, weight: Math.max(support + dispute, 0.1),
  };
}

export function windowConsistency(claims: Claim[], events: HotspotEvent[], w: Window): WindowConsistency {
  const allowed = new Set(eventsInWindow(events, w).map((e) => e.event_id));
  const trust = trustByDomain(events);
  const outcomes = claims.map((c) => outcomeFor(c, allowed, trust));

  const scorable = outcomes.filter((o) => o.status !== "unverifiable");
  // Any unverifiable claim makes the aggregate wrong, not merely incomplete:
  // it would silently drop a claim from both numerator and denominator.
  if (scorable.length === 0 || scorable.length !== outcomes.length) {
    return { mode: "countsOnly", outcomes };
  }

  const totalWeight = scorable.reduce((s, o) => s + o.weight, 0);
  const weighted = scorable.reduce((s, o) => s + o.weight * STATUS_VALUE[o.status as ClaimStatus], 0);
  return { mode: "score", score: (100 * weighted) / totalWeight, outcomes };
}

/** Does this port of consistency.py reproduce the published score? */
export function consistencyTrusted(claims: Claim[], events: HotspotEvent[], h: Hotspot): boolean {
  if (h.consistency_score == null) return false;
  const dates = events.map((e) => Date.parse(e.event_date));
  if (dates.length === 0) return false;
  const full = {
    from: new Date(Math.min(...dates)).toISOString(),
    to: new Date(Math.max(...dates) + 1000).toISOString(),
  };
  const r = windowConsistency(claims, events, full);
  return r.mode === "score" && Math.abs(r.score - h.consistency_score) <= RECONSTRUCT_TOLERANCE;
}
