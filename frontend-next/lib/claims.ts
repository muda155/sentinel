import type { Claim, ClaimEvidence } from "@/lib/api";

export type ClaimStatus = Claim["status"];

const ORDER: Record<ClaimStatus, number> = {
  disputed: 0, corroborated: 1, uncorroborated: 2,
};
const COLOR: Record<ClaimStatus, string> = {
  disputed: "#f87171", corroborated: "#4ade80", uncorroborated: "#9ca3af",
};

export function orderClaims(claims: Claim[]): Claim[] {
  return [...claims].sort((a, b) => ORDER[a.status] - ORDER[b.status]);
}

export function statusColor(status: ClaimStatus): string {
  return COLOR[status];
}

export function statusLabelKey(status: ClaimStatus): string {
  return `claims.${status === "uncorroborated" ? "uncorroborated" : status}`;
}

/** Split a claim's evidence into cited supporting vs contradicting sources,
 *  so a disputed claim can state WHICH sources disagree (FR-24). */
export function splitEvidence(claim: Claim): {
  supporting: ClaimEvidence[];
  contradicting: ClaimEvidence[];
} {
  const cited = claim.evidence.filter((e) => e.citation_index != null);
  return {
    supporting: cited.filter((e) => e.relation === "supports"),
    contradicting: cited.filter((e) => e.relation === "contradicts"),
  };
}
