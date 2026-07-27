import { describe, expect, it } from "vitest";
import { orderClaims, splitEvidence, statusColor, statusLabelKey } from "@/lib/claims";
import type { Claim } from "@/lib/api";

const mk = (id: number, status: Claim["status"]): Claim => ({
  claim_id: id, claim_text: `c${id}`, status, evidence: [],
});

describe("claims helpers", () => {
  it("orders disputed first, corroborated second, single-source last", () => {
    const ordered = orderClaims([
      mk(1, "uncorroborated"), mk(2, "corroborated"), mk(3, "disputed"),
    ]);
    expect(ordered.map((c) => c.claim_id)).toEqual([3, 2, 1]);
  });

  it("maps status to color and i18n key", () => {
    expect(statusColor("disputed")).toBe("#f87171");
    expect(statusColor("corroborated")).toBe("#4ade80");
    expect(statusColor("uncorroborated")).toBe("#9ca3af");
    expect(statusLabelKey("disputed")).toBe("claims.disputed");
    expect(statusLabelKey("corroborated")).toBe("claims.corroborated");
    expect(statusLabelKey("uncorroborated")).toBe("claims.uncorroborated");
  });
});

describe("splitEvidence", () => {
  it("separates supporting from contradicting sources", () => {
    const claim: Claim = {
      claim_id: 1, claim_text: "Ten casualties were reported.", status: "disputed",
      evidence: [
        { event_id: 1, citation_index: 1, relation: "supports", probability: 0.9, domain: "a.com" },
        { event_id: 2, citation_index: 3, relation: "contradicts", probability: 0.88, domain: "b.com" },
        { event_id: 3, citation_index: 4, relation: "neutral", probability: 0.4, domain: "c.com" },
        { event_id: 4, citation_index: null, relation: "supports", probability: 0.7, domain: "d.com" },
      ],
    };
    const { supporting, contradicting } = splitEvidence(claim);
    expect(supporting.map((e) => e.citation_index)).toEqual([1]);
    expect(contradicting.map((e) => e.citation_index)).toEqual([3]);
  });
});
